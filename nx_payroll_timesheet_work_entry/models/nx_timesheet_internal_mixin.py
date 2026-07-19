# -*- coding: utf-8 -*-
"""
Abstract mixin shared by hr.leave and resource.calendar.leaves
to automate Internal Project timesheet creation.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

_INTERNAL_PROJECT_PARAM = 'nx_payroll_timesheet_work_entry.internal_project_id'
_INTERNAL_PROJECT_NAME = 'Internal Project'


class NxTimesheetInternalMixin(models.AbstractModel):
    _name = 'nx.timesheet.internal.mixin'
    _description = 'Internal Project Timesheet Automation Helpers'

    # ------------------------------------------------------------------
    # Internal Project
    # ------------------------------------------------------------------

    @api.model
    def _get_internal_project(self):
        """
        Return the Internal Project, creating it once if it does not exist.

        The project ID is cached in ir.config_parameter so we avoid a search
        on every call.
        """
        IrConfig = self.env['ir.config_parameter'].sudo()
        project_id = IrConfig.get_param(_INTERNAL_PROJECT_PARAM)

        if project_id:
            project = self.env['project.project'].sudo().browse(int(project_id))
            if project.exists():
                return project

        # Not cached — search by canonical name.
        project = self.env['project.project'].sudo().search(
            [('name', '=', _INTERNAL_PROJECT_NAME)], limit=1
        )
        if not project:
            project = self.env['project.project'].sudo().create({
                'name': _INTERNAL_PROJECT_NAME,
                'privacy_visibility': 'employees',
                'allow_timesheets': True,
                'restricted_internal_entries': True,
            })
            _logger.info(
                'nx_payroll_timesheet_work_entry: '
                'Created Internal Project (id=%d).',
                project.id,
            )
        elif not project.restricted_internal_entries:
            project.sudo().write({'restricted_internal_entries': True})

        IrConfig.set_param(_INTERNAL_PROJECT_PARAM, str(project.id))
        return project

    @api.model
    def _get_internal_timesheet_target(self, employee):
        """
        Return the internal project/task target for the given employee.

        Preference order:
        1. The employee company's standard Odoo internal project and time-off task.
        2. The legacy module-specific fallback internal project.

        :param employee: hr.employee record.
        :returns: tuple(project.project, project.task)
        """
        company = employee.company_id
        project = company.internal_project_id if 'internal_project_id' in company._fields else self.env['project.project']
        task = company.leave_timesheet_task_id if 'leave_timesheet_task_id' in company._fields else self.env['project.task']

        if project and project.exists():
            return project.sudo(), task.sudo() if task and task.exists() else self.env['project.task']

        return self._get_internal_project(), self.env['project.task']

    # ------------------------------------------------------------------
    # Working hours per day
    # ------------------------------------------------------------------

    @api.model
    def _get_employee_hours_per_day(self, employee, date):
        """
        Return the number of working hours for *employee* on *date*.

        Returns 0.0 when the weekday is not in the employee's working schedule
        (e.g. weekend), which signals that no timesheet should be created.

        :param employee: hr.employee record.
        :param date:     datetime.date.
        :returns:        float — hours, or 0.0 for non-working days.
        """
        calendar = (
            employee.resource_calendar_id
            or employee.company_id.resource_calendar_id
        )
        if not calendar:
            return 8.0  # Fallback when no calendar is configured.

        weekday = str(date.weekday())
        attendances = calendar.attendance_ids.filtered(
            lambda a: a.dayofweek == weekday
        )
        if not attendances:
            return 0.0  # Not a working day in this schedule.

        return sum(a.hour_to - a.hour_from for a in attendances)

    # ------------------------------------------------------------------
    # Duplicate guard
    # ------------------------------------------------------------------

    @api.model
    def _internal_timesheet_exists(self, employee, date, project, task=False):
        """
        Return True when a timesheet already exists for *employee* on *date*
        inside *project* and *task*.

        Used to prevent duplicate entries.
        """
        duplicate_domain = [
            ('employee_id', '=', employee.id),
            ('date', '=', date),
            ('project_id', '=', project.id),
        ]
        if task and task.exists():
            duplicate_domain.append(('task_id', '=', task.id))
        return bool(self.env['account.analytic.line'].sudo().search_count(duplicate_domain))

    # ------------------------------------------------------------------
    # Timesheet creation
    # ------------------------------------------------------------------

    @api.model
    def _create_internal_timesheet(self, employee, date, description, hours):
        """
        Create one timesheet line in the Internal Project.

        Silently skips when:
        - *hours* is zero or negative (non-working day).
        - A timesheet already exists for this employee/date/project.

        :param employee:    hr.employee record.
        :param date:        datetime.date.
        :param description: str — timesheet description (leave type or holiday name).
        :param hours:       float — number of hours to log.
        """
        if not hours or hours <= 0:
            return

        project, task = self._get_internal_timesheet_target(employee)

        if self._internal_timesheet_exists(employee, date, project, task=task):
            _logger.info(
                'nx_payroll_timesheet_work_entry: '
                'Skipped duplicate internal timesheet for %s on %s.',
                employee.name, date,
            )
            return

        self.env['account.analytic.line'].sudo().with_context(
            bypass_timesheet_date_restriction=True,
        ).create({
            'employee_id': employee.id,
            'date': date,
            'project_id': project.id,
            'task_id': task.id if task and task.exists() else False,
            'account_id': project.account_id.id,
            'company_id': employee.company_id.id,
            'user_id': employee.user_id.id,
            'name': description,
            'unit_amount': hours,
        })

        _logger.info(
            'nx_payroll_timesheet_work_entry: '
            'Created internal timesheet — employee=%s, date=%s, hours=%.2f, desc=%r.',
            employee.name, date, hours, description,
        )

    # ------------------------------------------------------------------
    # Eligible employees
    # ------------------------------------------------------------------

    @api.model
    def _get_timesheet_eligible_employees(self, calendar=None):
        """
        Return hr.employee records whose active contract has
        ``attendance_based_on_timesheet = True``.

        Optionally filters to employees whose resource calendar matches
        *calendar* (used for public holidays tied to a specific schedule).

        :param calendar: resource.calendar record or None.
        :returns:        hr.employee recordset.
        """
        domain = [
            ('attendance_based_on_timesheet', '=', True),
            ('state', '=', 'open'),
        ]
        contracts = self.env['hr.contract'].sudo().search(domain)
        employees = contracts.mapped('employee_id')

        if calendar:
            employees = employees.filtered(
                lambda e: (
                    e.resource_calendar_id == calendar
                    or (
                        not e.resource_calendar_id
                        and e.company_id.resource_calendar_id == calendar
                    )
                )
            )

        return employees
