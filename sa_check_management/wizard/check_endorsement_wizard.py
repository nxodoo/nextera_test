from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CheckEndorsementWizard(models.TransientModel):
    _name = "check.endorsement.wizard"
    _description = "Endorse Check"

    check_id = fields.Many2one("check.check", required=True, readonly=True)
    currency_id = fields.Many2one(related="check_id.currency_id")
    company_id = fields.Many2one(related="check_id.company_id")
    customer_id = fields.Many2one(related="check_id.partner_id", string="Customer")
    available_amount = fields.Monetary(related="check_id.amount", string="Check Amount")
    partner_id = fields.Many2one(
        "res.partner", string="Endorse To", required=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    action_date = fields.Date(string="Endorsement Date", required=True, default=fields.Date.context_today)
    note = fields.Text()
    line_ids = fields.One2many("check.endorsement.wizard.line", "wizard_id", string="Bills")
    selected_amount = fields.Monetary(currency_field="currency_id", compute="_compute_amounts")
    remaining_amount = fields.Monetary(
        currency_field="currency_id", compute="_compute_amounts",
        help="Left as an advance to the endorsee.",
    )

    @api.depends("available_amount", "line_ids.selected", "line_ids.amount")
    def _compute_amounts(self):
        for wizard in self:
            wizard.selected_amount = sum(wizard.line_ids.filtered("selected").mapped("amount"))
            wizard.remaining_amount = wizard.available_amount - wizard.selected_amount

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        commands = [fields.Command.clear()]
        if self.partner_id and self.check_id:
            items = self.check_id._open_allocation_items(self.partner_id, "liability_payable")
            commands += [fields.Command.create(vals) for vals in self.check_id._document_summaries(items)]
        self.line_ids = commands

    def action_confirm(self):
        self.ensure_one()
        if self.action_date > fields.Date.context_today(self):
            raise UserError(_("The endorsement date cannot be in the future."))
        if self.partner_id.commercial_partner_id == self.check_id.partner_id.commercial_partner_id:
            raise UserError(_("A check cannot be endorsed back to its own drawer."))
        lines = self.line_ids.filtered(lambda line: line.selected and not self.currency_id.is_zero(line.amount))
        for line in lines:
            line._validate_amount()
        if self.currency_id.compare_amounts(sum(lines.mapped("amount")), self.available_amount) > 0:
            raise UserError(_("The selected bills exceed the check amount."))
        shares = []
        for line in lines:
            shares += line._distribution()
        self.check_id._apply_endorse(self.partner_id, self.action_date, shares, self.note)
        return {"type": "ir.actions.act_window_close"}


class CheckEndorsementWizardLine(models.TransientModel):
    _name = "check.endorsement.wizard.line"
    _description = "Endorse Check: Bill"
    _order = "date_due, id"

    wizard_id = fields.Many2one("check.endorsement.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    move_ref = fields.Integer(required=True, readonly=True)
    document_name = fields.Char(string="Bill", readonly=True)
    document_date = fields.Date(string="Date", readonly=True)
    date_due = fields.Date(string="First Due Date", readonly=True)
    installment_count = fields.Integer(string="Installments", readonly=True)
    open_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    selected = fields.Boolean()
    amount = fields.Monetary(string="Amount to Settle", currency_field="currency_id")

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
                "The amount for %(bill)s must be between zero and its open amount %(open)s.",
                bill=self.document_name, open=self.currency_id.format(self.open_amount),
            ))

    def _distribution(self):
        self.ensure_one()
        check = self.wizard_id.check_id
        items = check._open_allocation_items(self.wizard_id.partner_id, "liability_payable").filtered(
            lambda item: item.move_id.id == self.move_ref
        )
        return check._distribute_over_items(items, self.amount, check._reserved_amounts(items))
