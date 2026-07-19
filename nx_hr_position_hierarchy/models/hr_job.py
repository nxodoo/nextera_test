# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


POSITION_LEVELS = [
    ('1', 'Level 1 - CEO'),
    ('2', 'Level 2 - Director'),
    ('3', 'Level 3 - Department Manager'),
    ('4', 'Level 4 - Team Leader'),
    ('5', 'Level 5 - Senior Employee'),
    ('6', 'Level 6 - Employee'),
]

RECRUITMENT_STATES = [
    ('draft', 'Draft'),
    ('open', 'Open'),
    ('active', 'Active'),
    ('expired', 'Expired'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]


class HrJob(models.Model):
    _inherit = 'hr.job'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'position_level_sequence, sequence, name'

    parent_id = fields.Many2one(
        'hr.job',
        string='Parent Position',
        index=True,
        ondelete='restrict',
        domain="[('id', '!=', id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        tracking=True,
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many('hr.job', 'parent_id', string='Direct Sub Positions')
    child_count = fields.Integer(string='Direct Sub Positions', compute='_compute_position_counts')
    child_all_count = fields.Integer(string='Total Sub Positions', compute='_compute_position_counts')
    is_assistant_position = fields.Boolean(
        string='Assistant Position',
        help='Show this position as an assistant branch under its parent in the position org chart.',
        tracking=True,
    )
    position_level = fields.Selection(
        POSITION_LEVELS,
        string='Position Level',
        required=True,
        default='6',
        tracking=True,
    )
    position_level_id = fields.Many2one(
        'hr.position.level',
        string='Position Level',
        default=lambda self: self._default_position_level_id(),
        required=True,
        tracking=True,
        index=True,
    )
    position_level_sequence = fields.Integer(
        related='position_level_id.sequence',
        store=True,
        index=True,
    )
    headcount = fields.Integer(string='Headcount', default=1, tracking=True)
    position_status = fields.Selection(
        [('filled', 'Filled'), ('vacant', 'Vacant')],
        string='Position Status',
        compute='_compute_position_status',
        store=True,
        readonly=False,
        tracking=True,
    )
    assigned_employee_ids = fields.One2many(
        'hr.employee',
        'job_id',
        string='Assigned Employees',
        domain=[('active', '=', True)],
    )
    assigned_employee_count = fields.Integer(
        string='Assigned Employees',
        compute='_compute_position_status',
        store=True,
    )
    vacancy_count = fields.Integer(
        string='Vacancies',
        compute='_compute_position_status',
        store=True,
    )
    application_deadline = fields.Date(string='Application Deadline', tracking=True)
    recruitment_state = fields.Selection(
        RECRUITMENT_STATES,
        string='Recruitment Status',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    days_to_deadline = fields.Integer(
        string='Days to Deadline',
        compute='_compute_days_to_deadline',
        search='_search_days_to_deadline',
    )
    time_to_fill = fields.Integer(
        string='Time to Fill Position',
        compute='_compute_time_to_fill',
        help='Days between opening the job posting and the first hire date.',
    )

    _sql_constraints = [
        (
            'headcount_non_negative',
            'CHECK(headcount >= 0)',
            'Headcount must be zero or greater.',
        ),
    ]

    @api.model
    def _default_position_level_id(self):
        return self.env.ref(
            'nx_hr_position_hierarchy.position_level_employee',
            raise_if_not_found=False,
        )

    @api.model
    def _assistant_position_level_id(self):
        return self.env.ref(
            'nx_hr_position_hierarchy.position_level_assistant',
            raise_if_not_found=False,
        )

    @api.model
    def _sync_missing_position_levels(self):
        """Map legacy selection levels without invalidating existing hierarchies."""
        level_by_legacy_value = {
            '1': self.env.ref('nx_hr_position_hierarchy.position_level_ceo', raise_if_not_found=False),
            '2': self.env.ref('nx_hr_position_hierarchy.position_level_director', raise_if_not_found=False),
            '3': self.env.ref('nx_hr_position_hierarchy.position_level_department_manager', raise_if_not_found=False),
            '4': self.env.ref('nx_hr_position_hierarchy.position_level_team_leader', raise_if_not_found=False),
            '5': self.env.ref('nx_hr_position_hierarchy.position_level_senior_employee', raise_if_not_found=False),
            '6': self.env.ref('nx_hr_position_hierarchy.position_level_employee', raise_if_not_found=False),
        }
        assistant_level = self._assistant_position_level_id()
        jobs = self.with_context(active_test=False).search([]).sorted(
            key=lambda job: (job.parent_path or '').count('/')
        )
        for job in jobs:
            target_level = assistant_level if job.is_assistant_position else level_by_legacy_value.get(job.position_level)
            if not target_level or job.position_level_id == target_level:
                continue

            parent = job.parent_id
            parent_level = parent.position_level_id
            if (
                parent_level
                and not job.is_assistant_position
                and parent_level.sequence >= target_level.sequence
            ):
                _logger.warning(
                    "Skipped position-level synchronization for job %s because parent %s "
                    "does not have a higher level.",
                    job.display_name,
                    parent.display_name,
                )
                continue
            job.with_context(tracking_disable=True).position_level_id = target_level

    @api.depends('child_ids', 'child_ids.child_ids')
    def _compute_position_counts(self):
        child_count_data = self.env['hr.job']._read_group(
            [('parent_id', 'in', self.ids)],
            ['parent_id'],
            ['__count'],
        )
        child_count_by_parent = {parent.id: count for parent, count in child_count_data}

        descendants = self.env['hr.job'].search([('id', 'child_of', self.ids)])
        descendant_count_by_parent = dict.fromkeys(self.ids, 0)
        for descendant in descendants:
            ancestor_ids = [
                int(position_id)
                for position_id in (descendant.parent_path or '').split('/')[:-1]
                if position_id
            ]
            for ancestor_id in ancestor_ids:
                if ancestor_id in descendant_count_by_parent and ancestor_id != descendant.id:
                    descendant_count_by_parent[ancestor_id] += 1

        for job in self:
            job.child_count = child_count_by_parent.get(job.id, 0)
            job.child_all_count = descendant_count_by_parent.get(job.id, 0)

    @api.depends('employee_ids.active', 'employee_ids.job_id', 'headcount')
    def _compute_position_status(self):
        grouped = self.env['hr.employee']._read_group(
            [('job_id', 'in', self.ids), ('active', '=', True)],
            ['job_id'],
            ['__count'],
        )
        assigned_by_job = {job.id: count for job, count in grouped}
        for job in self:
            assigned_count = assigned_by_job.get(job.id, 0)
            job.assigned_employee_count = assigned_count
            job.vacancy_count = max(job.headcount - assigned_count, 0)
            job.position_status = 'filled' if job.headcount and assigned_count >= job.headcount else 'vacant'

    @api.depends('application_deadline')
    def _compute_days_to_deadline(self):
        today = fields.Date.context_today(self)
        for job in self:
            job.days_to_deadline = (job.application_deadline - today).days if job.application_deadline else 0

    def _search_days_to_deadline(self, operator, value):
        if operator not in ('<', '<=', '=', '!=', '>=', '>'):
            raise UserError(_('Operation not supported for Days to Deadline.'))
        today = fields.Date.context_today(self)
        deadline = fields.Date.add(today, days=value)
        return [('application_deadline', operator, deadline)]

    @api.depends('create_date', 'application_ids.date_closed')
    def _compute_time_to_fill(self):
        for job in self:
            hire_dates = job.application_ids.filtered('date_closed').mapped('date_closed')
            if not hire_dates or not job.create_date:
                job.time_to_fill = 0
                continue
            job.time_to_fill = (min(hire_dates).date() - job.create_date.date()).days

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_('A job position cannot be a parent of itself.'))

    @api.constrains('parent_id', 'position_level_id', 'is_assistant_position')
    def _check_parent_position_level(self):
        for job in self.filtered('parent_id'):
            if job.is_assistant_position:
                continue
            if job.parent_id.position_level_id.sequence >= job.position_level_id.sequence:
                raise ValidationError(_(
                    'The parent position level must be higher than the child position level.'
                ))

    @api.constrains('headcount')
    def _check_headcount(self):
        for job in self:
            if job.headcount < 0:
                raise ValidationError(_('Headcount must be zero or greater.'))

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('nx_forbid_job_creation'):
            raise UserError(_(
                'Job positions must be created from Employees > Configuration > Job Positions.'
            ))
        assistant_level = self._assistant_position_level_id()
        for vals in vals_list:
            if vals.get('is_assistant_position') and assistant_level:
                vals.setdefault('position_level_id', assistant_level.id)
            elif vals.get('position_level_id'):
                level = self.env['hr.position.level'].browse(vals['position_level_id'])
                if level.is_assistant:
                    vals.setdefault('is_assistant_position', True)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('is_assistant_position') and 'position_level_id' not in vals:
            assistant_level = self._assistant_position_level_id()
            if assistant_level:
                vals = dict(vals, position_level_id=assistant_level.id)
        elif vals.get('position_level_id') and 'is_assistant_position' not in vals:
            level = self.env['hr.position.level'].browse(vals['position_level_id'])
            if level.is_assistant:
                vals = dict(vals, is_assistant_position=True)
        result = super().write(vals)
        if 'application_deadline' in vals or 'recruitment_state' in vals:
            self._expire_jobs_after_deadline()
        return result

    @api.onchange('is_assistant_position')
    def _onchange_is_assistant_position(self):
        assistant_level = self._assistant_position_level_id()
        for job in self:
            if job.is_assistant_position and assistant_level:
                job.position_level_id = assistant_level

    @api.onchange('position_level_id')
    def _onchange_position_level_id(self):
        for job in self:
            if job.position_level_id.is_assistant:
                job.is_assistant_position = True

    def action_open_position_org_chart(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'nx_position_org_chart',
            'name': _('Org Chart'),
            'params': {'root_job_id': self.id},
        }

    def action_open(self):
        self.write({'recruitment_state': 'open'})

    def action_activate(self):
        self.write({'recruitment_state': 'active'})

    def action_close(self):
        self.write({'recruitment_state': 'closed'})

    def action_cancel(self):
        self.write({'recruitment_state': 'cancelled'})

    def _expire_jobs_after_deadline(self):
        today = fields.Date.context_today(self)
        expired_jobs = self.filtered(
            lambda job: job.application_deadline
            and job.application_deadline < today
            and job.recruitment_state in ('open', 'active')
        )
        if expired_jobs:
            expired_jobs.with_context(tracking_disable=True).write({'recruitment_state': 'expired'})

    @api.model
    def _cron_expire_jobs_after_deadline(self):
        jobs = self.search([
            ('application_deadline', '<', fields.Date.context_today(self)),
            ('recruitment_state', 'in', ('open', 'active')),
        ])
        jobs._expire_jobs_after_deadline()
