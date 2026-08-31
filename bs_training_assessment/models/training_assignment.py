# -*- coding: utf-8 -*-
import werkzeug.urls
from datetime import date
# pyrefly: ignore [missing-import]
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TrainingGoal(models.Model):
    _name = 'training.assignment'
    _description = 'Training Assignment'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    reference_no = fields.Char(
        string='TNA Reference No',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    training_title = fields.Char(string='Training Title', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string='Requested By',
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
    training_year = fields.Selection(
        selection='_get_training_year_selection',
        string='Training Year',
        required=True,
        default=lambda self: self._get_default_training_year(),
    )
    source_type = fields.Selection(
        [
            ('kpi_appraisal', 'KPI Appraisal'),
            ('manager_request', 'Manager Request'),
            ('compliance', 'Compliance'),
        ],
        string='Source Type',
        required=True,
        tracking=True
    )
    requirement_category = fields.Selection(
        [
            ('individual', 'Individual'),
            ('department_wise', 'Department-wise'),
            ('all_employees', 'All Employees'),
        ],
        string='Requirement Category',
        required=True,
        tracking=True
    )
    department_ids = fields.Many2many(
        'hr.department',
        'training_assignment_hr_department_rel',
        'training_assignment_id',
        'department_id',
        string='Department(s)',
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        'training_assignment_hr_employee_rel',
        'training_assignment_id',
        'employee_id',
        string='Employee(s)',
    )
    reason_for_need = fields.Html(string='Reason for Need', required=True)
    proposed_priority = fields.Selection(
        [
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low'),
        ],
        string='Proposed Priority',
        required=True,
        default='low',
    )
    training_attendance_ids = fields.One2many(
        'training.attendance',
        'training_assignment_id',
        string='Training Attendance',
    )
    training_plan_id = fields.Many2one(
        'training.plan',
        string='Training Plan',
        copy=False,
        ondelete='set null',
    )
    stage_id = fields.Many2one(
        'training.assignment.stage',
        string='Stage',
        default=lambda self: self._get_stage_by_code('draft'),
        group_expand='_read_group_stage_ids',
        required=True,
        ondelete='restrict',
        tracking=True
    )
    stage_code = fields.Char(
        related='stage_id.code',
        string='Stage Code',
        store=True,
        readonly=True,
    )
    venue = fields.Many2one('hr.work.location', domain="[('company_id', '=', company_id)]", string='Venue')
    trainer_type = fields.Selection(
        [
            ('internal', 'Internal'),
            ('external', 'External'),
        ],
        default='internal',
        required=True,
        string='Trainer Type',
    )
    internal_trainer = fields.Many2many(
        'hr.employee',
        'training_assignment_internal_trainer_rel',
        'training_assignment_id',
        'employee_id',
        string='Internal Trainer',
    )
    external_trainer = fields.Many2many(
        'res.partner',
        'training_assignment_external_trainer_rel',
        'training_assignment_id',
        'partner_id',
        string='External Trainer',
    )
    start_date = fields.Date(string='Start Date', tracking=True)
    end_date = fields.Date(string='End Date', tracking=True)
    budget = fields.Float(string='Budget', tracking=True)
    survey_id = fields.Many2one('survey.survey', string='Survey')
    duration = fields.Float(string='Duration (Hours)', tracking=True)
    employee_count = fields.Integer(
        string='Employee Count',
        compute='_compute_employee_count',
        store=True,
    )
    manhour = fields.Integer(
        string='Manhour',
        compute='_compute_manhour',
        store=True,
    )
    approver_id = fields.Many2one('hr.employee', string='Approved By', tracking=True)

    @api.constrains('reference_no')
    def _check_reference_no_unique(self):
        for record in self:
            if record.reference_no and record.reference_no != 'New':
                duplicate = self.search([
                    ('reference_no', '=', record.reference_no),
                    ('id', '!=', record.id),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_('TNA Reference No must be unique.'))

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.start_date and record.end_date and record.start_date > record.end_date:
                raise ValidationError(_('The Start Date must be before or equal to the End Date.'))

    @api.model
    def _get_training_year_selection(self):
        current_year = date.today().year - 2
        return [
            (f'{year}-{year + 1}', f'{year}-{year + 1}')
            for year in range(current_year, current_year + 8)
        ]

    @api.model
    def _get_default_training_year(self):
        today = date.today()
        start_year = today.year if today.month >= 1 else today.year - 1
        return f'{start_year}-{start_year + 1}'

    @api.depends('reference_no', 'training_title')
    def _compute_name(self):
        for record in self:
            parts = [part for part in [record.reference_no, record.training_title] if part and part != 'New']
            record.name = ' - '.join(parts) if parts else record.reference_no or record.training_title or '/'

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env['training.assignment.stage'].search([], order='sequence, id')

    @api.model
    def _get_stage_by_code(self, code):
        return self.env['training.assignment.stage'].search([('code', '=', code)], limit=1)

    def _set_stage_by_code(self, code):
        stage = self._get_stage_by_code(code)
        if not stage:
            raise UserError(_('Training Assignment stage "%s" is not configured.') % code)
        self.write({'stage_id': stage.id})

    def _get_scheduled_stage(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.end_date and self.end_date < today:
            return self._get_stage_by_code('completed')
        if self.start_date and self.start_date <= today:
            return self._get_stage_by_code('ongoing')
        return self._get_stage_by_code('approve')

    def _sync_schedule_state(self):
        for record in self:
            if record.stage_code in ('approve', 'ongoing', 'completed'):
                scheduled_stage = record._get_scheduled_stage()
                if scheduled_stage and record.stage_id.id != scheduled_stage.id:
                    super(TrainingGoal, record).write({'stage_id': scheduled_stage.id})

    @api.model
    def _cron_sync_schedule_state(self):
        records = self.search([('stage_code', 'in', ['approve', 'ongoing', 'completed'])])
        records._sync_schedule_state()

    def _get_target_employees(self):
        self.ensure_one()
        Employee = self.env['hr.employee']
        if self.requirement_category == 'all_employees':
            return Employee.search([])
        if self.requirement_category == 'department_wise':
            return Employee.search([('department_id', 'in', self.department_ids.ids)]) if self.department_ids else Employee
        return self.employee_ids

    @api.onchange('requirement_category')
    def _onchange_requirement_category(self):
        self.employee_ids = False
        self.department_ids = False

    @api.onchange('department_ids')
    def _onchange_department_ids(self):
        if self.requirement_category == 'department_wise':
            employees = self.env['hr.employee'].search([('department_id', 'in', self.department_ids.ids)])
            self.employee_ids = [(6, 0, employees.ids)]

    @api.depends('requirement_category', 'employee_ids', 'department_ids')
    def _compute_employee_count(self):
        for record in self:
            record.employee_count = len(record._get_target_employees())

    @api.depends('duration', 'employee_count')
    def _compute_manhour(self):
        for record in self:
            record.manhour = record.employee_count * record.duration

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference_no') or vals['reference_no'] == 'New':
                vals['reference_no'] = self.env['ir.sequence'].next_by_code('training.assignment') or 'New'
            if not vals.get('stage_id'):
                vals['stage_id'] = self._get_stage_by_code('draft').id
            employee = self.env['hr.employee'].browse(vals['employee_id']) if vals.get('employee_id') else self.env.user.employee_id
            if employee:
                vals['employee_id'] = employee.id
                vals['company_id'] = employee.company_id.id if employee.company_id else self.env.company.id
            else:
                vals['company_id'] = vals.get('company_id') or self.env.company.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('employee_id'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['company_id'] = employee.company_id.id if employee.company_id else self.env.company.id
        result = super().write(vals)
        if any(field in vals for field in ('start_date', 'end_date')):
            self._sync_schedule_state()
        return result

    def action_set_draft(self):
        draft_stage = self._get_stage_by_code('draft')
        self.write({'stage_id': draft_stage.id})

    def action_submit(self):
        for record in self:
            if record.stage_code != 'draft':
                continue
            if not record.employee_id:
                raise UserError(_('The current user must be linked to an employee before submitting a training goal.'))
            if record.requirement_category == 'department_wise' and not record.department_ids:
                raise UserError(_('Please select at least one department for a department-wise training assignment.'))

            target_employees = record._get_target_employees()
            if not target_employees:
                raise UserError(_('Please select at least one employee before submitting.'))

            record.write({'stage_id': self._get_stage_by_code('submit').id})
            record._notify_approver()

    def action_approve(self):
        for record in self:
            if record.stage_code != 'submit':
                continue
            if self.env.user.employee_id.id != record.approver_id.id:
                raise UserError(_('Only the assigned approver can approve this training assignment.'))
            scheduled_stage = record._get_scheduled_stage()
            record.write({'stage_id': scheduled_stage.id})
            record._notify_trainees()

    def _notify_trainees(self):
        template = self.env.ref(
            'bs_training_assessment.mail_template_training_approved',
            raise_if_not_found=False,
        )
        if not template:
            return
        Mail = self.env['mail.mail'].sudo()
        for record in self:
            employees = record._get_target_employees().filtered(lambda emp: emp.work_email)
            if not employees:
                continue

            schedule_text = '-'
            if record.start_date and record.end_date:
                schedule_text = _('%s to %s') % (record.start_date, record.end_date)
            elif record.start_date:
                schedule_text = str(record.start_date)
            elif record.end_date:
                schedule_text = str(record.end_date)

            subject = template._render_field('subject', record.ids)[record.id]
            for employee in employees:
                body = template.with_context(
                    employee_name=employee.name or '',
                    schedule=schedule_text,
                )._render_field('body_html', record.ids)[record.id]
                Mail.create({
                    'subject': subject,
                    'body_html': body,
                    'email_to': employee.work_email,
                }).send()

    def _notify_approver(self):
        self.ensure_one()
        if not self.approver_id or not self.approver_id.work_email:
            return
        template = self.env.ref(
            'bs_training_assessment.mail_template_training_pending_approval',
            raise_if_not_found=False,
        )
        if not template:
            return
        template.send_mail(self.id, force_send=True)

    def action_send_survey_mail(self):
        self.ensure_one()
        if not self.survey_id:
            raise UserError(_('Survey Empty'))

        employees = self._get_target_employees().filtered(lambda e: e.work_email)
        if not employees:
            raise UserError(_('No employees with email addresses found.'))

        template = self.env.ref(
            'bs_training_assessment.mail_template_training_survey',
            raise_if_not_found=False,
        )
        if not template:
            raise UserError(_('Survey email template not found.'))

        survey_link = werkzeug.urls.url_join(
            self.survey_id.get_base_url(), self.survey_id.get_start_url()
        )
        subject = template._render_field('subject', self.ids)[self.id]
        Mail = self.env['mail.mail'].sudo()
        for employee in employees:
            body = template.with_context(
                employee_name=employee.name or '',
                survey_link=survey_link,
            )._render_field('body_html', self.ids)[self.id]
            Mail.create({
                'subject': subject,
                'body_html': body,
                'email_to': employee.work_email,
            }).send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Mail Sent'),
                'message': _('Survey mail sent to %s participant(s).') % len(employees),
                'sticky': False,
            },
        }

    def action_close(self):
        for record in self:
            if record.stage_code != 'completed':
                raise UserError(_('Training assignments can only be closed from the Completed stage.'))
        self.write({'stage_id': self._get_stage_by_code('closed').id})
