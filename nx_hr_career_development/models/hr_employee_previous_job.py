from odoo import fields, models


class HrEmployeePreviousJob(models.Model):
    _name = 'hr.employee.previous.job'
    _description = 'Employee Previous Work Experience'
    _order = 'start_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_name = fields.Char(string='Company Name', required=True)
    job_title = fields.Char(string='Job Title')
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    leaving_reason = fields.Char(string='Leaving Reason')
