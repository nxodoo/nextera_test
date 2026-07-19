from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    payroll_expense_allowance_input_type_id = fields.Many2one(
        related="company_id.payroll_expense_allowance_input_type_id",
        readonly=False,
    )
