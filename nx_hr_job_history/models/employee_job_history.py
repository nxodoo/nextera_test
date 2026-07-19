# -*- coding: utf-8 -*-
from odoo import models, fields, api


class EmployeeJobHistory(models.Model):
    _name = 'employee.job.history'
    _description = 'Employee Job History'
    _order = 'date_from desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        ondelete='cascade',
        required=True
    )

    job_title = fields.Char(string='Job Title', required=True)

    date_from = fields.Date(string='From Date', required=True)
    date_to = fields.Date(string='To Date')

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id
    )

    salary = fields.Monetary(
        string='Salary',
        currency_field='currency_id',
        required=True
    )
