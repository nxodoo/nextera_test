# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EmployeeJobHistory(models.Model):
    _inherit = 'employee.job.history'

    movement_type = fields.Selection(
        selection=[
            ('hire', 'Hire / Start'),
            ('promotion', 'Promotion'),
            ('transfer', 'Transfer'),
            ('renewal', 'Renewal'),
            ('adjustment', 'Adjustment'),
        ],
        string='Movement Type',
        default='adjustment',
        help='Type of career movement represented by this milestone. '
             'Used to drive the icon/colour on the Summary timeline.',
    )

    movement_label = fields.Char(
        string='Movement / Department',
        help='Short label shown under the milestone, e.g. the new department '
             'on a transfer or "Annual Review" on a renewal.',
    )

    pct_increase = fields.Float(
        string='% vs Previous',
        compute='_compute_pct_increase',
        store=True,
        help='Salary increase compared to the previous milestone (chronological).',
    )

    @api.depends('employee_id', 'salary', 'date_from',
                 'employee_id.job_history_ids.salary',
                 'employee_id.job_history_ids.date_from')
    def _compute_pct_increase(self):
        for employee in self.mapped('employee_id'):
            lines = employee.job_history_ids.sorted(
                key=lambda l: (l.date_from or fields.Date.today(), l.id)
            )
            previous_salary = 0.0
            for line in lines:
                if previous_salary:
                    line.pct_increase = (
                        (line.salary - previous_salary) / previous_salary * 100.0
                    )
                else:
                    line.pct_increase = 0.0
                if line.salary:
                    previous_salary = line.salary
        # Lines without an employee (new, unsaved) default to 0.
        for line in self.filtered(lambda l: not l.employee_id):
            line.pct_increase = 0.0
