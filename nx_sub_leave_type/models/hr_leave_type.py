# -*- coding: utf-8 -*-
import logging

from odoo import models, api

_logger = logging.getLogger(__name__)


class HrLeaveType(models.Model):
    """Extends hr.leave.type to inject sub leave data into the dashboard response."""

    _inherit = 'hr.leave.type'

    @api.model
    def get_allocation_data_request(self, target_date=None, hidden_allocations=True):
        """Override to append sub leave info to each parent leave type's data dict.

        The dashboard card for a leave type (e.g. Annual Leave) will receive
        additional keys — sub_leave_type_name, sub_leave_remaining,
        sub_leave_limit, max_days_per_request — when a validated allocation
        exists that links it to a sub leave type for the current employee.

        Returns:
            list: Same structure as super(), with sub leave keys merged into
                  the data dict of matching leave types.
        """
        result = super().get_allocation_data_request(target_date, hidden_allocations)

        if not result:
            return result

        employee = self.env['hr.employee']._get_contextual_employee()
        if not employee:
            return result

        allocations = self.env['hr.leave.allocation'].search([
            ('employee_id', '=', employee.id),
            ('sub_leave_type_id', '!=', False),
            ('state', '=', 'validate'),
        ])

        if not allocations:
            return result

        # Map: parent leave type id → sub leave info
        sub_leave_map = {
            alloc.holiday_status_id.id: {
                'sub_leave_type_name': alloc.sub_leave_type_id.name,
                'sub_leave_remaining': alloc.sub_leave_remaining_days,
                'sub_leave_limit': alloc.sub_leave_days_limit,
                'max_days_per_request': alloc.max_days_per_request,
            }
            for alloc in allocations
        }

        # Inject into matching card data dicts (item[1] is the mutable data dict)
        for item in result:
            leave_type_id = item[3]
            if leave_type_id in sub_leave_map:
                item[1].update(sub_leave_map[leave_type_id])
                _logger.debug(
                    'Sub leave info injected into dashboard card for leave type %s',
                    leave_type_id,
                )

        return result
