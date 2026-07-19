from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    auto_deduct_unpaid_expenses = fields.Boolean(
        related="company_id.auto_deduct_unpaid_expenses",
        readonly=False,
    )
    expense_deduction_product_ids = fields.Many2many(
        related="company_id.expense_deduction_product_ids",
        readonly=False,
    )
    deduct_only_company_expenses = fields.Boolean(
        related="company_id.deduct_only_company_expenses",
        readonly=False,
    )
