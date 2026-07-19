from odoo import fields, models, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    passport_name_english = fields.Char(string='Passport Name (EN)')
    passport_name_arabic = fields.Char(string='Passport Name (AR)')
    religion = fields.Char(string='Religion')
    passport_profession = fields.Char(string='Passport Profession')
    iqama_ids = fields.One2many('hr.iqama', 'employee_id', string='Residencies')
    iqama_count = fields.Integer(string='Residencies Count', compute='_compute_iqama_count')
    residency_approver_ids = fields.Many2many(
        'res.users',
        'hr_employee_residency_approver_rel',
        'employee_id',
        'user_id',
        string='Residency Approvers',
        help='Users who must approve this employee residency and visa requests.',
    )

    def _compute_iqama_count(self):
        for employee in self:
            employee.iqama_count = len(employee.iqama_ids)

    def write(self, vals):
        """Propagate employee profile changes to linked residency requests."""
        result = super().write(vals)
        mirrored_fields = {
            'name',
            'job_title',
            'department_id',
            'company_id',
            'passport_name_english',
            'passport_name_arabic',
            'country_id',
            'religion',
            'birthday',
            'passport_profession',
        }
        if mirrored_fields & set(vals):
            self.mapped('iqama_ids')._sync_employee_profile_from_employee()
        return result

    def action_view_iqamas(self):
        """Open all residency/visa requests linked to the selected employee."""
        self.ensure_one()
        action = self.env.ref('nx_hr_iqama_management.action_hr_iqama_all').read()[0]
        action['name'] = _('Residencies')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action
