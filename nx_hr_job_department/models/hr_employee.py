# -*- coding: utf-8 -*-
from odoo import api, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # The Job Position now drives the Department instead of restricting the
    # job list. All job positions stay selectable, and picking one fills in
    # its department automatically.
    @api.onchange('job_id')
    def _onchange_job_id_set_department(self):
        """Auto-fill the department from the selected job position."""
        for employee in self:
            if employee.job_id and employee.job_id.department_id:
                employee.department_id = employee.job_id.department_id
