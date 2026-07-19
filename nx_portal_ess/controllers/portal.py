# -*- coding: utf-8 -*-
import logging
from datetime import date

from odoo import http, fields
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)

# Leave states considered "pending approval"
LEAVE_PENDING = ('confirm', 'validate1')
LEAVE_APPROVED = ('validate',)


def _is_ess_mode():
    return bool(
        request and request.website
        and request.website.portal_mode == 'ess'
    )


def _employee():
    """Return the hr.employee linked to the current user (sudo), or empty."""
    return request.env.user.employee_id.sudo()


def _fmt_date(value):
    return fields.Date.to_string(value) if value else False


def _fmt_datetime(value):
    return fields.Datetime.to_string(value) if value else False


class EssPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Page entry point
    # ------------------------------------------------------------------
    @http.route(['/my/ess'], type='http', auth='user', website=True)
    def ess_home(self, **kw):
        return request.render('nx_portal_ess.ess_portal_page', {
            'page_name': 'ess',
        })

    # Redirect the default portal home to the ESS app when the mode is on.
    # Note: only /my/home is claimed here; /my is left to the sibling
    # warranty controller (which already redirects it to /my/home).
    @http.route(['/my/home'], type='http', auth='user', website=True)
    def home(self, **kw):
        if _is_ess_mode():
            return request.redirect('/my/ess')
        return super().home(**kw)

    # ==================================================================
    # JSON data endpoints (consumed by the OWL app)
    # ==================================================================
    @http.route('/my/ess/dashboard', type='json', auth='user', website=True)
    def ess_dashboard(self, **kw):
        emp = _employee()
        if not emp:
            return {'has_employee': False}

        env = request.env
        Leave = env['hr.leave'].sudo()
        pending_leaves = Leave.search_count([
            ('employee_id', '=', emp.id),
            ('state', 'in', LEAVE_PENDING),
        ])

        open_letters = env['hr.letter.request'].sudo().search_count([
            ('employee_id', '=', emp.id),
            ('state', 'in', ('draft', 'submitted', 'approved')),
        ])
        open_trips = env['hr.business.trip'].sudo().search_count([
            ('employee_id', '=', emp.id),
            ('state', 'in', ('draft', 'submitted', 'approved')),
        ])

        # Attendance rate for the current month
        attendance_rate = self._attendance_rate(emp)

        latest_payslip_label = False
        if 'hr.payslip' in env:
            slip = env['hr.payslip'].sudo().search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ('done', 'paid', 'verify')),
            ], order='date_to desc', limit=1)
            if slip and slip.date_to:
                latest_payslip_label = slip.date_to.strftime('%B %Y')

        return {
            'has_employee': True,
            'employee': self._employee_card(emp),
            'kpis': {
                'pending_approvals': pending_leaves,
                'open_requests': open_letters + open_trips,
                'attendance_rate': attendance_rate,
                'latest_payslip': latest_payslip_label,
            },
            'recent_requests': self._recent_requests(emp),
        }

    @http.route('/my/ess/leaves', type='json', auth='user', website=True)
    def ess_leaves(self, **kw):
        emp = _employee()
        if not emp:
            return {'has_employee': False}
        env = request.env
        leaves = env['hr.leave'].sudo().search(
            [('employee_id', '=', emp.id)], order='request_date_from desc', limit=100)
        allocations = env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', emp.id),
            ('state', '=', 'validate'),
        ])
        balances = {}
        for alloc in allocations:
            key = alloc.holiday_status_id.id
            entry = balances.setdefault(key, {
                'type_id': key,
                'name': alloc.holiday_status_id.name,
                'allocated': 0.0,
                'taken': 0.0,
            })
            entry['allocated'] += alloc.number_of_days
        for lv in leaves:
            if lv.state == 'validate' and lv.holiday_status_id.id in balances:
                balances[lv.holiday_status_id.id]['taken'] += lv.number_of_days
        for b in balances.values():
            b['remaining'] = round(b['allocated'] - b['taken'], 2)

        leave_types = [{
            'id': t.id, 'name': t.name,
        } for t in env['hr.leave.type'].sudo().search([])]

        return {
            'has_employee': True,
            'balances': list(balances.values()),
            'leave_types': leave_types,
            'leaves': [{
                'id': lv.id,
                'name': lv.holiday_status_id.name,
                'description': lv.name,
                'date_from': _fmt_date(lv.request_date_from),
                'date_to': _fmt_date(lv.request_date_to),
                'days': lv.number_of_days,
                'state': lv.state,
                'state_label': dict(
                    lv._fields['state'].selection).get(lv.state, lv.state),
            } for lv in leaves],
        }

    @http.route('/my/ess/leave/create', type='json', auth='user', website=True)
    def ess_leave_create(self, leave_type_id=None, date_from=None,
                         date_to=None, name=None, **kw):
        emp = _employee()
        if not emp:
            return {'ok': False, 'error': 'No employee linked to your account.'}
        if not (leave_type_id and date_from and date_to):
            return {'ok': False, 'error': 'Please fill in all required fields.'}
        try:
            leave = request.env['hr.leave'].sudo().create({
                'employee_id': emp.id,
                'holiday_status_id': int(leave_type_id),
                'request_date_from': date_from,
                'request_date_to': date_to,
                'name': name or 'Leave request',
            })
            leave.action_confirm() if hasattr(leave, 'action_confirm') else None
            return {'ok': True, 'id': leave.id}
        except Exception as exc:
            _logger.exception('ESS leave create failed')
            return {'ok': False, 'error': str(exc)}

    @http.route('/my/ess/attendance', type='json', auth='user', website=True)
    def ess_attendance(self, **kw):
        emp = _employee()
        if not emp:
            return {'has_employee': False}
        records = request.env['hr.attendance'].sudo().search(
            [('employee_id', '=', emp.id)], order='check_in desc', limit=60)
        total_hours = sum(r.worked_hours for r in records)
        return {
            'has_employee': True,
            'summary': {
                'count': len(records),
                'total_hours': round(total_hours, 2),
                'avg_hours': round(total_hours / len(records), 2) if records else 0.0,
            },
            'records': [{
                'id': r.id,
                'check_in': _fmt_datetime(r.check_in),
                'check_out': _fmt_datetime(r.check_out),
                'worked_hours': round(r.worked_hours, 2),
            } for r in records],
        }

    @http.route('/my/ess/payslips', type='json', auth='user', website=True)
    def ess_payslips(self, **kw):
        emp = _employee()
        if not emp:
            return {'has_employee': False}
        if 'hr.payslip' not in request.env:
            return {'has_employee': True, 'payroll_available': False, 'payslips': []}
        slips = request.env['hr.payslip'].sudo().search(
            [('employee_id', '=', emp.id)], order='date_to desc', limit=48)
        return {
            'has_employee': True,
            'payslips': [{
                'id': s.id,
                'number': s.number or s.name,
                'period': (s.date_from and s.date_to)
                and '%s - %s' % (_fmt_date(s.date_from), _fmt_date(s.date_to))
                or '',
                'date_to': _fmt_date(s.date_to),
                'net_wage': round(s.net_wage, 2),
                'basic_wage': round(s.basic_wage, 2),
                'currency': s.company_id.currency_id.symbol or '',
                'state': s.state,
            } for s in slips],
        }

    @http.route('/my/ess/payslip/<int:slip_id>', type='json', auth='user', website=True)
    def ess_payslip_detail(self, slip_id, **kw):
        emp = _employee()
        if 'hr.payslip' not in request.env:
            return {'ok': False, 'error': 'Payroll is not installed.'}
        slip = request.env['hr.payslip'].sudo().browse(slip_id)
        if not slip.exists() or slip.employee_id != emp:
            return {'ok': False, 'error': 'Payslip not found.'}
        return {
            'ok': True,
            'number': slip.number or slip.name,
            'period': '%s - %s' % (_fmt_date(slip.date_from), _fmt_date(slip.date_to)),
            'currency': slip.company_id.currency_id.symbol or '',
            'lines': [{
                'code': line.code,
                'name': line.name,
                'total': round(line.total, 2),
            } for line in slip.line_ids],
        }

    @http.route('/my/ess/letters', type='json', auth='user', website=True)
    def ess_letters(self, **kw):
        emp = _employee()
        if not emp:
            return {'has_employee': False}
        model = request.env['hr.letter.request'].sudo()
        letters = model.search([('employee_id', '=', emp.id)])
        return {
            'has_employee': True,
            'letter_types': [
                {'value': v, 'label': l}
                for v, l in model._fields['letter_type'].selection
            ],
            'letters': [{
                'id': r.id,
                'name': r.name,
                'letter_type': dict(
                    model._fields['letter_type'].selection).get(r.letter_type),
                'addressed_to': r.addressed_to or '',
                'request_date': _fmt_date(r.request_date),
                'state': r.state,
                'state_label': dict(
                    model._fields['state'].selection).get(r.state),
            } for r in letters],
        }

    @http.route('/my/ess/letter/create', type='json', auth='user', website=True)
    def ess_letter_create(self, letter_type=None, addressed_to=None,
                          reason=None, **kw):
        emp = _employee()
        if not emp:
            return {'ok': False, 'error': 'No employee linked to your account.'}
        if not letter_type:
            return {'ok': False, 'error': 'Please choose a letter type.'}
        try:
            rec = request.env['hr.letter.request'].sudo().create({
                'employee_id': emp.id,
                'letter_type': letter_type,
                'addressed_to': addressed_to or False,
                'reason': reason or False,
                'state': 'submitted',
            })
            return {'ok': True, 'id': rec.id}
        except Exception as exc:
            _logger.exception('ESS letter create failed')
            return {'ok': False, 'error': str(exc)}

    @http.route('/my/ess/trips', type='json', auth='user', website=True)
    def ess_trips(self, **kw):
        emp = _employee()
        if not emp:
            return {'has_employee': False}
        model = request.env['hr.business.trip'].sudo()
        trips = model.search([('employee_id', '=', emp.id)])
        return {
            'has_employee': True,
            'trips': [{
                'id': t.id,
                'name': t.name,
                'destination': t.destination,
                'purpose': t.purpose or '',
                'date_from': _fmt_date(t.date_from),
                'date_to': _fmt_date(t.date_to),
                'duration': t.duration,
                'estimated_cost': round(t.estimated_cost, 2),
                'currency': t.currency_id.symbol or '',
                'state': t.state,
                'state_label': dict(
                    model._fields['state'].selection).get(t.state),
            } for t in trips],
        }

    @http.route('/my/ess/trip/create', type='json', auth='user', website=True)
    def ess_trip_create(self, destination=None, purpose=None, date_from=None,
                        date_to=None, estimated_cost=None, **kw):
        emp = _employee()
        if not emp:
            return {'ok': False, 'error': 'No employee linked to your account.'}
        if not (destination and date_from and date_to):
            return {'ok': False, 'error': 'Please fill in all required fields.'}
        try:
            rec = request.env['hr.business.trip'].sudo().create({
                'employee_id': emp.id,
                'destination': destination,
                'purpose': purpose or False,
                'date_from': date_from,
                'date_to': date_to,
                'estimated_cost': float(estimated_cost or 0.0),
                'state': 'submitted',
            })
            return {'ok': True, 'id': rec.id}
        except Exception as exc:
            _logger.exception('ESS trip create failed')
            return {'ok': False, 'error': str(exc)}

    # ==================================================================
    # Helpers
    # ==================================================================
    def _employee_card(self, emp):
        return {
            'id': emp.id,
            'name': emp.name,
            'job_title': emp.job_title or (emp.job_id.name if emp.job_id else ''),
            'department': emp.department_id.name if emp.department_id else '',
            'manager': emp.parent_id.name if emp.parent_id else '',
            'work_location': emp.work_location_id.name if emp.work_location_id else '',
            'employee_number': emp.barcode or emp.registration_number or '',
            'avatar': '/web/image/hr.employee/%s/avatar_256' % emp.id,
        }

    def _attendance_rate(self, emp):
        today = date.today()
        month_start = today.replace(day=1)
        atts = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', emp.id),
            ('check_in', '>=', fields.Datetime.to_string(
                fields.Datetime.now().replace(
                    year=month_start.year, month=month_start.month, day=1,
                    hour=0, minute=0, second=0))),
        ])
        present_days = len({a.check_in.date() for a in atts if a.check_in})
        # working days elapsed so far this month (Mon-Fri)
        elapsed = 0
        d = month_start
        while d <= today:
            if d.weekday() < 5:
                elapsed += 1
            d = date.fromordinal(d.toordinal() + 1)
        if not elapsed:
            return 0
        return min(100, round(present_days / elapsed * 100))

    def _recent_requests(self, emp):
        rows = []
        env = request.env
        for lv in env['hr.leave'].sudo().search(
                [('employee_id', '=', emp.id)],
                order='create_date desc', limit=5):
            rows.append({
                'ref': 'LV-%s' % lv.id,
                'type': lv.holiday_status_id.name or 'Leave',
                'date': (lv.request_date_from and lv.request_date_to)
                        and '%s - %s' % (_fmt_date(lv.request_date_from),
                                         _fmt_date(lv.request_date_to)) or '',
                'submitted': _fmt_date(lv.create_date),
                'state': lv.state,
                'state_label': dict(lv._fields['state'].selection).get(lv.state),
            })
        for r in env['hr.letter.request'].sudo().search(
                [('employee_id', '=', emp.id)], order='create_date desc', limit=5):
            rows.append({
                'ref': r.name,
                'type': dict(r._fields['letter_type'].selection).get(r.letter_type),
                'date': _fmt_date(r.request_date),
                'submitted': _fmt_date(r.create_date),
                'state': r.state,
                'state_label': dict(r._fields['state'].selection).get(r.state),
            })
        for t in env['hr.business.trip'].sudo().search(
                [('employee_id', '=', emp.id)], order='create_date desc', limit=5):
            rows.append({
                'ref': t.name,
                'type': 'Business Trip',
                'date': (t.date_from and t.date_to)
                        and '%s - %s' % (_fmt_date(t.date_from), _fmt_date(t.date_to)) or '',
                'submitted': _fmt_date(t.create_date),
                'state': t.state,
                'state_label': dict(t._fields['state'].selection).get(t.state),
            })
        rows.sort(key=lambda x: x['submitted'] or '', reverse=True)
        return rows[:8]
