from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hr_iqama_notification_days_before_expiry = fields.Integer(
        string='Days Before Expiry Notification',
        config_parameter='hr_iqama.notification_days_before_expiry',
        default=30,
        help='Number of days before the iqama expiry date when reminder emails and activities should be created.',
    )
