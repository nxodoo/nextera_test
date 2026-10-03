from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.check_banking import CTX_INTERNAL_ACCOUNTING
from ..models.check_allocation import CTX_ALLOCATION_SYSTEM_WRITE

GROUP_MANAGER = "sa_check_management.group_check_manager"
GROUP_ACCOUNTANT = "sa_check_management.group_check_accountant"


class CheckReallocationWizard(models.TransientModel):
    """Repair a posted check whose invoice was unreconciled or cancelled from Accounting."""

    _name = "check.reallocation.wizard"
    _description = "Repair Check Allocations"

    check_id = fields.Many2one("check.check", required=True, readonly=True)
    currency_id = fields.Many2one(related="check_id.currency_id")
    open_line_ids = fields.One2many("check.reallocation.wizard.open", "wizard_id", string="Open Amounts")
    target_ids = fields.One2many("check.reallocation.wizard.target", "wizard_id", string="Other Open Documents")

    @api.model
    def _create_for_check(self, check):
        if not self.env.su and not (self.env.user.has_group(GROUP_MANAGER) or self.env.user.has_group(GROUP_ACCOUNTANT)):
            raise AccessError(_("Only a Check Manager or Check Accountant can repair allocations."))
        wizard = self.create({"check_id": check.id})
        wizard.open_line_ids = [fields.Command.create(vals) for vals in wizard._open_vals()]
        items = check._open_allocation_items()
        wizard.target_ids = [fields.Command.create(vals) for vals in check._document_summaries(items)]
        return wizard

    def _open_vals(self):
        self.ensure_one()
        vals_list = []
        for allocation in self.check_id.sudo().allocation_ids.filtered("payment_id"):
            counterpart = allocation.payment_id._seek_for_lines()[1]
            residual = abs(counterpart.amount_residual_currency)
            if self.currency_id.is_zero(residual):
                continue
            original = allocation.move_line_id
            same_open = original.parent_state == "posted" and not original.reconciled
            vals_list.append({
                "allocation_ref": allocation.id,
                "document_name": allocation.document_name,
                "open_amount": residual,
                "same_available": same_open,
                "resolution": "same" if same_open else "other",
            })
        return vals_list

    def action_confirm(self):
        self.ensure_one()
        check = self.check_id.sudo().with_context(**{CTX_INTERNAL_ACCOUNTING: True})
        notes = []
        for line in self.open_line_ids.filtered(lambda l: l.resolution == "same"):
            notes += line._reconcile_same(check)
        pool = self.open_line_ids.filtered(lambda l: l.resolution == "other")
        for target in self.target_ids.filtered("selected"):
            notes += target._absorb(check, pool)
        self._finish(check, notes)
        return {"type": "ir.actions.act_window_close"}

    def _finish(self, check, notes):
        if notes:
            check._log_event("accounting", note=_("Allocations repaired:\n%s", "\n".join(notes)))
        if not self._still_open(check):
            check.write({"accounting_attention": False, "accounting_attention_note": False})
            check._log_event("correction", note=_("Accounting review closed after repairing allocations."))

    def _still_open(self, check):
        open_lines = self.open_line_ids.filtered(lambda l: l.resolution != "credit")
        for line in open_lines:
            counterpart = line._allocation(check).payment_id._seek_for_lines()[1]
            if not check.currency_id.is_zero(counterpart.amount_residual_currency):
                return True
        return False


class CheckReallocationWizardOpen(models.TransientModel):
    _name = "check.reallocation.wizard.open"
    _description = "Repair Check Allocations: Open Amount"

    wizard_id = fields.Many2one("check.reallocation.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    allocation_ref = fields.Integer(required=True, readonly=True)
    document_name = fields.Char(string="Original Document", readonly=True)
    open_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    same_available = fields.Boolean(string="Original Still Open", readonly=True)
    resolution = fields.Selection(
        selection=[
            ("same", "Reconcile again with the original"),
            ("other", "Move to another document"),
            ("credit", "Keep as partner credit"),
        ],
        required=True, default="other",
    )

    def _allocation(self, check):
        return check.allocation_ids.browse(self.allocation_ref)

    def _reconcile_same(self, check):
        self.ensure_one()
        allocation = self._allocation(check)
        if not self.same_available:
            raise UserError(_("%s is no longer open; choose another resolution.", self.document_name))
        counterpart = allocation.payment_id._seek_for_lines()[1]
        (counterpart | allocation.move_line_id).reconcile()
        return [_("%s reconciled again", self.document_name)]


class CheckReallocationWizardTarget(models.TransientModel):
    _name = "check.reallocation.wizard.target"
    _description = "Repair Check Allocations: Target Document"
    _order = "date_due, id"

    wizard_id = fields.Many2one("check.reallocation.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    move_ref = fields.Integer(required=True, readonly=True)
    document_name = fields.Char(string="Document", readonly=True)
    document_date = fields.Date(string="Date", readonly=True)
    date_due = fields.Date(string="First Due Date", readonly=True)
    installment_count = fields.Integer(string="Installments", readonly=True)
    open_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    selected = fields.Boolean()

    def _absorb(self, check, pool):
        """Reconcile the pooled open payment amounts with this document, earliest installment first."""
        self.ensure_one()
        notes = []
        items = check._open_allocation_items().filtered(lambda item: item.move_id.id == self.move_ref)
        for item in items:
            for line in pool:
                allocation = line._allocation(check)
                counterpart = allocation.payment_id._seek_for_lines()[1]
                if check.currency_id.is_zero(counterpart.amount_residual_currency) or item.reconciled:
                    continue
                before = abs(counterpart.amount_residual_currency)
                (counterpart | item).reconcile()
                moved = before - abs(counterpart.amount_residual_currency)
                if moved > 0:
                    self._record_allocation(check, allocation, item, moved)
                    notes.append(_("%(amount)s moved from %(old)s to %(new)s",
                                   amount=check.currency_id.format(moved), old=line.document_name, new=self.document_name))
        return notes

    def _record_allocation(self, check, allocation, item, amount):
        writer = {CTX_ALLOCATION_SYSTEM_WRITE: True}
        existing = check.allocation_ids.filtered(lambda a: a.move_line_id == item)
        if existing:
            existing.with_context(**writer).write({"amount": existing.amount + amount})
        elif not self._still_linked(allocation):
            allocation.with_context(**writer).write({"move_line_id": item.id, "amount": amount})
        else:
            self.env["check.allocation"].sudo().with_context(**writer).create({
                "check_id": check.id, "move_line_id": item.id, "amount": amount,
                "payment_id": allocation.payment_id.id,
            })

    @staticmethod
    def _still_linked(allocation):
        """Is the allocation's document still reconciled with its payment?"""
        counterpart = allocation.payment_id._seek_for_lines()[1]
        partials = counterpart.matched_debit_ids | counterpart.matched_credit_ids
        return allocation.move_line_id in (partials.debit_move_id | partials.credit_move_id)
