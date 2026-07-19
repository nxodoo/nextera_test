# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import AccessError


class PortalExpenseController(http.Controller):

    @http.route('/my/expenses/new', type='http', auth='user', website=True)
    def portal_new_expense(self, **kw):
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )

        categories = request.env['product.product'].sudo().search([('can_be_expensed', '=', True)])
        currencies = request.env['res.currency'].sudo().search([])
        taxes = request.env['account.tax'].sudo().search([
            ('type_tax_use', '=', 'purchase')
        ])
        accounts = request.env['account.account'].sudo().search([
            ('deprecated', '=', False)
        ])
        vendors = request.env['res.partner'].sudo().search([
            ('supplier_rank', '>', 0)
        ])

        return request.render('nx_portal_expense.portal_expense_form', {
            'employee': employee,
            'categories': categories,
            'today': fields.Date.today(),
            'vendors': vendors,
            'accounts': accounts,
            'taxes': taxes,
            'currencies': currencies,
            'page_name': 'portal_expense_form',
        })

    @http.route('/my/expenses/create', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_create_expense(self, **post):
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )

        tax_ids = request.httprequest.form.getlist('tax_ids')
        tax_ids = [int(tid) for tid in tax_ids if tid]

        expense_vals = {
            'name': post.get('description'),
            'product_id': int(post.get('product_id')),
            'total_amount': float(post.get('amount')),
            'date': post.get('date'),
            'currency_id': int(post.get('currency_id')),
            'tax_ids': [(6, 0, tax_ids)] if tax_ids else False,
            'account_id': int(post.get('account_id')) if post.get('account_id') else False,
            'payment_mode': post.get('payment_mode'),
            'employee_id': employee.id,
        }

        if post.get('vendor_id'):
            expense_vals['vendor_id'] = int(post.get('vendor_id'))

        expense = request.env['hr.expense'].sudo().create(expense_vals)

        return request.redirect('/my/expenses')

    @http.route('/my/expenses/edit/<int:expense_id>', type='http', auth='user', website=True)
    def portal_edit_expense(self, expense_id, **kw):
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )

        expense = request.env['hr.expense'].sudo().search([
            ('id', '=', expense_id),
            ('employee_id', '=', employee.id)
        ], limit=1)

        if not expense:
            return request.redirect('/my/expenses')

        categories = request.env['product.product'].sudo().search([('can_be_expensed', '=', True)])
        currencies = request.env['res.currency'].sudo().search([])
        taxes = request.env['account.tax'].sudo().search([
            ('type_tax_use', '=', 'purchase')
        ])
        accounts = request.env['account.account'].sudo().search([
            ('deprecated', '=', False)
        ])
        vendors = request.env['res.partner'].sudo().search([
            ('supplier_rank', '>', 0)
        ])

        return request.render('nx_portal_expense.portal_expense_edit_form', {
            'expense': expense,
            'employee': employee,
            'categories': categories,
            'currencies': currencies,
            'taxes': taxes,
            'accounts': accounts,
            'vendors': vendors,
            'page_name': 'portal_expense_edit_form',
        })

    @http.route('/my/expenses/update/<int:expense_id>', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_update_expense(self, expense_id, **post):
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )

        expense = request.env['hr.expense'].sudo().search([
            ('id', '=', expense_id),
            ('employee_id', '=', employee.id),
            ('state', '=', 'draft')
        ], limit=1)

        if not expense:
            return request.redirect('/my/expenses')

        tax_ids = request.httprequest.form.getlist('tax_ids')
        tax_ids = [int(tid) for tid in tax_ids if tid]

        expense_vals = {
            'name': post.get('description'),
            'product_id': int(post.get('product_id')),
            'total_amount': float(post.get('amount')),
            'date': post.get('date'),
            'currency_id': int(post.get('currency_id')),
            'tax_ids': [(6, 0, tax_ids)] if tax_ids else [(5, 0, 0)],
            'account_id': int(post.get('account_id')) if post.get('account_id') else False,
            'payment_mode': post.get('payment_mode'),
        }

        if post.get('vendor_id'):
            expense_vals['vendor_id'] = int(post.get('vendor_id'))
        else:
            expense_vals['vendor_id'] = False

        expense.write(expense_vals)

        return request.redirect('/my/expenses')

    @http.route('/my/expenses/view/<int:expense_id>', type='http', auth='user', website=True)
    def portal_view_expense(self, expense_id, **kw):
        """View expense details (read-only)"""
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )

        expense = request.env['hr.expense'].sudo().search([
            ('id', '=', expense_id),
            ('employee_id', '=', employee.id)
        ], limit=1)

        if not expense:
            return request.redirect('/my/expenses')

        return request.render('nx_portal_expense.portal_expense_view', {
            'expense': expense,
            'page_name': 'portal_expense_view',
        })

    @http.route('/my/expenses', type='http', auth='user', website=True)
    def portal_my_expenses(self, **kw):
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )

        expenses = request.env['hr.expense'].sudo().search([
            ('employee_id', '=', employee.id)
        ], order='date desc')

        return request.render('nx_portal_expense.portal_my_expenses', {
            'expenses': expenses,
            'page_name': 'portal_my_expenses',
        })