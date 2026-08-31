# -*- coding: utf-8 -*-

from odoo import models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # NOTE: Previously had a global display_name override here.
    # This was removed because it affected ALL employee displays system-wide,
    # breaking other modules, reports, and views.
    # If custom employee display formatting is needed, use computed fields
    # on specific models (e.g., training.assignment) instead.
