# -*- coding: utf-8 -*-

from odoo import _, api, fields, models


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
            employee.department_id = employee.job_id.department_id

    @api.model_create_multi
    def create(self, vals_list):
        """Keep employee department aligned with the selected job position."""
        job_ids = {vals['job_id'] for vals in vals_list if vals.get('job_id')}
        jobs_by_id = {
            job.id: job
            for job in self.env['hr.job'].browse(job_ids)
        }
        for vals in vals_list:
            if 'job_id' in vals:
                job = jobs_by_id.get(vals.get('job_id'))
                vals['department_id'] = job.department_id.id if job else False
            elif 'department_id' in vals and not self.env.context.get('nx_sync_department_from_job'):
                vals['department_id'] = False
        return super().create(vals_list)

    def write(self, vals):
        """Keep employee department aligned when the job position changes."""
        if 'job_id' in vals:
            job = self.env['hr.job'].browse(vals['job_id']) if vals['job_id'] else False
            vals = dict(vals, department_id=job.department_id.id if job else False)
        elif 'department_id' in vals and not self.env.context.get('nx_sync_department_from_job'):
            vals = dict(vals)
            vals.pop('department_id')
        return super().write(vals)

    def action_open_position_org_chart(self):
        """Open the custom position-based org chart from an employee record.

        Returns:
            dict: Odoo client action rooted at the employee's job position when available.
        """
        self.ensure_one()
        params = {}
        if self.job_id:
            params['root_job_id'] = self.job_id.id
            params['title'] = self.job_id.name
        return {
            'type': 'ir.actions.client',
            'tag': 'nx_position_org_chart',
            'name': _('Org Chart'),
            'params': params,
        }
