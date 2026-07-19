from odoo import fields, models


class MailTrackingValue(models.Model):
    _inherit = "mail.tracking.value"

    changed_on = fields.Datetime(
        related="mail_message_id.date",
        string="Changed On",
        readonly=True,
    )
    changed_by_id = fields.Many2one(
        "res.partner",
        related="mail_message_id.author_id",
        string="Changed By",
        readonly=True,
    )
