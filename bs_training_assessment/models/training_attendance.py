# -*- coding: utf-8 -*-

from odoo import api, fields, models


class TrainingAttendance(models.Model):
    _name = 'training.attendance'
    _description = 'Training Attendance'
    _rec_name = 'training_assignment_id'
    _order = 'attendance_date desc, id desc'

    training_assignment_id = fields.Many2one(
        'training.assignment',
        string='Training Assignment',
        required=True,
        domain=[('stage_code', 'in', ['approve', 'ongoing', 'completed'])],
    )
    training_on = fields.Char(
        string='Training On',
        related='training_assignment_id.training_title',
        readonly=True,
    )
    attendance_date = fields.Date(
        string='Attendance Date',
        required=True,
        default=fields.Date.context_today,
    )
    submitted_by = fields.Many2one(
        'res.users',
        string='Submitted By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    duration = fields.Float(string='Duration (Hours)')
    facilitator_id = fields.Many2one(
        'hr.employee',
        string='Facilitator',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='training_assignment_id.company_id',
        readonly=True,
        store=True,
    )
    attendee_line_ids = fields.One2many(
        'training.attendance.line',
        'attendance_id',
        string='Attendance Lines',
    )
    present_count = fields.Integer(
        string='Present',
        compute='_compute_attendance_counts',
        store=True,
    )
    absent_count = fields.Integer(
        string='Absent',
        compute='_compute_attendance_counts',
        store=True,
    )

    @api.depends('attendee_line_ids.is_present')
    def _compute_attendance_counts(self):
        for record in self:
            present_lines = record.attendee_line_ids.filtered('is_present')
            record.present_count = len(present_lines)
            record.absent_count = len(record.attendee_line_ids) - len(present_lines)

    @api.onchange('training_assignment_id')
    def _onchange_training_assignment_id(self):
        if not self.training_assignment_id:
            self.attendee_line_ids = [(5, 0, 0)]
            return
        employees = self.training_assignment_id._get_target_employees()
        self.attendee_line_ids = [
            (5, 0, 0),
            *[
                (0, 0, {
                    'employee_id': employee.id,
                    'is_present': True,
                })
                for employee in employees
            ],
        ]

    def _prepare_attendee_line_commands(self, assignment=None):
        self.ensure_one()
        assignment = assignment or self.training_assignment_id
        employees = assignment._get_target_employees()
        existing_lines_by_employee = {
            line.employee_id.id: line
            for line in self.attendee_line_ids.filtered("employee_id")
        }
        commands = [(5, 0, 0)]
        for employee in employees:
            existing_line = existing_lines_by_employee.get(employee.id)
            commands.append((0, 0, {
                'employee_id': employee.id,
                'is_present': existing_line.is_present if existing_line else True,
                'note': existing_line.note if existing_line else False,
            }))
        return commands

    @api.model
    def _should_rebuild_attendee_lines(self, vals):
        attendee_commands = vals.get('attendee_line_ids')
        if not attendee_commands:
            return True
        for command in attendee_commands:
            if not isinstance(command, (list, tuple)) or not command:
                continue
            if command[0] == 0 and len(command) > 2 and not command[2].get('employee_id'):
                return True
        return False

    @api.model_create_multi
    def create(self, vals_list):
        sanitized_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            assignment_id = vals.get('training_assignment_id')
            if assignment_id and self._should_rebuild_attendee_lines(vals):
                assignment = self.env['training.assignment'].browse(assignment_id)
                vals['attendee_line_ids'] = [
                    (5, 0, 0),
                    *[
                        (0, 0, {
                            'employee_id': employee.id,
                            'is_present': True,
                            'note': False,
                        })
                        for employee in assignment._get_target_employees()
                    ],
                ]
            sanitized_vals_list.append(vals)
        return super().create(sanitized_vals_list)

    def write(self, vals):
        if self._should_rebuild_attendee_lines(vals) or 'training_assignment_id' in vals:
            for record in self:
                record_vals = dict(vals)
                assignment = self.env['training.assignment'].browse(record_vals['training_assignment_id']) \
                    if record_vals.get('training_assignment_id') else record.training_assignment_id
                if assignment:
                    record_vals['attendee_line_ids'] = record._prepare_attendee_line_commands(assignment=assignment)
                super(TrainingAttendance, record).write(record_vals)
            return True
        return super().write(vals)

    def action_view_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Training Attendance',
            'res_model': 'training.attendance',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

class TrainingAttendanceLine(models.Model):
    _name = 'training.attendance.line'
    _description = 'Training Attendance Line'
    _order = 'employee_id'

    attendance_id = fields.Many2one(
        'training.attendance',
        string='Attendance',
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Trainee',
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        readonly=True,
        store=True,
    )
    is_present = fields.Boolean(string='Present', default=True)
    note = fields.Char(string='Note')

    def action_view_employee(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Employee',
            'res_model': 'hr.employee',
            'res_id': self.employee_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    _sql_constraints = [
        (
            'training_attendance_employee_uniq',
            'unique(attendance_id, employee_id)',
            'Each trainee can only appear once in a training attendance record.',
        ),
    ]
