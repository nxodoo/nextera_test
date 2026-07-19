# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
from odoo.tools import float_round
from odoo.addons.nx_efe_portal_hr_leave.controllers.portal_hr_leave import PortalHrLeaveController
from .helpers.leave_stats import build_leave_maps, get_leave_state_counts


class PortalHrLeaveInherit(PortalHrLeaveController):

    @http.route()
    def portal_my_leaves(self, page=1, **kw):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        if employee:
            domain = [('employee_id', '=', employee.id)]
        else:
            domain = [('user_id', '=', user.id)]

        Leave = request.env['hr.leave'].sudo()
        total_count = Leave.search_count(domain)

        leave_types = request.env['hr.leave.type'].sudo().search([
            ('company_id', 'in', [employee.company_id.id if employee else False, False]),
            '|',
            ('requires_allocation', '=', 'no'),
            ('has_valid_allocation', '=', True),
        ])

        # Hours per day for this employee (from resource calendar)
        hours_per_day = employee._get_hours_per_day(fields.Date.today()) if employee else 8.0

        # Prefetch allocations/taken grouped by leave type through helper for clarity.
        alloc_map, taken_map = build_leave_maps(request.env, employee.id if employee else False)

        leave_balances = []
        for lt in leave_types:
            total_allocated_days = float_round(
                alloc_map.get(lt.id, 0.0), precision_digits=2
            )
            total_taken_days = float_round(
                taken_map.get(lt.id, 0.0), precision_digits=2
            )

            remaining_days = max(total_allocated_days - total_taken_days, 0.0)
            remaining_hours = float_round(remaining_days * hours_per_day, precision_digits=2)
            total_allocated_hours = float_round(total_allocated_days * hours_per_day, precision_digits=2)
            total_taken_hours = float_round(total_taken_days * hours_per_day, precision_digits=2)

            # Percentage used for progress bar
            percentage_used = (
                round((total_taken_days / total_allocated_days) * 100)
                if total_allocated_days > 0 else 0
            )

            percentage_used_capped = min(percentage_used, 100)
            percentage_remaining = max(100 - percentage_used_capped, 0)

            # Accent (presentation token) computed here, not in QWeb.
            # Thresholds: >50% remaining => success, >20% => warning, else danger.
            if percentage_remaining > 50:
                accent = 'success'
            elif percentage_remaining > 20:
                accent = 'warning'
            else:
                accent = 'danger'

            leave_balances.append({
                'name': lt.name,
                'available_days': remaining_days,
                'available_hours': remaining_hours,
                'total_allocated_days': total_allocated_days,
                'total_allocated_hours': total_allocated_hours,
                'total_taken_days': total_taken_days,
                'total_taken_hours': total_taken_hours,
                'percentage_used': percentage_used_capped,
                'percentage_remaining': percentage_remaining,
                'accent': accent,
            })

        # Summary stats
        total_balance_days = sum(lb['available_days'] for lb in leave_balances)
        pending_count, approved_count = get_leave_state_counts(
            Leave,
            employee.id if employee else False,
        )

        return request.render('nx-analytics-widgets.nx_portal_my_leaves_override', {
            'total_balance_days': float_round(total_balance_days, precision_digits=2),
            'pending_count': pending_count,
            'approved_count': approved_count,
            'total_leave_count': total_count,
            'leave_balances': leave_balances,
            'page_name': 'portal_my_leaves',
        })
