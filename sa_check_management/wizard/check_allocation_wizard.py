from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CheckAllocationWizard(models.TransientModel):
    _name = "check.allocation.wizard"
    _description = "Add Invoices to Check"

    check_id = fields.Many2one("check.check", required=True, readonly=True, ondelete="cascade")
    currency_id = fields.Many2one(related="check_id.currency_id")
    available_amount = fields.Monetary(
        string="Available on Check", currency_field="currency_id", readonly=True,
    )
    line_ids = fields.One2many("check.allocation.wizard.line", "wizard_id", string="Documents")
    selected_amount = fields.Monetary(currency_field="currency_id", compute="_compute_amounts")
    remaining_amount = fields.Monetary(currency_field="currency_id", compute="_compute_amounts")

    @api.depends("available_amount", "line_ids.selected", "line_ids.amount")
    def _compute_amounts(self):
        for wizard in self:
            wizard.selected_amount = sum(wizard.line_ids.filtered("selected").mapped("amount"))
            wizard.remaining_amount = wizard.available_amount - wizard.selected_amount

    # ------------------------------------------------------------------
    # Opening
    # ------------------------------------------------------------------
    @api.model
    def _create_for_check(self, check):
        check._validate_allocation_editable()
        wizard = self.create({
            "check_id": check.id,
            "available_amount": check.unallocated_amount,
        })
        wizard.line_ids = [fields.Command.create(vals) for vals in wizard._document_line_vals()]
        return wizard

    def _document_line_vals(self):
        self.ensure_one()
        return self.check_id._document_summaries(self.check_id._open_allocation_items())

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------
    def action_confirm(self):
        self.ensure_one()
        self.check_id._validate_allocation_editable()
        lines = self._lines_to_allocate()
        self._validate_selection_total(lines)
        vals_list = []
        for line in lines:
            vals_list += line._distribution_vals()
        self.env["check.allocation"].sudo().create(vals_list)
        return {"type": "ir.actions.act_window_close"}

    def _lines_to_allocate(self):
        lines = self.line_ids.filtered(lambda line: line.selected and not self.currency_id.is_zero(line.amount))
        if not lines:
            raise UserError(_("Select at least one document and enter the amount to allocate."))
        for line in lines:
            line._validate_amount()
        return lines

    def _validate_selection_total(self, lines):
        total = sum(lines.mapped("amount"))
        available = self.check_id.unallocated_amount
        if self.currency_id.compare_amounts(total, available) > 0:
            raise UserError(_(
                "You selected %(selected)s but only %(available)s is left on the check.",
                selected=self.currency_id.format(total), available=self.currency_id.format(available),
            ))


class CheckAllocationWizardLine(models.TransientModel):
    _name = "check.allocation.wizard.line"
    _description = "Add Invoices to Check: Document"
    _order = "date_due, id"

    wizard_id = fields.Many2one("check.allocation.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    # Plain values (not a Many2one) so users without accounting rights can display the line.
    move_ref = fields.Integer(required=True, readonly=True)
    document_name = fields.Char(string="Document", readonly=True)
    document_date = fields.Date(string="Date", readonly=True)
    date_due = fields.Date(string="First Due Date", readonly=True)
    installment_count = fields.Integer(string="Installments", readonly=True)
    open_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    selected = fields.Boolean()
    amount = fields.Monetary(string="Amount to Allocate", currency_field="currency_id")

    @api.onchange("selected")
    def _onchange_selected(self):
        if not self.selected:
            self.amount = 0.0
        elif not self.amount:
            others = sum((self.wizard_id.line_ids - self).filtered("selected").mapped("amount"))
            self.amount = max(min(self.open_amount, self.wizard_id.available_amount - others), 0.0)

    def _validate_amount(self):
        self.ensure_one()
        if self.amount < 0 or self.currency_id.compare_amounts(self.amount, self.open_amount) > 0:
            raise UserError(_(
                "The amount for %(document)s must be between zero and its open amount %(open)s.",
                document=self.document_name, open=self.currency_id.format(self.open_amount),
            ))

    def _distribution_vals(self):
        """Spread the amount over the document's open installments, earliest due first."""
        self.ensure_one()
        check = self.wizard_id.check_id
        items = check._open_allocation_items().filtered(lambda item: item.move_id.id == self.move_ref)
        shares = check._distribute_over_items(items, self.amount, check._reserved_amounts(items))
        return [{"check_id": check.id, "move_line_id": item.id, "amount": share} for item, share in shares]
