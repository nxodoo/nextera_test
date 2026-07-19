# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class PortalTaskController(http.Controller):

    # -----------------------------
    # List Open Tasks
    # -----------------------------
    @http.route('/my/open-tasks', type='http', auth='user', website=True)
    def portal_open_tasks(self, **kw):
        user = request.env.user

        tasks = request.env['project.task'].sudo().search([
            ('user_ids', '=', user.id),
            ('stage_id.fold', '=', False),
            ('state', 'not in', ['1_done','1_canceled']),
        ])

        return request.render(
            'nx_portal_tasks.portal_open_tasks_list',
            {
                'tasks': tasks,
                'page_name': 'portal_my_tasks_edit',
            }
        )

    # -----------------------------
    # List Close Tasks
    # -----------------------------
    @http.route('/my/close-tasks', type='http', auth='user', website=True)
    def portal_close_tasks(self, **kw):
        user = request.env.user

        tasks = request.env['project.task'].sudo().search([
            ('user_ids', '=', user.id),
            ('stage_id.fold', '=', False),
            ('state', 'in', ['1_done','1_canceled']),
        ])

        return request.render(
            'nx_portal_tasks.portal_close_tasks_list',
            {
                'tasks': tasks,
                'page_name': 'portal_my_tasks_close',
            }
        )

    # -----------------------------
    # Task Details
    # -----------------------------
    @http.route('/my/open-task/<int:task_id>', type='http', auth='user', website=True)
    def portal_task_form(self, task_id, **kw):
        task = request.env['project.task'].sudo().browse(task_id)

        # Security check
        if request.env.user.id not in task.user_ids.ids:
            return request.redirect('/my')

        timesheets = request.env['account.analytic.line'].sudo().search([
            ('task_id', '=', task.id)
        ])

        return request.render(
            'nx_portal_tasks.portal_task_form',
            {
                'task': task,
                'timesheets': timesheets,
                'page_name': 'portal_task_form_edit',
            }
        )
    @http.route('/my/close-task/<int:task_id>', type='http', auth='user', website=True)
    def portal_task_close_form(self, task_id, **kw):
        task = request.env['project.task'].sudo().browse(task_id)

        # Security check
        if request.env.user.id not in task.user_ids.ids:
            return request.redirect('/my')

        timesheets = request.env['account.analytic.line'].sudo().search([
            ('task_id', '=', task.id)
        ])

        return request.render(
            'nx_portal_tasks.portal_close_task_form',
            {
                'task': task,
                'timesheets': timesheets,
                'page_name': 'portal_task_form_close',
            }
        )

    # -----------------------------
    # Add Timesheet
    # -----------------------------
    @http.route(
        '/my/task/timesheet/add',
        type='http',
        auth='user',
        methods=['POST'],
        website=True
    )
    def add_timesheet(self, **post):
        task = request.env['project.task'].sudo().browse(
            int(post.get('task_id'))
        )

        # Security check
        if request.env.user.id not in task.user_ids.ids:
            return request.redirect('/my')

        unit_amount = post.get('unit_amount') or 0
        try:
            unit_amount = float(unit_amount)
        except ValueError:
            unit_amount = 0

        employee = request.env.user.employee_id.id if request.env.user.employee_id else False

        request.env['account.analytic.line'].sudo().create({
            'name': post.get('name') or '',
            'unit_amount': unit_amount,
            'task_id': task.id,
            'project_id': task.project_id.id,
            'employee_id': employee,
            'date': post.get('date') or '',
        })

        return request.redirect('/my/open-task/%s' % task.id)
