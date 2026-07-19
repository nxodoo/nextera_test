# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """
    Extends Payroll configuration settings to add the
    'Minimum Timesheet Hours' threshold used by the 'Both' work entry source.

    HR Managers can adjust this value from:
    Payroll → Configuration → Settings → Work Entry
    """

    _inherit = 'res.config.settings'

    minimum_timesheet_hours = fields.Float(
        string='Minimum Timesheet Hours',
        help=(
            'Minimum daily timesheet hours required to count a day as a full '
            'working day when the contract Work Entry Source is set to "Both". '
            'If the employee logs fewer hours than this threshold, only the '
            'actual hours are counted instead of a full day.'
        ),
        config_parameter='nx_payroll_both_work_entry.minimum_timesheet_hours',
        default=8.0,
    )
