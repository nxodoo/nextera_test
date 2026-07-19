# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_SUPPORTED_WORK_ENTRY_SOURCES = ('timesheet', 'both')


class AccountAnalyticLine(models.Model):
    """
    Enforces a timesheet date restriction for regular employees.

    Allowed dates  : today or yesterday (in the user's timezone).
    Blocked dates  : any future date, or any date older than yesterday.

    Exemptions (no restriction applied):
        - User has the 'Bypass Timesheet Date Restriction' group.
        - User has the 'Project / Manager' group (project managers).
        - The record is not a timesheet line (no project_id / task_id).
    """

    _inherit = 'account.analytic.line'

    mass_internal_entry = fields.Boolean(
        string='Mass Internal Entry',
        help='Set when the timesheet was created by the internal mass allocation wizard.',
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_timesheet_line(self):
        """Return True when this analytic line is a timesheet (has project/task)."""
        analytic_model = self.env['account.analytic.line']
        if 'is_timesheet' in analytic_model._fields:
            return self.is_timesheet
        return bool(self.project_id or self.task_id)

    def _get_user_today(self):
        """Return today's date in the current user's timezone."""
        user_tz = self.env.user.tz or 'UTC'
        try:
            tz = pytz.timezone(user_tz)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                'nx_payroll_timesheet_work_entry: unknown timezone %r for user %s, '
                'falling back to UTC.',
                user_tz,
                self.env.user.login,
            )
            tz = pytz.utc
        return fields.Datetime.now().astimezone(tz).date()

    def _user_can_bypass_date_restriction(self):
        """
        Return True when the current user is exempt from the date restriction.

        Exempt users:
            - Members of 'Bypass Timesheet Date Restriction' group.
            - Project Managers (project.group_project_manager).
        """
        bypass_group = self.env.ref(
            'nx_payroll_timesheet_work_entry.group_bypass_timesheet_date_restriction',
            raise_if_not_found=False,
        )
        if bypass_group and self.env.user in bypass_group.users:
            return True

        project_manager_group = self.env.ref(
            'project.group_project_manager',
            raise_if_not_found=False,
        )
        if project_manager_group and self.env.user in project_manager_group.users:
            return True

        return False

    def _validate_timesheet_date(self, date_value):
        """
        Raise ValidationError when *date_value* falls outside today/yesterday.

        :param date_value: datetime.date or falsy — if falsy the check is skipped.
        """
        if not date_value:
            return

        today = self._get_user_today()
        yesterday = today - timedelta(days=1)

        if date_value > today:
            raise ValidationError(_(
                'Future timesheet entries are not allowed.\n'
                'You tried to save a timesheet for %(date)s, '
                'but only today (%(today)s) and yesterday (%(yesterday)s) are permitted.',
                date=date_value,
                today=today,
                yesterday=yesterday,
            ))

        if date_value < yesterday:
            raise ValidationError(_(
                'You can only create timesheets for today or yesterday.\n'
                'You tried to save a timesheet for %(date)s, '
                'but only today (%(today)s) and yesterday (%(yesterday)s) are permitted.',
                date=date_value,
                today=today,
                yesterday=yesterday,
            ))

    def _user_can_manage_internal_entries(self):
        """Return True when the current user may manage restricted internal entries."""
        return (
            self.env.user.has_group(
                'nx_payroll_timesheet_work_entry.group_manage_internal_project_entries'
            )
            or self.env.user.has_group('base.group_system')
        )

    def _is_readonly(self):
        """
        Keep mass-allocated internal entries visible to employees but read-only.
        """
        self.ensure_one()
        return bool(
            self.mass_internal_entry and not self._user_can_manage_internal_entries()
        ) or super()._is_readonly()

    @api.model
    def _get_internal_project_from_values(self, vals):
        """Resolve the project targeted by vals, if any."""
        project_id = vals.get('project_id')
        if not project_id:
            return self.env['project.project']
        return self.env['project.project'].sudo().browse(project_id)

    @api.model
    def _ensure_internal_project_entry_allowed(self, project, operation='create'):
        """
        Block unauthorized access to restricted internal projects.
        """
        if not project or not project.exists() or not project.restricted_internal_entries:
            return

        if self._user_can_manage_internal_entries():
            return

        if operation == 'create':
            raise ValidationError(
                _("You are not allowed to create entries in the Internal Project.")
            )

        raise ValidationError(
            _("You are not allowed to modify entries in the Internal Project.")
        )

    def _get_related_employees(self):
        """
        Resolve employees that should receive work-entry refreshes for these lines.

        This keeps the sync logic tolerant to the different link patterns Odoo
        can use for timesheets.
        """
        employees = self.mapped('employee_id')
        if employees:
            return employees
        return self.mapped('user_id.employee_id')

    def _get_work_entry_sync_values(self):
        """
        Collect employee/date pairs affected by these timesheet lines.

        :returns: list(tuple(hr.employee, date))
        """
        sync_values = []
        for line in self:
            if not line._is_timesheet_line() or not line.date:
                continue
            employee = line.employee_id or line.user_id.employee_id
            if not employee:
                continue
            sync_values.append((employee, line.date))
        return sync_values

    @api.model
    def _refresh_work_entries_from_timesheets(self, sync_values):
        """
        Regenerate work entries for the provided employee/date pairs.

        This is intentionally narrow: we only refresh contracts whose work entry
        source depends on timesheets, and only for the exact dates touched by
        the edited timesheet lines.
        """
        if not sync_values:
            return

        contract_model = self.env['hr.contract'].sudo()
        dates_by_employee = {}
        for employee, work_date in sync_values:
            employee = employee.sudo()
            work_date = fields.Date.to_date(work_date)
            if not employee or not work_date:
                continue
            dates_by_employee.setdefault(employee.id, {
                'employee': employee,
                'dates': set(),
            })['dates'].add(work_date)

        for data in dates_by_employee.values():
            employee = data['employee']
            for work_date in sorted(data['dates']):
                contracts = contract_model.search([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ['open', 'close']),
                    ('work_entry_source', 'in', _SUPPORTED_WORK_ENTRY_SOURCES),
                    ('date_start', '<=', work_date),
                    '|',
                    ('date_end', '=', False),
                    ('date_end', '>=', work_date),
                ])
                for contract in contracts:
                    contract.generate_work_entries(work_date, work_date, force=True)
                    _logger.info(
                        'nx_payroll_timesheet_work_entry: refreshed work entries '
                        'for employee %s on %s via timesheet sync (contract=%s, source=%s).',
                        employee.name,
                        work_date,
                        contract.name,
                        contract.work_entry_source,
                    )

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Validate date on new timesheet lines before saving."""
        for vals in vals_list:
            self._ensure_internal_project_entry_allowed(
                self._get_internal_project_from_values(vals),
                operation='create',
            )

        if not self._user_can_bypass_date_restriction():
            for vals in vals_list:
                # Only validate if this is a timesheet line (has project or task)
                if vals.get('project_id') or vals.get('task_id'):
                    date_value = vals.get('date')
                    if date_value:
                        # date may come in as string 'YYYY-MM-DD' from RPC
                        if isinstance(date_value, str):
                            date_value = fields.Date.from_string(date_value)
                        self._validate_timesheet_date(date_value)
        records = super().create(vals_list)
        self._refresh_work_entries_from_timesheets(records._get_work_entry_sync_values())
        return records

    def write(self, vals):
        """Validate date on timesheet lines being edited."""
        target_project = self._get_internal_project_from_values(vals) if vals.get('project_id') else False
        for record in self:
            self._ensure_internal_project_entry_allowed(
                target_project or record.project_id,
                operation='write',
            )

        if not self._user_can_bypass_date_restriction():
            new_date = vals.get('date')
            for record in self:
                if not record._is_timesheet_line():
                    # Becoming a timesheet line in this write?
                    if not (vals.get('project_id') or vals.get('task_id')):
                        continue

                # Determine the effective date after this write
                if new_date:
                    effective_date = new_date
                    if isinstance(effective_date, str):
                        effective_date = fields.Date.from_string(effective_date)
                else:
                    effective_date = record.date

                self._validate_timesheet_date(effective_date)
        sync_values = self._get_work_entry_sync_values()
        result = super().write(vals)
        sync_values += self._get_work_entry_sync_values()
        self._refresh_work_entries_from_timesheets(sync_values)
        return result

    def unlink(self):
        """Restrict deletion of internal project entries."""
        for record in self:
            self._ensure_internal_project_entry_allowed(
                record.project_id,
                operation='unlink',
            )
        sync_values = self._get_work_entry_sync_values()
        result = super().unlink()
        self._refresh_work_entries_from_timesheets(sync_values)
        return result
