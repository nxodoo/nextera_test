from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    job_history_ids = fields.One2many(
        'hr.employee.job.history',
        'employee_id',
        string='Job History',
    )
    education_ids = fields.One2many(
        'hr.employee.education',
        'employee_id',
        string='Education',
    )
    previous_job_ids = fields.One2many(
        'hr.employee.previous.job',
        'employee_id',
        string='Previous Work Experience',
    )
