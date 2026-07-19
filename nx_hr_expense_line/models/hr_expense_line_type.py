from odoo import fields, models


class HrExpenseLineType(models.Model):
    _name = "hr.expense.line.type"
    _description = "Expense Line Type"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    account_id = fields.Many2one(
        "account.account",
        string="Financial Account",
        required=True,
        domain="[('deprecated', '=', False), ('account_type', 'not in', ('asset_receivable', 'liability_payable', 'asset_cash', 'liability_credit_card'))]",
        check_company=True,
    )
    max_amount = fields.Monetary(
        string="Maximum Amount",
        currency_field="company_currency_id",
        help="Optional maximum amount allowed for a single expense line.",
    )
    active = fields.Boolean(default=True)
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    company_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
