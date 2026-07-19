from odoo import fields, models


class HrEmployeeJobHistory(models.Model):
    _name = 'hr.employee.job.history'
    _description = 'Employee Job History'
    _order = 'date_from desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    job_title = fields.Char(string='Job Title', required=True)
    date_from = fields.Date(string='From Date')
    date_to = fields.Date(string='To Date')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    salary = fields.Monetary(string='Salary', currency_field='currency_id')
