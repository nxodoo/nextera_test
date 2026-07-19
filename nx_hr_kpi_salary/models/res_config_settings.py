from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    auto_generate_kpi_evaluations = fields.Boolean(
        related="company_id.auto_generate_kpi_evaluations",
        readonly=False,
    )
