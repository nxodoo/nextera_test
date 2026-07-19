# models/website.py

from odoo import models, fields

class Website(models.Model):
    _inherit = 'website'

    portal_mode = fields.Selection([
        ('default', 'Default'),
        ('warranty', 'Warranty SLA'),
        ('activity', 'Activity Portal'),
    ], default='default')




class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    portal_mode = fields.Selection(
        related='website_id.portal_mode',
        readonly=False
    )