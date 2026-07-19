# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    job_history_ids = fields.One2many(
        'employee.job.history',
        'employee_id',
        string='Job History'
    )
