from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    birthday_management_enabled = fields.Boolean(
        string='Enable Birthday Management',
        help='Enable monthly birthday reminders and automatic greeting emails.',
    )
    birthday_reminder_manager_id = fields.Many2one(
        'res.users',
        string='Birthday Reminder Manager',
        domain="[('share', '=', False)]",
        help='HR responsible user who receives birthday reminders and missing email activities.',
    )
    send_monthly_birthday_reminder = fields.Boolean(
        string='Send Monthly Birthday Reminder',
        help='Send an internal monthly reminder that lists employee birthdays for the current month.',
    )
    send_automatic_birthday_greeting = fields.Boolean(
        string='Send Automatic Birthday Greeting to Employees',
        help='Send the configured birthday greeting email automatically on the employee birthday.',
    )
    birthday_greeting_template_id = fields.Many2one(
        'mail.template',
        string='Birthday Greeting Email Template',
        help='Template used for automatic birthday greeting emails.',
    )
    birthday_last_reminder_date = fields.Date(
        string='Last Birthday Reminder Date',
        copy=False,
        help='Technical field used to avoid sending the same monthly reminder multiple times.',
    )
