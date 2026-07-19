# -*- coding: utf-8 -*-
"""
Automatically create Internal Project timesheet entries for public holidays
represented by generic resource calendar leaves.
"""
from datetime import timedelta

from odoo import models, _


class ResourceCalendarLeaves(models.Model):
    """
    Extends resource.calendar.leaves to create internal timesheets for
    timesheet-based employees when public holidays are created or updated.
    """

    _name = 'resource.calendar.leaves'
    _inherit = ['resource.calendar.leaves', 'nx.timesheet.internal.mixin']

    def create(self, vals_list):
        leaves = super().create(vals_list)
        leaves._sync_public_holiday_internal_timesheets()
        return leaves

    def write(self, vals):
        result = super().write(vals)
        tracked_fields = {'name', 'date_from', 'date_to', 'calendar_id', 'resource_id', 'time_type'}
        if tracked_fields.intersection(vals):
            self._sync_public_holiday_internal_timesheets()
        return result

    def _sync_public_holiday_internal_timesheets(self):
        """
        Create one Internal Project timesheet per employee and per working day
        for generic calendar leaves that act as public holidays.
        """
        for leave in self.filtered(self._is_public_holiday_candidate):
            leave._create_public_holiday_timesheets()

    def _is_public_holiday_candidate(self, leave):
        """
        Return whether the calendar leave should be treated like a public holiday.
        """
        return (
            not leave.resource_id
            and leave.time_type == 'leave'
            and leave.calendar_id
            and leave.date_from
            and leave.date_to
        )

    def _create_public_holiday_timesheets(self):
        """
        Create Internal Project timesheets for every eligible employee affected
        by the holiday calendar.
        """
        self.ensure_one()

        employees = self._get_timesheet_eligible_employees(calendar=self.calendar_id)
        if not employees:
            return

        description = self.name or _('Public Holiday')
        current = self.date_from.date()
        date_to = self.date_to.date()

        while current <= date_to:
            for employee in employees:
                hours = self._get_employee_hours_per_day(employee, current)
                if hours > 0:
                    self._create_internal_timesheet(
                        employee=employee,
                        date=current,
                        description=description,
                        hours=hours,
                    )
            current += timedelta(days=1)
