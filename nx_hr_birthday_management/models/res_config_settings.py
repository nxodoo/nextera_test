from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    birthday_management_enabled = fields.Boolean(
        related='company_id.birthday_management_enabled',
        readonly=False,
    )
    birthday_reminder_manager_id = fields.Many2one(
        related='company_id.birthday_reminder_manager_id',
        readonly=False,
    )
    send_monthly_birthday_reminder = fields.Boolean(
        related='company_id.send_monthly_birthday_reminder',
        readonly=False,
    )
    send_automatic_birthday_greeting = fields.Boolean(
        related='company_id.send_automatic_birthday_greeting',
        readonly=False,
    )
    birthday_greeting_template_id = fields.Many2one(
        related='company_id.birthday_greeting_template_id',
        readonly=False,
    )
