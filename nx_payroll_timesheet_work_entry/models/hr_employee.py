# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    """
    Store the attendance-via-timesheet policy on the employee so it can be
    maintained from both Employee and Contract screens.
    """

    _inherit = 'hr.employee'

    attendance_based_on_timesheet = fields.Boolean(
        string='Attendance Based on Timesheet',
        help=(
            'Enable automatic Internal Project timesheets for approved leave '
            'and public holidays.'
        ),
    )
