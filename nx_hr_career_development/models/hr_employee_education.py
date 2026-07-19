from odoo import fields, models


class HrEmployeeEducation(models.Model):
    _name = 'hr.employee.education'
    _description = 'Employee Education Record'
    _order = 'graduation_year desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    certificate = fields.Selection([
        ('graduate', 'Graduate'),
        ('bachelor', 'Bachelor'),
        ('master', 'Master'),
        ('doctor', 'Doctor'),
        ('other', 'Other'),
    ], string='Certificate Level')
    university = fields.Char(string='University / College')
    department = fields.Char(string='Department')
    study_field = fields.Char(string='Field of Study')
    school = fields.Char(string='School')
    graduation_year = fields.Integer(string='Graduation Year')
    grade = fields.Char(string='Final Grade')
