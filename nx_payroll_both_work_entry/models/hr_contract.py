# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, timedelta, time as dtime

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_BOTH_SOURCE = 'both'
_DEFAULT_WORK_START_HOUR = 8.0   # 08:00 fallback when no calendar is set
_DEFAULT_DAY_HOURS = 8.0          # fallback day length in hours


class HrContract(models.Model):
    """
    Extends hr.contract to add the 'Both' Work Entry Source option.

    When work_entry_source == 'both':
      - Daily timesheet hours are fetched for the employee.
      - If hours on a given day >= minimum_timesheet_hours  → full working day.
      - If hours on a given day <  minimum_timesheet_hours  → actual hours only.
    """

    _inherit = 'hr.contract'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    work_entry_source = fields.Selection(
        selection_add=[(_BOTH_SOURCE, 'Both (Timesheet + Full Day Threshold)')],
        ondelete={_BOTH_SOURCE: 'set default'},
    )

    @api.depends('structure_type_id', 'work_entry_source')
    def _compute_schedule_pay(self):
        both_contracts = self.filtered(lambda contract: contract.work_entry_source == _BOTH_SOURCE)
        other_contracts = self - both_contracts
        if other_contracts:
            super(HrContract, other_contracts)._compute_schedule_pay()
        for contract in both_contracts:
            contract.schedule_pay = 'daily'

    @api.depends('structure_type_id', 'work_entry_source')
    def _compute_wage_type(self):
        both_contracts = self.filtered(lambda contract: contract.work_entry_source == _BOTH_SOURCE)
        other_contracts = self - both_contracts
        if other_contracts:
            super(HrContract, other_contracts)._compute_wage_type()
        for contract in both_contracts:
            contract.wage_type = 'monthly'

    @api.onchange('work_entry_source')
    def _onchange_work_entry_source_both(self):
        if self.work_entry_source == _BOTH_SOURCE:
            self.schedule_pay = 'daily'
            self.wage_type = 'monthly'
            employee_structure_type = self.env.ref(
                'hr_contract.structure_type_employee',
                raise_if_not_found=False,
            )
            if employee_structure_type:
                self.structure_type_id = employee_structure_type

    @api.constrains('work_entry_source', 'wage', 'employee_id', 'structure_type_id')
    def _check_both_work_entry_source_configuration(self):
        for contract in self.filtered(lambda c: c.work_entry_source == _BOTH_SOURCE):
            if contract.wage <= 0:
                raise ValidationError(_(
                    'Contracts with Work Entry Source "Both" require a positive daily Wage.'
                ))
            if contract._get_both_partial_hourly_cost() <= 0:
                raise ValidationError(_(
                    'Contracts with Work Entry Source "Both" require a positive Hourly Cost '
                    'on the employee or a positive Hourly Wage fallback on the contract.'
                ))
            employee_structure_type = self.env.ref(
                'hr_contract.structure_type_employee',
                raise_if_not_found=False,
            )
            if employee_structure_type and contract.structure_type_id != employee_structure_type:
                raise ValidationError(_(
                    'Contracts with Work Entry Source "Both" must use the Employee salary structure type, '
                    'not the Worker structure type.'
                ))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_minimum_timesheet_hours(self):
        """
        Return the configured minimum timesheet hours from system parameters.

        :returns: float – minimum hours threshold (default 8.0).
        """
        param = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param(
                'nx_payroll_both_work_entry.minimum_timesheet_hours',
                str(_DEFAULT_DAY_HOURS),
            )
        )
        try:
            return float(param)
        except (TypeError, ValueError):
            _logger.warning(
                'nx_payroll_both_work_entry: invalid minimum_timesheet_hours '
                'parameter value %r — falling back to %s',
                param,
                _DEFAULT_DAY_HOURS,
            )
            return _DEFAULT_DAY_HOURS

    @api.model
    def _get_both_work_entry_type(self):
        """
        Resolve the regular work entry type (WORK100 / attendance).

        Tries the standard XML-ID first; falls back to a domain search.

        :returns: hr.work.entry.type record or empty recordset.
        """
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
                'nx_payroll_both_work_entry: Could not find a work entry type '
                'with code WORK100 or XML-ID hr_work_entry.work_entry_type_attendance.'
            )
        return work_entry_type

    def _get_calendar_day_info(self, calendar, work_date):
        """
        Return (start_hour, total_hours) from the resource calendar for *work_date*.

        :param calendar: resource.calendar record (may be empty).
        :param work_date: date object.
        :returns: tuple(float start_hour, float total_hours)
        """
        if not calendar:
            return _DEFAULT_WORK_START_HOUR, _DEFAULT_DAY_HOURS

        weekday = str(work_date.weekday())
        attendances = calendar.attendance_ids.filtered(
            lambda a: a.dayofweek == weekday
        ).sorted('hour_from')

        if not attendances:
            return _DEFAULT_WORK_START_HOUR, _DEFAULT_DAY_HOURS

        start_hour = attendances[0].hour_from
        total_hours = sum(a.hour_to - a.hour_from for a in attendances)
        return start_hour, total_hours

    def _get_both_partial_hourly_cost(self):
        """
        Return the hourly rate used for partial-day payroll.

        The business rule prefers the employee Hourly Cost from the System tab.
        If it is missing, the contract Hourly Wage is used as a fallback.
        """
        self.ensure_one()
        employee_hourly_cost = getattr(self.employee_id, 'hourly_cost', 0.0) or 0.0
        if employee_hourly_cost > 0:
            return employee_hourly_cost
        return self.hourly_wage or 0.0

    def _get_both_day_buckets(self, date_start, date_stop):
        """
        Aggregate timesheet hours into daily payroll buckets for the Both source.

        :returns: list(dict) with work_date, logged_hours, entry_hours,
                  calendar_day_hours and is_full_day.
        """
        self.ensure_one()

        min_hours = self._get_minimum_timesheet_hours()
        d_start = self._to_date(date_start)
        d_stop = self._to_date(date_stop)
        calendar = (
            self.employee_id.resource_calendar_id
            or self.resource_calendar_id
            or self.env.company.resource_calendar_id
        )

        daily_hours = {}
        for timesheet in self._search_timesheet_lines(d_start, d_stop):
            work_date = self._to_date(timesheet.date)
            daily_hours[work_date] = (
                daily_hours.get(work_date, 0.0) + self._timesheet_line_hours(timesheet)
            )

        buckets = []
        for work_date, logged_hours in sorted(daily_hours.items()):
            if logged_hours <= 0:
                continue

            start_hour, calendar_day_hours = self._get_calendar_day_info(calendar, work_date)
            is_full_day = logged_hours >= min_hours
            buckets.append({
                'work_date': work_date,
                'logged_hours': logged_hours,
                'start_hour': start_hour,
                'calendar_day_hours': calendar_day_hours,
                # The threshold decides whether the day is full or partial,
                # but displayed/generated hours should remain the actual hours.
                'entry_hours': logged_hours,
                'is_full_day': is_full_day,
            })
        return buckets

    @staticmethod
    def _to_date(value):
        """Coerce *value* to a :class:`datetime.date`."""
        if isinstance(value, datetime):
            return value.date()
        return value  # already a date

    @staticmethod
    def _hour_to_time(hour_float):
        """Convert a float hour (e.g. 8.5) to a :class:`datetime.time`."""
        hours = int(hour_float)
        minutes = int(round((hour_float - hours) * 60))
        return dtime(min(hours, 23), min(minutes, 59))

    # ------------------------------------------------------------------
    # Core work-entry generation for 'both' source
    # ------------------------------------------------------------------

    def _get_both_work_entries_values(self, date_start, date_stop):
        """
        Build work entry value dicts for a single contract whose
        work_entry_source is 'both'.

        Algorithm
        ---------
        1. Fetch all approved timesheets for the employee within
           [date_start, date_stop].
        2. Group them by calendar date and sum unit_amount (hours).
        3. For each date that has logged hours:
           - hours >= minimum_timesheet_hours  → full day (threshold hours)
           - hours <  minimum_timesheet_hours  → actual hours

        :param date_start: date or datetime — period start (inclusive).
        :param date_stop:  date or datetime — period end   (inclusive).
        :returns: list of dicts suitable for env['hr.work.entry'].create().
        :raises: nothing — logs warnings on missing configuration.

        Example::

            vals = contract._get_both_work_entries_values(
                date(2025, 1, 1), date(2025, 1, 31)
            )
            self.env['hr.work.entry'].create(vals)
        """
        self.ensure_one()

        work_entry_type = self._get_both_work_entry_type()
        if not work_entry_type:
            return []

        d_start = self._to_date(date_start)
        d_stop = self._to_date(date_stop)
        vals_list = []
        min_hours = self._get_minimum_timesheet_hours()

        for bucket in self._get_both_day_buckets(d_start, d_stop):
            dt_start = datetime.combine(
                bucket['work_date'],
                self._hour_to_time(bucket['start_hour']),
            )

            if bucket['is_full_day']:
                full_day_stop = dt_start + timedelta(hours=bucket['entry_hours'])
                vals_list.append({
                    'name': '%s - Full Day (%.2fh logged)' % (
                        self.employee_id.name, bucket['logged_hours']
                    ),
                    'date_start': dt_start,
                    'date_stop': full_day_stop,
                    'work_entry_type_id': work_entry_type.id,
                    'employee_id': self.employee_id.id,
                    'contract_id': self.id,
                    'company_id': self.company_id.id,
                    'state': 'draft',
                    'timesheet_generated': True,
                })
            else:
                vals_list.append({
                    'name': '%s - Partial Day (%.2fh / %.2fh min)' % (
                        self.employee_id.name, bucket['logged_hours'], min_hours
                    ),
                    'date_start': dt_start,
                    'date_stop': dt_start + timedelta(hours=bucket['entry_hours']),
                    'work_entry_type_id': work_entry_type.id,
                    'employee_id': self.employee_id.id,
                    'contract_id': self.id,
                    'company_id': self.company_id.id,
                    'state': 'draft',
                    'timesheet_generated': True,
                })

        _logger.info(
            'nx_payroll_both_work_entry: Generated %d work entries for contract %s '
            '[%s → %s] (min=%.1fh)',
            len(vals_list), self.name, d_start, d_stop, min_hours,
        )
        return vals_list

    # ------------------------------------------------------------------
    # Override: hook into Odoo's work-entry generation pipeline
    # ------------------------------------------------------------------

    def _get_work_entries_values(self, date_start, date_stop):
        """
        Override to intercept contracts with work_entry_source == 'both'.

        'Both' contracts are processed by our custom logic.
        All other contracts follow the standard Odoo pipeline unchanged.

        :param date_start: date or datetime.
        :param date_stop:  date or datetime.
        :returns: list of work entry value dicts.
        """
        both_contracts = self.filtered(lambda c: c.work_entry_source == _BOTH_SOURCE)
        other_contracts = self - both_contracts

        result = []

        # Standard pipeline for non-'both' contracts
        if other_contracts:
            result += super(HrContract, other_contracts)._get_work_entries_values(
                date_start,
                date_stop,
            )

        # Custom pipeline for 'both' contracts
        for contract in both_contracts:
            result += contract._get_both_work_entries_values(date_start, date_stop)

        return result
