# -*- coding: utf-8 -*-
"""
Automatically create Internal Project timesheet entries when a leave is
validated for an employee whose contract has ``attendance_based_on_timesheet``.
"""
import logging
from datetime import timedelta

from odoo import api, models, _

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    """
    Extends hr.leave to trigger internal timesheet creation on validation.

    One timesheet line per working day is created inside the Internal Project
    with the leave type as description and the employee's scheduled hours as
    the duration.
    """

    _name = 'hr.leave'
    _inherit = ['hr.leave', 'nx.timesheet.internal.mixin']

    # ------------------------------------------------------------------
    # Override
    # ------------------------------------------------------------------

    def action_validate(self, check_state=True):
        result = super().action_validate(check_state=check_state)
        # After super, validated leaves are in state='validate'.
        for leave in self.filtered(lambda l: l.state == 'validate'):
            leave._sync_leave_internal_timesheet()
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sync_leave_internal_timesheet(self):
        """
        Create an internal timesheet for every working day within the leave.

        Only runs when the employee has an active contract with
        ``attendance_based_on_timesheet = True``.
        """
        self.ensure_one()

        employee = self.employee_id
        if not employee:
            return

        # Only process employees with the flag enabled on their active contract.
        has_flag = self.env['hr.contract'].sudo().search_count([
            ('employee_id', '=', employee.id),
            ('attendance_based_on_timesheet', '=', True),
            ('state', '=', 'open'),
        ])
        if not has_flag:
            return

        leave_type_name = self.holiday_status_id.name or _('Leave')
        date_from = self.date_from.date()
        date_to = self.date_to.date()

        _logger.info(
            'nx_payroll_timesheet_work_entry: '
            'Processing leave "%s" for %s [%s → %s].',
            leave_type_name, employee.name, date_from, date_to,
        )

        current = date_from
        while current <= date_to:
            hours = self._get_employee_hours_per_day(employee, current)
            if hours > 0:
                self._create_internal_timesheet(
                    employee=employee,
                    date=current,
                    description=leave_type_name,
                    hours=hours,
                )
            current += timedelta(days=1)
