from odoo import fields, models


class SlideChannel(models.Model):
    _inherit = "slide.channel"

    nx_allowed_contact_ids = fields.Many2many(
        "res.partner",
        "nx_partner_slide_channel_rel",
        "channel_id",
        "partner_id",
        string="Allowed Contacts",
        help="Contacts explicitly allowed to access this course through the customer portal and eLearning website.",
    )
