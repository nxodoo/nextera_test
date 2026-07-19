from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    leave_allowance_scheduler_enabled = fields.Boolean(
        related="company_id.leave_allowance_scheduler_enabled",
        readonly=False,
    )
    leave_allowance_scheduler_start_date = fields.Date(
        related="company_id.leave_allowance_scheduler_start_date",
        readonly=False,
    )
    holiday_greeting_scheduler_enabled = fields.Boolean(
        related="company_id.holiday_greeting_scheduler_enabled",
        readonly=False,
    )
