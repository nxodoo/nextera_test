# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TrainingPlan(models.Model):
    _name = 'training.plan'
    _description = 'Training Plan'
    _rec_name = 'serial_no'
    _order = 'start_date desc, id desc'

    serial_no = fields.Char(
        string='Serial No',
        readonly=True,
        copy=False,
        default='New',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Prepared By',
        default=lambda self: self.env.user.employee_id,
        readonly=True,
        copy=False,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    training_assignment_ids = fields.One2many(
        'training.assignment',
        'training_plan_id',
        string='Training Assignments',
    )
    assignment_count = fields.Integer(
        string='Training Count',
        compute='_compute_plan_totals',
    )
    total_participants = fields.Integer(
        string='Total Participants',
        compute='_compute_plan_totals',
    )
    total_duration = fields.Integer(
        string='Total Duration (Hours)',
        compute='_compute_plan_totals',
    )
    total_manhour = fields.Integer(
        string='Total Manhour',
        compute='_compute_plan_totals',
    )
    total_budget = fields.Float(
        string='Total Budget',
        compute='_compute_plan_totals',
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submit', 'Submitted'),
            ('approved', 'Approved'),
            ('ongoing', 'Ongoing'),
            ('completed', 'Completed'),
            ('rejected', 'Rejected'),
        ],
        string='Status',
        default='draft',
        required=True,
    )
    _sql_constraints = [
        (
            'training_plan_date_range_check',
            'CHECK(start_date <= end_date)',
            'End date must be greater than or equal to start date.',
        ),
    ]

    def _get_matching_training_assignments(self):
        self.ensure_one()
        if not self.start_date or not self.end_date:
            return self.env['training.assignment']
        domain = [
            ('company_id', '=', self.company_id.id),
            ('stage_code', 'in', ['approve', 'ongoing', 'completed', 'closed']),
            ('start_date', '<=', self.end_date),
            ('end_date', '>=', self.start_date),
        ]
        return self.env['training.assignment'].search(domain, order='start_date, id')

    def _sync_training_assignment_ids(self):
        for record in self:
            matching_assignments = record._get_matching_training_assignments()
            record.training_assignment_ids = [(6, 0, matching_assignments.ids)]

    @api.onchange('start_date', 'end_date', 'company_id')
    def _onchange_training_assignment_domain_fields(self):
        self.training_assignment_ids = [(6, 0, self._get_matching_training_assignments().ids)]

    @api.depends(
        'training_assignment_ids',
        'training_assignment_ids.employee_count',
        'training_assignment_ids.duration',
        'training_assignment_ids.manhour',
        'training_assignment_ids.budget',
    )
    def _compute_plan_totals(self):
        for record in self:
            record.assignment_count = len(record.training_assignment_ids)
            record.total_participants = sum(record.training_assignment_ids.mapped('employee_count'))
            record.total_duration = sum(record.training_assignment_ids.mapped('duration'))
            record.total_manhour = sum(record.training_assignment_ids.mapped('manhour'))
            record.total_budget = sum(record.training_assignment_ids.mapped('budget'))

    def _get_scheduled_state(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.end_date and self.end_date < today:
            return 'completed'
        if self.start_date and self.start_date <= today:
            return 'ongoing'
        return 'approved'

    def _sync_schedule_state(self):
        for record in self:
            if record.state in ('approved', 'ongoing', 'completed'):
                scheduled_state = record._get_scheduled_state()
                if record.state != scheduled_state:
                    super(TrainingPlan, record).write({'state': scheduled_state})

    @api.model
    def _cron_sync_schedule_state(self):
        records = self.search([('state', 'in', ['approved', 'ongoing', 'completed'])])
        records._sync_schedule_state()

    @api.model_create_multi
    def create(self, vals_list):
        sync_records = self.env[self._name]
        for vals in vals_list:
            if not vals.get('serial_no') or vals['serial_no'] == 'New':
                vals['serial_no'] = self.env['ir.sequence'].next_by_code('training.plan') or 'New'
            employee = self.env['hr.employee'].browse(vals['employee_id']) if vals.get('employee_id') else self.env.user.employee_id
            if employee:
                vals['employee_id'] = employee.id
                vals['company_id'] = employee.company_id.id if employee.company_id else self.env.company.id
            else:
                vals['company_id'] = vals.get('company_id') or self.env.company.id
        records = super().create(vals_list)
        for record, vals in zip(records, vals_list):
            if not vals.get('training_assignment_ids'):
                sync_records |= record
        sync_records._sync_training_assignment_ids()
        records._sync_schedule_state()
        return records

    def write(self, vals):
        should_sync_assignments = any(field_name in vals for field_name in ('start_date', 'end_date', 'company_id'))
        if vals.get('employee_id'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['company_id'] = employee.company_id.id if employee.company_id else self.env.company.id
            should_sync_assignments = True
        result = super().write(vals)
        if should_sync_assignments:
            self._sync_training_assignment_ids()
        if any(field in vals for field in ('start_date', 'end_date')):
            self._sync_schedule_state()
        return result

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                continue
            if not record.employee_id:
                raise UserError(_('The current user must be linked to an employee before submitting a training plan.'))
            if not record.start_date or not record.end_date:
                raise UserError(_('Please set both start date and end date.'))
            if record.end_date < record.start_date:
                raise UserError(_('End date must be greater than or equal to start date.'))
            if not record.training_assignment_ids:
                raise UserError(_('No training assignments were found in the selected date range.'))

            record.write({'state': record._get_scheduled_state()})
