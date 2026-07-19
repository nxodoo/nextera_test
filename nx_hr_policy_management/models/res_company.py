from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    leave_allowance_scheduler_enabled = fields.Boolean(
        string="Leave Allowance Scheduler Enabled",
        default=False,
    )
    leave_allowance_scheduler_start_date = fields.Date(
        string="Leave Allowance Scheduler Start Date",
    )
    holiday_greeting_scheduler_enabled = fields.Boolean(
        string="Holiday Greeting Scheduler Enabled",
        default=False,
    )
