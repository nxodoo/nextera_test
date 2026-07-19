# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta, time as dtime
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.osv import expression

_logger = logging.getLogger(__name__)

_TIMESHEET_SOURCE = 'timesheet'
_DEFAULT_WORK_START_HOUR = 8.0
_DEFAULT_DAY_HOURS = 8.0


class HrContract(models.Model):
    """
    Adds a pure Timesheet Work Entry Source.

    Payroll uses only validated timesheet hours in the period × employee hourly cost.
    Attendance and calendar-based working days are not used.
    """

    _inherit = 'hr.contract'

    work_entry_source = fields.Selection(
        selection_add=[(_TIMESHEET_SOURCE, 'Timesheet')],
        ondelete={_TIMESHEET_SOURCE: 'set default'},
    )
    timesheet_hours_preview = fields.Float(
        string='Timesheet Hours (Current Month)',
        compute='_compute_timesheet_hours_preview',
        help='Sum of timesheet hours for this employee in the current calendar month.',
    )
    attendance_based_on_timesheet = fields.Boolean(
        string='Attendance Based on Timesheet',
        related='employee_id.attendance_based_on_timesheet',
        readonly=False,
        store=True,
        help=(
            'Enable automatic Internal Project timesheets for approved leave '
            'and public holidays.'
        ),
    )

    @api.depends('employee_id', 'work_entry_source')
    def _compute_timesheet_hours_preview(self):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        for contract in self:
            if (
                contract.work_entry_source == _TIMESHEET_SOURCE
                and contract.employee_id
            ):
                contract.timesheet_hours_preview = contract._get_timesheet_hours_total(
                    month_start, today,
                )
            else:
                contract.timesheet_hours_preview = 0.0

    def _get_timesheet_hourly_cost(self):
        """
        Return the hourly rate used by Timesheet payroll.

        The source of truth is the employee Hourly Cost on the System tab.
        """
        self.ensure_one()
        return getattr(self.employee_id, 'hourly_cost', 0.0) or 0.0

    @api.constrains('work_entry_source', 'wage_type', 'employee_id')
    def _check_timesheet_work_entry_source(self):
        for contract in self.filtered(lambda c: c.work_entry_source == _TIMESHEET_SOURCE):
            if contract.wage_type != 'hourly':
                raise ValidationError(_(
                    'Contracts with Work Entry Source "Timesheet" must use '
                    'Hourly Wage type so payroll can multiply hours by the employee Hourly Cost.'
                ))
            if contract._get_timesheet_hourly_cost() <= 0:
                raise ValidationError(_(
                    'Contracts with Work Entry Source "Timesheet" require a '
                    'positive Hourly Cost on the employee System tab.'
                ))

    @api.onchange('work_entry_source')
    def _onchange_work_entry_source_timesheet(self):
        if self.work_entry_source == _TIMESHEET_SOURCE:
            self.wage_type = 'hourly'
            worker_type = self.env.ref(
                'hr_contract.structure_type_worker',
                raise_if_not_found=False,
            )
            if worker_type:
                self.structure_type_id = worker_type

    def _unlink_draft_work_entries_in_period(self, date_start, date_stop):
        """Remove draft work entries in the interval (clears old calendar/attendance rows)."""
        self.ensure_one()
        d_start = self._to_date(date_start)
        d_stop = self._to_date(date_stop)
        start_dt = datetime.combine(d_start, dtime.min)
        stop_dt = datetime.combine(d_stop, dtime.max)
        draft_entries = self.env['hr.work.entry'].sudo().search([
            ('contract_id', '=', self.id),
            ('state', '!=', 'validated'),
            ('date_start', '<', stop_dt),
            ('date_stop', '>', start_dt),
        ])
        if draft_entries:
            draft_entries.unlink()

    @api.depends('structure_type_id', 'work_entry_source')
    def _compute_wage_type(self):
        """Keep hourly wage for Timesheet contracts (structure type often forces monthly)."""
        timesheet_contracts = self.filtered(
            lambda c: c.work_entry_source == _TIMESHEET_SOURCE
        )
        other_contracts = self - timesheet_contracts
        if other_contracts:
            super(HrContract, other_contracts)._compute_wage_type()
        for contract in timesheet_contracts:
            contract.wage_type = 'hourly'

    def _timesheet_line_hours(self, line):
        """Return timesheet quantity as hours (handles day-based encoding)."""
        if self.env['account.analytic.line']._is_timesheet_encode_uom_day():
            calendar = (
                self.resource_calendar_id
                or self.employee_id.resource_calendar_id
                or self.env.company.resource_calendar_id
            )
            hours_per_day = (
                calendar.hours_per_day if calendar and calendar.hours_per_day
                else _DEFAULT_DAY_HOURS
            )
            return line.unit_amount * hours_per_day
        return line.unit_amount

    @api.model
    def _get_timesheet_work_entry_type(self):
        work_entry_type = self.env.ref(
            'hr_work_entry.work_entry_type_attendance',
            raise_if_not_found=False,
        )
        if not work_entry_type:
            work_entry_type = self.env['hr.work.entry.type'].search(
                [('code', '=', 'WORK100')], limit=1
            )
        if not work_entry_type:
            _logger.error(
                'nx_payroll_timesheet_work_entry: work entry type WORK100 not found.'
            )
        return work_entry_type

    @staticmethod
    def _to_date(value):
        if isinstance(value, datetime):
            return value.date()
        return value

    @staticmethod
    def _hour_to_time(hour_float):
        hours = int(hour_float)
        minutes = int(round((hour_float - hours) * 60))
        return dtime(min(hours, 23), min(minutes, 59))

    def _get_timesheet_employee_domain(self):
        """Match timesheet lines for the contract employee (several link patterns)."""
        self.ensure_one()
        employee = self.employee_id
        parts = [[('employee_id', '=', employee.id)]]
        if employee.user_id:
            parts.append([('user_id', '=', employee.user_id.id)])
        return expression.OR(parts)

    def _get_timesheet_line_kind_domain(self):
        """Identify real timesheet lines (project/task), not generic analytic lines."""
        analytic = self.env['account.analytic.line']
        if 'is_timesheet' in analytic._fields:
            return [('is_timesheet', '=', True)]
        return expression.OR([
            [('project_id', '!=', False)],
            [('task_id', '!=', False)],
        ])

    def _get_timesheet_domain(self, date_start, date_stop):
        """Domain for payroll-relevant timesheet lines in [date_start, date_stop]."""
        self.ensure_one()
        d_start = self._to_date(date_start)
        d_stop = self._to_date(date_stop)

        domain = expression.AND([
            self._get_timesheet_employee_domain(),
            self._get_timesheet_line_kind_domain(),
            [('date', '>=', d_start), ('date', '<=', d_stop)],
        ])

        if self.env['ir.config_parameter'].sudo().get_param(
            'nx_payroll_timesheet_work_entry.only_validated_timesheets'
        ) == 'True' and 'validated' in self.env['account.analytic.line']._fields:
            domain = expression.AND([domain, [('validated', '=', True)]])
        return domain

    def _search_timesheet_lines(self, date_start, date_stop):
        """Search timesheet lines with sudo to avoid record-rule blind spots."""
        self.ensure_one()
        domain = self._get_timesheet_domain(date_start, date_stop)
        lines = self.env['account.analytic.line'].sudo().search(domain)
        if lines:
            return lines

        # Fallback: any analytic line with hours for this employee in the period.
        fallback_domain = expression.AND([
            self._get_timesheet_employee_domain(),
            [
                ('date', '>=', self._to_date(date_start)),
                ('date', '<=', self._to_date(date_stop)),
                ('unit_amount', '>', 0),
            ],
        ])
        lines = self.env['account.analytic.line'].sudo().search(fallback_domain)
        if lines:
            _logger.warning(
                'nx_payroll_timesheet_work_entry: using fallback timesheet domain '
                'for %s [%s → %s] — %d line(s) found without project/task filter.',
                self.employee_id.name,
                self._to_date(date_start),
                self._to_date(date_stop),
                len(lines),
            )
        return lines

    def _get_timesheet_hours_total(self, date_start, date_stop):
        """Return the sum of timesheet hours in the period."""
        self.ensure_one()
        timesheets = self._search_timesheet_lines(date_start, date_stop)
        return sum(self._timesheet_line_hours(line) for line in timesheets)

    def _get_timesheet_work_entries_values(self, date_start, date_stop):
        """
        Build one work entry per calendar day from aggregated timesheet hours.

        Only days with logged hours produce entries (no pay without timesheet).
        """
        self.ensure_one()

        work_entry_type = self._get_timesheet_work_entry_type()
        if not work_entry_type:
            return []

        d_start = self._to_date(date_start)
        d_stop = self._to_date(date_stop)

        timesheets = self._search_timesheet_lines(date_start, date_stop)

        daily_hours = {}
        for ts in timesheets:
            ts_date = self._to_date(ts.date)
            daily_hours[ts_date] = (
                daily_hours.get(ts_date, 0.0) + self._timesheet_line_hours(ts)
            )

        if not daily_hours:
            _logger.warning(
                'nx_payroll_timesheet_work_entry: no timesheet hours for %s '
                '[%s → %s] (work_entry_source=%s, contract=%s).',
                self.employee_id.name,
                d_start,
                d_stop,
                self.work_entry_source,
                self.name,
            )
            return []

        calendar = (
            self.resource_calendar_id
            or self.employee_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        vals_list = []
        for work_date, logged_hours in sorted(daily_hours.items()):
            if logged_hours <= 0:
                continue

            start_hour = _DEFAULT_WORK_START_HOUR
            if calendar:
                weekday = str(work_date.weekday())
                attendances = calendar.attendance_ids.filtered(
                    lambda a: a.dayofweek == weekday
                ).sorted('hour_from')
                if attendances:
                    start_hour = attendances[0].hour_from

            dt_start = datetime.combine(work_date, self._hour_to_time(start_hour))
            dt_stop = dt_start + timedelta(hours=logged_hours)

            vals_list.append({
                'name': '%s - Timesheet (%.2fh)' % (self.employee_id.name, logged_hours),
                'date_start': dt_start,
                'date_stop': dt_stop,
                'work_entry_type_id': work_entry_type.id,
                'employee_id': self.employee_id.id,
                'contract_id': self.id,
                'company_id': self.company_id.id,
                'state': 'draft',
                'timesheet_generated': True,
            })

        return vals_list

    def has_static_work_entries(self):
        self.ensure_one()
        if self.work_entry_source == _TIMESHEET_SOURCE:
            return False
        return super().has_static_work_entries()

    def _generate_work_entries(self, date_start, date_stop, force=False):
        """
        For Timesheet contracts, clear all draft work entries in the interval
        before regenerating from timesheets only.
        """
        for contract in self.filtered(lambda c: c.work_entry_source == _TIMESHEET_SOURCE):
            contract._unlink_draft_work_entries_in_period(date_start, date_stop)
        return super()._generate_work_entries(date_start, date_stop, force=force)

    def _get_work_entries_values(self, date_start, date_stop):
        timesheet_contracts = self.filtered(
            lambda c: c.work_entry_source == _TIMESHEET_SOURCE
        )
        other_contracts = self - timesheet_contracts

        result = []
        if other_contracts:
            result += super(HrContract, other_contracts)._get_work_entries_values(
                date_start, date_stop,
            )
        for contract in timesheet_contracts:
            result += contract._get_timesheet_work_entries_values(date_start, date_stop)
        return result

    def action_generate_timesheet_work_entries(self):
        """Regenerate work entries from timesheets for the full current month."""
        for contract in self.filtered(lambda c: c.work_entry_source == _TIMESHEET_SOURCE):
            today = fields.Date.context_today(contract)
            month_start = today.replace(day=1)
            month_end = today + relativedelta(day=31)
            contract._unlink_draft_work_entries_in_period(month_start, month_end)
            contract.generate_work_entries(month_start, month_end, force=True)
        return True
