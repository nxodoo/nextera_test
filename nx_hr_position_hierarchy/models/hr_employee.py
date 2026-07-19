# -*- coding: utf-8 -*-

from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    job_id = fields.Many2one(
        domain="['&', '|', ('department_id', '=', False), ('department_id', '=', department_id),"
               " '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        context={'nx_forbid_job_creation': True},
    )

    @api.onchange('job_id')
    def _onchange_job_id_sync_department(self):
        for employee in self:
            if employee.job_id.department_id:
                employee.department_id = employee.job_id.department_id
