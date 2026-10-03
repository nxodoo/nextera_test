from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    check_sale_bounce_policy = fields.Selection(related="company_id.check_sale_bounce_policy", readonly=False)
    check_sale_credit_include_checks = fields.Boolean(
        related="company_id.check_sale_credit_include_checks", readonly=False,
    )
