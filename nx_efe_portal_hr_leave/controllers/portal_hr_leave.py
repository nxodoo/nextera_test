# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError
from datetime import datetime
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT


class PortalHrLeaveController(http.Controller):
    """Controller class to handle HTTP routes."""

    @http.route(['/my/leaves', '/my/leaves/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_leaves(self, page=1, **kw):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        if employee:
            domain = [('employee_id', '=', employee.id)]
        else:
            domain = [('user_id', '=', user.id)]

        Leave = request.env['hr.leave'].sudo()
        leaves = Leave.search(domain, order='date_from desc', limit=50, offset=(page - 1) * 50)

        leave_types = request.env['hr.leave.type'].sudo().search([
            ('company_id', 'in', [employee.company_id.id if employee else False, False]),
            '|',
            ('requires_allocation', '=', 'no'),
            ('has_valid_allocation', '=', True),
        ])

        leave_balances = []
        for lt in leave_types:
            allocations = request.env['hr.leave.allocation'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate'),
                ('holiday_status_id', '=', lt.id)
            ])

            total_allocated = sum(allocations.mapped('number_of_days'))

            leaves_taken = request.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('holiday_status_id', '=', lt.id),
                ('state', 'in', ['confirm', 'validate', 'validate1'])
            ])
            total_taken = sum(leaves_taken.mapped('number_of_days'))

            remaining = total_allocated - total_taken

            leave_balances.append({
                'name': lt.name,
                'available_days': remaining if remaining > 0 else 0.0,
            })

        return request.render('nx_efe_portal_hr_leave.portal_my_leaves', {
            'leaves': leaves,
            'leave_balances': leave_balances,
            'page_name': 'portal_my_leaves',
        })

    @http.route(['/my/allocations', '/my/allocations/page/<int:page>'],
                type='http', auth="user", website=True)
    def portal_my_allocations(self, page=1, **kw):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        if not employee:
            return request.render('portal.portal_404')

        Allocation = request.env['hr.leave.allocation'].sudo()

        allocations = Allocation.search(
            [('employee_id', '=', employee.id)],
            order='create_date desc',
            limit=50,
            offset=(page - 1) * 50
        )

        return request.render(
            'nx_efe_portal_hr_leave.portal_my_allocations',
            {
                'allocations': allocations,
                'page_name': 'portal_my_allocations',
            }
        )

    @http.route(['/my/leaves/new'], type='http', auth="user", website=True, methods=['POST', 'GET'])
    def portal_new_leave(self, **post):
        """Allow the user to create a new leave request from the portal."""
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        # Render the leave creation form (GET request)
        if request.httprequest.method == 'GET':
            employee_company_id = employee.company_id.id if employee else False

            leave_types = request.env['hr.leave.type'].sudo().search([
                ('company_id', 'in', [employee_company_id, False]),
                '|',
                ('requires_allocation', '=', 'no'),
                ('has_valid_allocation', '=', True),
            ])

            return request.render('nx_efe_portal_hr_leave.portal_leave_form', {
                'employee': employee,
                'leave_types': leave_types,
                'page_name': 'portal_leave_form',
            })
        # Handle form submission (POST request)
        vals = {}
        leave_type_id = post.get('holiday_status_id')
        date_from = post.get('date_from')
        date_to = post.get('date_to')
        description = post.get('description') or ''

        if not employee:
            raise UserError(_("No employee record is linked to your user. Please contact the HR department."))

        if not leave_type_id:
            raise UserError(_("Please select a leave type."))

        vals['employee_id'] = employee.id
        vals['holiday_status_id'] = int(leave_type_id)
        vals['name'] = description or _('Leave Request from Portal')

        # Set duration by either date range or number of days
        if date_from and date_to:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d")
                date_to = datetime.strptime(date_to, "%Y-%m-%d")

                date_from = date_from.replace(hour=0, minute=0, second=0)
                date_to = date_to.replace(hour=23, minute=59, second=59)

                vals['request_date_from'] = date_from.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                vals['request_date_to'] = date_to.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            except Exception:
                raise UserError(_("Invalid date format. Please use DD/MM/YYYY"))

        else:
            raise UserError(_("Please provide either a date range or a number of days."))

        # Default state for new requests
        vals['state'] = 'confirm'
        vals['user_id'] = user.id

        leave = request.env['hr.leave'].sudo().create(vals)
        leave.generate_token()
        leave.send_leave_approval_mail()

        return request.redirect('/my/leaves')

    @http.route(['/my/allocations/new'], type='http', auth="user", website=True, methods=['GET', 'POST'])
    def portal_new_allocation(self, **post):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        if not employee:
            raise UserError(_("No employee linked to your user."))

        # Render the allocation creation form (GET request)
        if request.httprequest.method == 'GET':
            leave_types = request.env['hr.leave.type'].sudo().search([
                ('requires_allocation', '=', 'yes'),
                ('name', '=', 'Compensatory Days'),
                ('company_id', 'in', [employee.company_id.id, False]),
            ])
            return request.render('nx_efe_portal_hr_leave.portal_allocation_form', {
                'employee': employee,
                'leave_types': leave_types,
                'page_name': 'portal_allocation_form',
            })

        # Handle form submission (POST request)
        leave_type_id = post.get('holiday_status_id')
        number_of_days = post.get('number_of_days')
        date_from = post.get('date_from')
        date_to = post.get('date_to')
        reason = post.get('reason') or ''

        if not leave_type_id or not number_of_days:
            raise UserError(_("Please fill all required fields."))

        vals = {
            'employee_id': employee.id,
            'holiday_status_id': int(leave_type_id),
            'number_of_days': float(number_of_days),
            'notes': reason or _('Allocation Request from Portal'),
            'state': 'confirm',
        }

        if date_from or date_to:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d")
                date_to = datetime.strptime(date_to, "%Y-%m-%d")

                date_from = date_from.replace(hour=0, minute=0, second=0)
                date_to = date_to.replace(hour=23, minute=59, second=59)
            except Exception:
                raise UserError(_("Invalid date format. Please use DD/MM/YYYY"))

            vals.update({
                'alternative_date_from': date_from,
                'alternative_date_to': date_to,
            })

        allocation = request.env['hr.leave.allocation'].sudo().create(vals)
        allocation.generate_token()
        allocation.send_allocation_approval_mail()

        return request.redirect('/my/allocations')

    @http.route('/leave/approve/<int:leave_id>/<string:token>', type='http', auth="public", website=True)
    def approve_leave(self, leave_id, token, **kw):
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave or leave.approval_token != token:
            return "Invalid or expired link."

        if leave.state == 'confirm':
            leave.action_approve()
        elif leave.state == 'validate1':
            leave.action_validate()

        leave.approval_token = False

        return request.render("nx_efe_portal_hr_leave.approval_success", {
            'message': "Leave Approved Successfully",
        })

    @http.route('/leave/reject/<int:leave_id>/<string:token>', type='http', auth="public", website=True)
    def reject_leave(self, leave_id, token, **kw):
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not leave or leave.approval_token != token:
            return "Invalid or expired link."

        leave.action_refuse()
        leave.approval_token = False

        return request.render("nx_efe_portal_hr_leave.approval_success", {
            'message': "Leave Rejected",
        })

    @http.route(
        '/allocation/approve/<int:allocation_id>/<string:token>',
        type='http', auth='public', website=True
    )
    def approve_allocation(self, allocation_id, token, **kw):
        allocation = request.env['hr.leave.allocation'].sudo().browse(allocation_id)

        if not allocation or allocation.approval_token != token:
            return "Invalid or expired link."

        if allocation.state == 'confirm':
            allocation.action_approve()
        elif allocation.state == 'validate1':
            allocation.action_validate()

        allocation.approval_token = False

        return request.render(
            'nx_efe_portal_hr_leave.approval_success',
            {'message': "Allocation Approved Successfully"}
        )

    @http.route(
        '/allocation/reject/<int:allocation_id>/<string:token>',
        type='http', auth='public', website=True
    )
    def reject_allocation(self, allocation_id, token, **kw):
        allocation = request.env['hr.leave.allocation'].sudo().browse(allocation_id)

        if not allocation or allocation.approval_token != token:
            return "Invalid or expired link."

        allocation.action_refuse()
        allocation.approval_token = False

        return request.render(
            'nx_efe_portal_hr_leave.approval_success',
            {'message': "Allocation Rejected"}
        )
