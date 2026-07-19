# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    job_id = fields.Many2one(
        domain="['&', ('recruitment_state', 'in', ('open', 'active')),"
               " '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        context={'nx_forbid_job_creation': True},
    )
    application_deadline = fields.Date(
        related='job_id.application_deadline',
        string='Application Deadline',
        store=True,
        readonly=True,
    )
    recruitment_state = fields.Selection(
        related='job_id.recruitment_state',
        string='Recruitment Status',
        store=True,
        readonly=True,
    )

    @api.constrains('job_id', 'create_date')
    def _check_job_accepts_applications(self):
        today = fields.Date.context_today(self)
        for applicant in self.filtered('job_id'):
            job = applicant.job_id
            if job.recruitment_state == 'expired' or (
                job.application_deadline and job.application_deadline < today
            ):
                raise ValidationError(_(
                    'The application deadline for this job position has expired.'
                ))
            if job.recruitment_state not in ('open', 'active'):
                raise ValidationError(_(
                    'Applications can only be created for open or active job positions.'
                ))

    @api.model_create_multi
    def create(self, vals_list):
        applicants = super().create(vals_list)
        applicants._check_job_accepts_applications()
        return applicants

    def write(self, vals):
        result = super().write(vals)
        if 'job_id' in vals:
            self._check_job_accepts_applications()
        return result
