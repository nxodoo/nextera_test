# -*- coding: utf-8 -*-
import json
from datetime import datetime, time as dtime, timedelta

from odoo import api, fields, models
from odoo.tools import format_date

from .employee_career_move import _move_sort_key


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ------------------------------------------------------------------
    # Currency
    # ------------------------------------------------------------------
    nx_currency_id = fields.Many2one(
        'res.currency',
        string='Summary Currency',
        default=lambda self: self.env.company.currency_id,
    )

    # ------------------------------------------------------------------
    # 1. Renewal Decision Summary
    # ------------------------------------------------------------------
    nx_contract_end_date = fields.Date(
        string='Contract End Date',
        compute='_compute_nx_renewal', store=False,
    )
    nx_days_remaining = fields.Integer(
        string='Days Remaining',
        compute='_compute_nx_renewal', store=False,
    )
    nx_system_recommendation = fields.Selection(
        selection=[
            ('renew', 'Renew Contract'),
            ('review', 'Review Required'),
            ('terminate', 'Do Not Renew'),
        ],
        string='System Recommendation',
        compute='_compute_nx_renewal', store=False,
    )

    # ------------------------------------------------------------------
    # 2. Career Summary
    # ------------------------------------------------------------------
    nx_career_move_ids = fields.One2many(
        'hr.employee.career.move', 'employee_id', string='Company Moves',
    )
    nx_years_of_service = fields.Float(
        string='Years of Service',
        compute='_compute_nx_career', store=False,
    )
    nx_promotions_count = fields.Integer(
        string='Promotions', compute='_compute_nx_career', store=False,
    )
    nx_transfers_count = fields.Integer(
        string='Transfers', compute='_compute_nx_career', store=False,
    )
    nx_last_title_change = fields.Date(
        string='Last Title Change', compute='_compute_nx_career', store=False,
    )
    nx_last_dept_change = fields.Date(
        string='Last Dept. Change', compute='_compute_nx_career', store=False,
    )
    nx_last_renewal_date = fields.Date(
        string='Last Renewal', compute='_compute_nx_career', store=False,
    )

    # ------------------------------------------------------------------
    # 3. Compensation Growth
    # ------------------------------------------------------------------
    nx_current_monthly_cost = fields.Monetary(
        string='Current Monthly Cost', currency_field='nx_currency_id',
        compute='_compute_nx_compensation', store=False,
    )
    nx_current_annual_cost = fields.Monetary(
        string='Current Annual Cost', currency_field='nx_currency_id',
        compute='_compute_nx_compensation', store=False,
    )
    nx_starting_salary = fields.Monetary(
        string='Starting Salary', currency_field='nx_currency_id',
        compute='_compute_nx_compensation', store=False,
    )
    nx_total_growth_pct = fields.Float(
        string='Total Growth %', compute='_compute_nx_compensation', store=False,
    )

    # ------------------------------------------------------------------
    # 4. Attendance, Leave & Discipline
    # ------------------------------------------------------------------
    nx_period_start_date = fields.Date(
        string='Attendance Period Start',
        help='Start date used to compute working days, leaves and late arrivals.',
    )
    nx_period_end_date = fields.Date(
        string='Attendance Period End',
        help='Optional end date. Leave empty to compute up to today automatically.',
    )
    nx_period_label = fields.Char(
        string='Attendance Period', compute='_compute_nx_period_label', store=False,
    )
    nx_total_working_days = fields.Integer(
        string='Total Working Days',
        compute='_compute_nx_operational_record', store=False,
    )
    nx_present_days = fields.Integer(
        string='Present Days',
        compute='_compute_nx_present_days',
        inverse='_inverse_nx_present_days',
        store=True,
        readonly=False,
        help='Computed from timesheet days when available, but can still be adjusted manually.',
    )
    nx_absent_days = fields.Integer(
        string='Absent Days', compute='_compute_nx_attendance',
        store=False,
    )
    nx_attendance_pct = fields.Float(
        string='Attendance %', compute='_compute_nx_attendance', store=False,
    )
    nx_sick_leave_days = fields.Integer(
        string='Sick Leave (days)',
        compute='_compute_nx_operational_record', store=False,
    )
    nx_annual_leave_days = fields.Integer(
        string='Annual Leave (days)',
        compute='_compute_nx_operational_record', store=False,
    )
    nx_unpaid_leave_days = fields.Integer(
        string='Unpaid Leave (days)',
        compute='_compute_nx_operational_record', store=False,
    )
    nx_other_leave_days = fields.Integer(
        string='Other Leave (days)',
        compute='_compute_nx_operational_record', store=False,
    )
    nx_late_arrivals = fields.Integer(
        string='Late Arrivals',
        compute='_compute_nx_operational_record', store=False,
    )
    nx_warnings_count = fields.Integer(string='Disciplinary Warnings')

    # ------------------------------------------------------------------
    # 5. HR Recommendation Note
    # ------------------------------------------------------------------
    nx_hr_comments = fields.Text(string='HR Comments')
    nx_manager_comments = fields.Text(string='Direct Manager Comments')
    nx_decision_summary = fields.Text(string='Decision Summary')

    # ------------------------------------------------------------------
    # Rendering payload for the OWL dashboard widget
    # ------------------------------------------------------------------
    nx_summary_data_json = fields.Text(
        string='Summary Data (JSON)',
        compute='_compute_nx_summary_data_json', store=False,
    )

    # ==================================================================
    # Compute methods
    # ==================================================================
    @api.depends('contract_id', 'contract_id.date_end',
                 'nx_warnings_count', 'nx_total_working_days', 'nx_present_days')
    def _compute_nx_renewal(self):
        today = fields.Date.context_today(self)
        for emp in self:
            end_date = False
            contract = emp.contract_id if 'contract_id' in emp._fields else False
            if contract and contract.date_end:
                end_date = contract.date_end
            emp.nx_contract_end_date = end_date
            emp.nx_days_remaining = (end_date - today).days if end_date else 0
            # Simple deterministic recommendation heuristic.
            recommendation = 'renew'
            if emp.nx_warnings_count and emp.nx_warnings_count >= 2:
                recommendation = 'review'
            if emp.nx_total_working_days:
                ratio = (emp.nx_present_days or 0) / emp.nx_total_working_days
                if ratio < 0.85:
                    recommendation = 'review'
                if ratio < 0.70:
                    recommendation = 'terminate'
            emp.nx_system_recommendation = recommendation

    @api.depends('nx_career_move_ids.date', 'nx_career_move_ids.move_type',
                 'nx_career_move_ids.from_department_id',
                 'nx_career_move_ids.to_department_id',
                 'nx_career_move_ids.from_job_id', 'nx_career_move_ids.to_job_id',
                 'job_history_ids.date_from',
                 'first_contract_date', 'contract_id.date_start',
                 'contract_ids.date_start', 'contract_ids.state')
    def _compute_nx_career(self):
        today = fields.Date.context_today(self)
        for emp in self:
            lines = emp.job_history_ids.sorted(
                key=lambda l: (l.date_from or today, l.id)
            )
            # Years of service span the employee's whole tenure: anchor on the
            # earliest start date across ALL contracts (running, expired or
            # otherwise), so previous/expired contracts are counted too.
            start = False
            if 'contract_ids' in emp._fields:
                contract_starts = [
                    c.date_start for c in emp.contract_ids if c.date_start
                ]
                if contract_starts:
                    start = min(contract_starts)
            # Fallbacks when no contracts exist on the employee.
            if not start and 'first_contract_date' in emp._fields:
                start = emp.first_contract_date
            if not start and emp.contract_id and emp.contract_id.date_start:
                start = emp.contract_id.date_start
            if not start and lines:
                start = lines[0].date_from
            emp.nx_years_of_service = round((today - start).days / 365.25, 1) if start else 0.0

            # Promotions / transfers / latest changes come from the Company
            # Moves log maintained on the Resume tab. A move counts as a
            # transfer whenever the department actually changes (or it is
            # explicitly typed as a transfer), regardless of the move type.
            moves = emp.nx_career_move_ids.sorted(key=_move_sort_key)

            def _is_transfer(m):
                dept_changed = (
                    m.from_department_id and m.to_department_id
                    and m.from_department_id != m.to_department_id
                )
                return m.move_type == 'transfer' or bool(dept_changed)

            def _is_title_change(m):
                job_changed = (
                    m.from_job_id and m.to_job_id and m.from_job_id != m.to_job_id
                )
                return m.move_type in ('promotion', 'title_change') or bool(job_changed)

            emp.nx_promotions_count = len(
                moves.filtered(lambda m: m.move_type == 'promotion')
            )
            transfer_moves = moves.filtered(_is_transfer)
            emp.nx_transfers_count = len(transfer_moves)
            title_moves = moves.filtered(_is_title_change)
            emp.nx_last_title_change = title_moves[-1].date if title_moves else False
            emp.nx_last_dept_change = transfer_moves[-1].date if transfer_moves else False
            renewals = moves.filtered(lambda m: m.move_type == 'renewal')
            emp.nx_last_renewal_date = renewals[-1].date if renewals else False

    @api.depends('nx_career_move_ids.salary', 'nx_career_move_ids.date')
    def _compute_nx_compensation(self):
        for emp in self:
            moves = emp.nx_career_move_ids.sorted(key=_move_sort_key)
            paid = moves.filtered(lambda m: m.salary)
            starting = paid[0].salary if paid else 0.0
            current = paid[-1].salary if paid else 0.0
            emp.nx_starting_salary = starting
            emp.nx_current_monthly_cost = current
            emp.nx_current_annual_cost = current * 12.0
            emp.nx_total_growth_pct = (
                (current - starting) / starting * 100.0 if starting else 0.0
            )

    @api.depends('nx_period_start_date', 'nx_period_end_date', 'contract_id.date_start')
    def _compute_nx_period_label(self):
        for emp in self:
            start_date, end_date = emp._nx_get_attendance_period()
            if start_date and end_date:
                emp.nx_period_label = '%s - %s' % (
                    format_date(emp.env, start_date),
                    format_date(emp.env, end_date),
                )
            else:
                emp.nx_period_label = ''

    @api.depends(
        'nx_period_start_date', 'nx_period_end_date',
        'contract_id', 'contract_id.date_start', 'contract_id.work_entry_source',
        'contract_id.resource_calendar_id', 'resource_calendar_id',
    )
    def _compute_nx_operational_record(self):
        for emp in self:
            start_date, end_date = emp._nx_get_attendance_period()
            if not start_date or not end_date:
                emp.nx_total_working_days = 0
                emp.nx_sick_leave_days = 0
                emp.nx_annual_leave_days = 0
                emp.nx_unpaid_leave_days = 0
                emp.nx_other_leave_days = 0
                emp.nx_late_arrivals = 0
                continue

            emp.nx_total_working_days = emp._nx_compute_total_working_days(
                start_date, end_date,
            )
            leave_counts = emp._nx_compute_leave_counts(start_date, end_date)
            emp.nx_sick_leave_days = leave_counts['sick']
            emp.nx_annual_leave_days = leave_counts['annual']
            emp.nx_unpaid_leave_days = leave_counts['unpaid']
            emp.nx_other_leave_days = leave_counts['other']
            emp.nx_late_arrivals = emp._nx_compute_late_arrivals(
                start_date, end_date,
            )

    @api.depends(
        'nx_period_start_date', 'nx_period_end_date',
        'contract_id', 'contract_id.date_start', 'contract_id.work_entry_source',
    )
    def _compute_nx_present_days(self):
        for emp in self:
            start_date, end_date = emp._nx_get_attendance_period()
            if not start_date or not end_date:
                emp.nx_present_days = 0
                continue
            contract = emp._nx_get_summary_contract()
            emp.nx_present_days = emp._nx_count_timesheet_present_days(
                contract, start_date, end_date,
            )

    def _inverse_nx_present_days(self):
        """Allow HR to adjust present days after the timesheet-based default."""
        return True

    @api.depends('nx_total_working_days', 'nx_present_days')
    def _compute_nx_attendance(self):
        for emp in self:
            total = emp.nx_total_working_days or 0
            present = emp.nx_present_days or 0
            emp.nx_absent_days = max(total - present, 0)
            emp.nx_attendance_pct = round(present / total * 100.0, 1) if total else 0.0

    def _nx_get_attendance_period(self):
        """Return the summary period, defaulting to contract start through today."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        start_date = self.nx_period_start_date
        if not start_date:
            contract = self.contract_id if 'contract_id' in self._fields else False
            start_date = contract.date_start if contract and contract.date_start else today.replace(day=1)
        end_date = self.nx_period_end_date or today
        if start_date > end_date:
            return False, False
        return start_date, end_date

    def _nx_get_summary_contract(self):
        """Return the employee contract used as the operational data source."""
        self.ensure_one()
        return self.contract_id if 'contract_id' in self._fields else self.env['hr.contract']

    def _nx_get_summary_calendar(self):
        """Return the working calendar used for calendar-based summary metrics."""
        self.ensure_one()
        contract = self._nx_get_summary_contract()
        return (
            contract.resource_calendar_id
            or self.resource_calendar_id
            or self.env.company.resource_calendar_id
        )

    def _nx_compute_total_working_days(self, start_date, end_date):
        """Compute total working days from the resource calendar."""
        self.ensure_one()
        return self._nx_count_calendar_working_days(start_date, end_date)

    def _nx_count_timesheet_present_days(self, contract, start_date, end_date):
        """Count each date with positive logged timesheet hours as one day."""
        self.ensure_one()
        if not contract or 'account.analytic.line' not in self.env.registry:
            return 0
        if hasattr(contract, '_search_timesheet_lines'):
            timesheets = contract._search_timesheet_lines(start_date, end_date)
        else:
            timesheets = self.env['account.analytic.line'].sudo().search([
                ('employee_id', '=', self.id),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
                ('unit_amount', '>', 0),
            ])
        worked_dates = {
            fields.Date.to_date(line.date)
            for line in timesheets
            if line.unit_amount and line.unit_amount > 0
        }
        return len(worked_dates)

    def _nx_count_calendar_working_days(self, start_date, end_date):
        """Count dates whose weekday exists in the employee working schedule."""
        self.ensure_one()
        calendar = self._nx_get_summary_calendar()
        if not calendar:
            return 0
        working_weekdays = {
            int(attendance.dayofweek)
            for attendance in calendar.attendance_ids
            if (
                'display_type' not in attendance._fields
                or attendance.display_type != 'line_section'
            )
        }
        count = 0
        current = start_date
        while current <= end_date:
            if current.weekday() in working_weekdays:
                count += 1
            current += timedelta(days=1)
        return count

    def _nx_compute_leave_counts(self, start_date, end_date):
        """Bucket approved Time Off days by leave type name."""
        self.ensure_one()
        counts = dict.fromkeys(('sick', 'annual', 'unpaid', 'other'), 0.0)
        if 'hr.leave' not in self.env.registry:
            return counts
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', end_date),
            ('request_date_to', '>=', start_date),
        ])
        for leave in leaves:
            days = self._nx_get_leave_overlap_days(leave, start_date, end_date)
            bucket = self._nx_get_leave_bucket(leave.holiday_status_id)
            counts[bucket] += days
        return {key: int(round(value)) for key, value in counts.items()}

    def _nx_get_leave_overlap_days(self, leave, start_date, end_date):
        """Return leave days within the summary period using request dates."""
        leave_start = max(leave.request_date_from, start_date)
        leave_end = min(leave.request_date_to, end_date)
        if leave_start > leave_end:
            return 0.0
        return (leave_end - leave_start).days + 1

    @staticmethod
    def _nx_get_leave_bucket(leave_type):
        """Classify leave type into the dashboard buckets from its name."""
        name = (leave_type.name or '').lower()
        if 'sick' in name or 'medical' in name:
            return 'sick'
        if 'annual' in name or 'vacation' in name or 'paid time off' in name:
            return 'annual'
        if 'unpaid' in name or 'without pay' in name:
            return 'unpaid'
        return 'other'

    def _nx_compute_late_arrivals(self, start_date, end_date):
        """Count check-ins after the first scheduled attendance hour."""
        self.ensure_one()
        if 'hr.attendance' not in self.env.registry:
            return 0
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', self.id),
            ('check_in', '>=', datetime.combine(start_date, dtime.min)),
            ('check_in', '<=', datetime.combine(end_date, dtime.max)),
        ])
        calendar = self._nx_get_summary_calendar()
        late_count = 0
        for attendance in attendances:
            check_in = fields.Datetime.context_timestamp(self, attendance.check_in)
            expected_hour = self._nx_get_expected_start_hour(calendar, check_in.date())
            if expected_hour is False:
                continue
            expected_dt = datetime.combine(
                check_in.date(),
                self._nx_float_hour_to_time(expected_hour),
            )
            if check_in.replace(tzinfo=None) > expected_dt:
                late_count += 1
        return late_count

    @staticmethod
    def _nx_get_expected_start_hour(calendar, work_date):
        if not calendar:
            return False
        attendances = calendar.attendance_ids.filtered(
            lambda attendance: (
                attendance.dayofweek == str(work_date.weekday())
                and (
                    'display_type' not in attendance._fields
                    or attendance.display_type != 'line_section'
                )
            )
        ).sorted('hour_from')
        return attendances[0].hour_from if attendances else False

    @staticmethod
    def _nx_float_hour_to_time(hour_float):
        hours = int(hour_float)
        minutes = int(round((hour_float - hours) * 60))
        return dtime(min(hours, 23), min(minutes, 59))

    @api.depends(
        'nx_career_move_ids.salary', 'nx_career_move_ids.date',
        'nx_career_move_ids.move_type', 'nx_career_move_ids.pct_increase',
        'nx_career_move_ids.to_job_id', 'nx_career_move_ids.from_job_id',
        'nx_career_move_ids.to_department_id', 'nx_career_move_ids.from_department_id',
        'nx_currency_id',
        'nx_total_working_days', 'nx_present_days', 'nx_absent_days',
        'nx_sick_leave_days', 'nx_annual_leave_days', 'nx_unpaid_leave_days',
        'nx_other_leave_days', 'nx_late_arrivals', 'nx_warnings_count',
        'nx_contract_end_date', 'nx_days_remaining', 'nx_system_recommendation',
        'nx_years_of_service', 'nx_promotions_count', 'nx_transfers_count',
        'nx_last_title_change', 'nx_last_dept_change', 'nx_last_renewal_date',
        'nx_period_label',
    )
    def _compute_nx_summary_data_json(self):
        for emp in self:
            currency = emp.nx_currency_id or emp.env.company.currency_id
            symbol = currency.name or currency.symbol or ''
            moves = emp.nx_career_move_ids.sorted(key=_move_sort_key)
            max_salary = max(moves.mapped('salary')) if moves else 0.0

            milestones = []
            for idx, move in enumerate(moves):
                dept_changed = bool(
                    move.from_department_id and move.to_department_id
                    and move.from_department_id != move.to_department_id
                )
                # Resolve the visual style of the node from its semantics.
                if idx == 0:
                    style = {'icon': 'fa-flag', 'color': '#3B82F6', 'badge': 'START'}
                elif move.move_type == 'renewal':
                    style = {'icon': 'fa-usd', 'color': '#22C55E', 'badge': 'Renewal'}
                elif dept_changed or move.move_type == 'transfer':
                    style = {'icon': 'fa-users', 'color': '#6366F1', 'badge': '→ Transfer'}
                elif move.move_type == 'promotion':
                    style = {'icon': 'fa-line-chart', 'color': '#8B5CF6', 'badge': '↑ Promoted'}
                else:
                    style = {'icon': 'fa-usd', 'color': '#22C55E', 'badge': 'Adjustment'}

                # Sub-label under the node (department / movement detail).
                if move.move_type == 'renewal':
                    movement = 'Annual Review'
                elif dept_changed and move.to_department_id:
                    movement = '→ %s' % move.to_department_id.name
                elif move.move_type == 'promotion':
                    movement = '↑ Promoted'
                elif move.to_department_id:
                    movement = move.to_department_id.name
                else:
                    movement = ''

                date_label = format_date(emp.env, move.date, date_format='MMM y') \
                    if move.date else ''
                if move.move_type == 'renewal':
                    date_label = '%s (Renewal)' % date_label

                title = (move.to_job_id.name if move.to_job_id
                         else (move.from_job_id.name if move.from_job_id else ''))

                milestones.append({
                    'title': title,
                    'date': date_label,
                    'movement': movement,
                    'movement_type': 'hire' if idx == 0 else (move.move_type or 'adjustment'),
                    'badge': style['badge'],
                    'icon': style['icon'],
                    'color': style['color'],
                    'salary': move.salary,
                    'salary_label': self._nx_money_k(move.salary, symbol),
                    'salary_full': self._nx_money(move.salary, symbol),
                    'pct': round(move.pct_increase, 0),
                    'width': round(move.salary / max_salary * 100.0, 1) if max_salary else 0.0,
                })

            data = {
                'currency': symbol,
                'exec': {
                    'end_date': format_date(emp.env, emp.nx_contract_end_date)
                    if emp.nx_contract_end_date else 'Not set',
                    'days_remaining': emp.nx_days_remaining,
                    'recommendation': dict(
                        self._fields['nx_system_recommendation'].selection
                    ).get(emp.nx_system_recommendation, ''),
                    'recommendation_key': emp.nx_system_recommendation or 'review',
                },
                'career': {
                    'years': emp.nx_years_of_service,
                    'promotions': emp.nx_promotions_count,
                    'transfers': emp.nx_transfers_count,
                    'last_title_change': format_date(emp.env, emp.nx_last_title_change)
                    if emp.nx_last_title_change else '—',
                    'last_dept_change': format_date(emp.env, emp.nx_last_dept_change)
                    if emp.nx_last_dept_change else '—',
                    'last_renewal': format_date(emp.env, emp.nx_last_renewal_date)
                    if emp.nx_last_renewal_date else '—',
                },
                'milestones': milestones,
                'compensation': {
                    'monthly': self._nx_money(emp.nx_current_monthly_cost, symbol),
                    'annual': self._nx_money(emp.nx_current_annual_cost, symbol),
                    'starting': self._nx_money(emp.nx_starting_salary, symbol),
                    'current': self._nx_money(emp.nx_current_monthly_cost, symbol),
                    'starting_k': self._nx_money_k(emp.nx_starting_salary, symbol),
                    'current_k': self._nx_money_k(emp.nx_current_monthly_cost, symbol),
                    'growth_pct': round(emp.nx_total_growth_pct, 0),
                    'years': emp.nx_years_of_service,
                },
                'attendance': dict(self._nx_attendance_rating(emp.nx_attendance_pct), **{
                    'period': emp.nx_period_label or '',
                    'pct': emp.nx_attendance_pct,
                    'total': emp.nx_total_working_days,
                    'present': emp.nx_present_days,
                    'absent': emp.nx_absent_days,
                    'sick': emp.nx_sick_leave_days,
                    'annual': emp.nx_annual_leave_days,
                    'unpaid': emp.nx_unpaid_leave_days,
                    'other': emp.nx_other_leave_days,
                    'late': emp.nx_late_arrivals,
                    'warnings': emp.nx_warnings_count,
                }),
            }
            emp.nx_summary_data_json = json.dumps(data)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _nx_attendance_rating(pct):
        """Return the rating label, badge colour and ring colour for a %."""
        if pct >= 95:
            return {'rating': 'EXCELLENT', 'rating_color': '#2563EB', 'ring_color': '#2563EB'}
        if pct >= 85:
            return {'rating': 'GOOD', 'rating_color': '#16A34A', 'ring_color': '#16A34A'}
        if pct >= 75:
            return {'rating': 'FAIR', 'rating_color': '#D97706', 'ring_color': '#D97706'}
        return {'rating': 'POOR', 'rating_color': '#DC2626', 'ring_color': '#DC2626'}

    @staticmethod
    def _nx_money(amount, symbol):
        return '%s %s' % (symbol, '{:,.0f}'.format(amount or 0.0))

    @staticmethod
    def _nx_money_k(amount, symbol):
        return '%s %.0fK' % (symbol, (amount or 0.0) / 1000.0)
