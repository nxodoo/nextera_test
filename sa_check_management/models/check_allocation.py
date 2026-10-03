from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

CTX_ALLOCATION_SYSTEM_WRITE = "sa_check_allocation_system_write"

ACCOUNT_TYPE_BY_DIRECTION = {
    "incoming": "asset_receivable",
    "outgoing": "liability_payable",
}


class CheckAllocation(models.Model):
    _name = "check.allocation"
    _description = "Check Allocation"
    _order = "check_id, id"
    _check_company_auto = True

    _sql_constraints = [
        ("amount_positive", "CHECK(amount > 0)", "The allocated amount must be greater than zero."),
        ("line_unique", "UNIQUE(check_id, move_line_id)", "This journal item is already allocated on the check."),
    ]

    check_id = fields.Many2one("check.check", required=True, index=True, ondelete="cascade")
    move_line_id = fields.Many2one(
        "account.move.line", string="Journal Item", required=True, index=True,
        check_company=True, ondelete="restrict",
    )
    move_id = fields.Many2one(related="move_line_id.move_id", store=True, string="Document Entry")
    # Stored plain copy so users without accounting rights can see which document is settled.
    document_name = fields.Char(related="move_line_id.move_id.name", store=True, string="Document")
    date_maturity = fields.Date(related="move_line_id.date_maturity", string="Due Date")
    amount = fields.Monetary(currency_field="currency_id", required=True)
    currency_id = fields.Many2one(related="check_id.currency_id", store=True)
    company_id = fields.Many2one(related="check_id.company_id", store=True, index=True)
    line_residual = fields.Monetary(
        string="Open Amount", currency_field="currency_id", compute="_compute_line_residual",
        compute_sudo=True,
    )
    payment_id = fields.Many2one("account.payment", readonly=True, copy=False)

    @api.depends("move_line_id.amount_residual_currency")
    def _compute_line_residual(self):
        for allocation in self:
            allocation.line_residual = abs(allocation.move_line_id.amount_residual_currency)

    # ------------------------------------------------------------------
    # Constraints (one rule each)
    # ------------------------------------------------------------------
    @api.constrains("move_line_id", "check_id")
    def _check_line_partner(self):
        for allocation in self:
            line_partner = allocation.move_line_id.partner_id.commercial_partner_id
            if line_partner != allocation.check_id.partner_id.commercial_partner_id:
                raise ValidationError(_(
                    "%(document)s belongs to another partner than check %(check)s.",
                    document=allocation.move_id.display_name, check=allocation.check_id.display_name,
                ))

    @api.constrains("move_line_id", "check_id")
    def _check_line_account_type(self):
        for allocation in self:
            expected = ACCOUNT_TYPE_BY_DIRECTION[allocation.check_id.check_type]
            if allocation.move_line_id.account_id.account_type != expected:
                raise ValidationError(_(
                    "Incoming checks allocate to customer receivables and outgoing checks to vendor payables."
                ))

    @api.constrains("move_line_id", "check_id")
    def _check_line_currency(self):
        for allocation in self:
            if allocation.move_line_id.currency_id != allocation.check_id.currency_id:
                raise ValidationError(_(
                    "%(document)s is in %(line_currency)s but the check is in %(check_currency)s.",
                    document=allocation.move_id.display_name,
                    line_currency=allocation.move_line_id.currency_id.name,
                    check_currency=allocation.check_id.currency_id.name,
                ))

    @api.constrains("move_line_id", "amount")
    def _check_line_open_amount(self):
        for allocation in self.filtered(lambda a: a.check_id.state == "draft"):
            line = allocation.move_line_id
            if line.parent_state != "posted" or line.reconciled:
                raise ValidationError(_("%(document)s is not open for allocation.", document=allocation.move_id.display_name))
            if allocation.currency_id.compare_amounts(allocation.amount, allocation.line_residual) > 0:
                raise ValidationError(_(
                    "The allocation on %(document)s exceeds its open amount.",
                    document=allocation.move_id.display_name,
                ))

    @api.constrains("amount", "check_id")
    def _check_check_total(self):
        for check in self.check_id:
            if check.currency_id.compare_amounts(sum(check.allocation_ids.mapped("amount")), check.amount) > 0:
                raise ValidationError(_(
                    "Allocations on check %(check)s exceed the check amount.", check=check.display_name,
                ))

    @api.constrains("check_id")
    def _check_purpose_allows_allocation(self):
        for allocation in self:
            if allocation.check_id.purpose in ("guarantee", "security"):
                raise ValidationError(_("Guarantee and security checks cannot settle invoices or bills."))

    # ------------------------------------------------------------------
    # Editability: allocations are frozen once the check leaves Draft
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        allocations = super().create(vals_list)
        allocations._guard_check_editable()
        return allocations

    def write(self, vals):
        self._guard_check_editable()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_on_draft_checks(self):
        self._guard_check_editable()

    def _guard_check_editable(self):
        if self.env.context.get(CTX_ALLOCATION_SYSTEM_WRITE):
            return
        if self.check_id.filtered(lambda check: check.state != "draft"):
            raise UserError(_("Allocations can only change while the check is in Draft."))
