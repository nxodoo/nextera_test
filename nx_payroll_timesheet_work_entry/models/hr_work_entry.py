# -*- coding: utf-8 -*-
from odoo import fields, models


class HrWorkEntry(models.Model):
    _inherit = 'hr.work.entry'

    timesheet_generated = fields.Boolean(
        string='From Timesheet Source',
        default=False,
        help='Set when the entry was generated from the Timesheet work entry source.',
    )
