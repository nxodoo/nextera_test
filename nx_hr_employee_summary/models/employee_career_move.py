# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models


def _move_sort_key(move):
    """Stable, NewId-safe ordering key for career moves."""
    return (
        move.date or date.min,
        move.id if isinstance(move.id, int) else 0,
    )


class EmployeeCareerMove(models.Model):
    _name = 'hr.employee.career.move'
    _description = 'Employee Career Move'
    _order = 'date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        ondelete='cascade', required=True, index=True,
    )
    date = fields.Date(string='Effective Date', required=True,
                       default=fields.Date.context_today)
    move_type = fields.Selection(
        selection=[
            ('promotion', 'Promotion'),
            ('transfer', 'Transfer'),
            ('title_change', 'Title Change'),
            ('renewal', 'Renewal'),
            ('other', 'Other'),
        ],
        string='Move Type', required=True, default='promotion',
    )
    from_job_id = fields.Many2one('hr.job', string='From Position')
    to_job_id = fields.Many2one('hr.job', string='To Position')
    from_department_id = fields.Many2one('hr.department', string='From Department')
    to_department_id = fields.Many2one('hr.department', string='To Department')
    note = fields.Char(string='Note')

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    salary = fields.Monetary(
        string='Salary', currency_field='currency_id',
        help='Monthly salary effective from this move. Drives the salary '
             'timeline and the % increase on the Summary tab.',
    )
    pct_increase = fields.Float(
        string='% vs Previous', compute='_compute_pct_increase', store=True,
        help='Salary increase compared to the previous move (chronological).',
    )

    @api.depends('employee_id', 'salary', 'date',
                 'employee_id.nx_career_move_ids.salary',
                 'employee_id.nx_career_move_ids.date')
    def _compute_pct_increase(self):
        for employee in self.mapped('employee_id'):
            moves = employee.nx_career_move_ids.sorted(key=_move_sort_key)
            previous = 0.0
            for move in moves:
                move.pct_increase = (
                    (move.salary - previous) / previous * 100.0 if previous else 0.0
                )
                if move.salary:
                    previous = move.salary
        for move in self.filtered(lambda m: not m.employee_id):
            move.pct_increase = 0.0

    @api.onchange('employee_id', 'move_type')
    def _onchange_defaults(self):
        if self.employee_id and not self.from_job_id:
            self.from_job_id = self.employee_id.job_id
            self.from_department_id = self.employee_id.department_id
