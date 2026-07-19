# -*- coding: utf-8 -*-
from odoo import models, fields


class Website(models.Model):
    _inherit = 'website'

    # Extend the selection defined in portal_my_tabs with the ESS mode.
    portal_mode = fields.Selection(
        selection_add=[('ess', 'Employee Self-Service')],
        ondelete={'ess': 'set default'},
    )
