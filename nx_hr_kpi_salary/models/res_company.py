from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    auto_generate_kpi_evaluations = fields.Boolean(
        string="Auto Generate KPI Evaluations",
        help="Automatically create draft KPI evaluations for monthly and quarterly periods.",
    )
