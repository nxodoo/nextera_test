# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request


class PositionOrgChartController(http.Controller):

    def _get_company_domain(self):
        allowed_company_ids = request.env.context.get('allowed_company_ids') or [request.env.company.id]
        return ['|', ('company_id', '=', False), ('company_id', 'in', allowed_company_ids)]

    def _prepare_employee_map(self, jobs):
        employees = request.env['hr.employee'].sudo().search([
            ('active', '=', True),
            ('job_id', 'in', jobs.ids),
        ])
        employees_by_job = {}
        for employee in employees:
            employees_by_job.setdefault(employee.job_id.id, []).append({
                'id': employee.id,
                'name': employee.name,
                'work_email': employee.work_email or '',
                'avatar_url': '/web/image/hr.employee.public/%s/avatar_128' % employee.id,
            })
        return employees_by_job

    def _job_to_node(self, job, children_by_parent, employees_by_job, filters):
        employees = employees_by_job.get(job.id, [])
        assigned_count = len(employees)
        status = 'filled' if job.headcount and assigned_count >= job.headcount else 'vacant'
        assistant_children = []
        regular_children = []
        if not job.is_assistant_position:
            children = [
                self._job_to_node(child, children_by_parent, employees_by_job, filters)
                for child in children_by_parent.get(job.id, request.env['hr.job'])
            ]
            children = [child for child in children if child]
            assistant_children = [child for child in children if child.get('is_assistant')]
            regular_children = [child for child in children if not child.get('is_assistant')]

        show_vacant = filters.get('show_vacant', True)
        if not assistant_children and not regular_children and status == 'vacant' and not show_vacant:
            return False

        return {
            'id': job.id,
            'name': job.name,
            'is_assistant': job.is_assistant_position,
            'department_id': job.department_id.id,
            'department_name': job.department_id.name or '',
            'level': job.position_level_id.id,
            'level_name': job.position_level_id.name or '',
            'status': status,
            'headcount': job.headcount,
            'assigned_count': assigned_count,
            'target_count': job.no_of_recruitment,
            'vacancy_count': max(job.headcount - assigned_count, 0),
            'employees': employees,
            'assistant_children': assistant_children,
            'children': regular_children,
        }

    @http.route('/nx_hr_position_hierarchy/options', type='json', auth='user')
    def get_options(self):
        request.env['hr.job'].check_access('read')
        departments = request.env['hr.department'].sudo().search(self._get_company_domain(), order='name')
        levels = request.env['hr.position.level'].sudo().search([], order='sequence, name')
        return {
            'departments': [{'id': department.id, 'name': department.name} for department in departments],
            'levels': [{'id': level.id, 'name': level.name} for level in levels],
        }

    @http.route('/nx_hr_position_hierarchy/chart', type='json', auth='user')
    def get_chart(self, department_id=False, level=False, show_vacant=True, root_job_id=False):
        request.env['hr.job'].check_access('read')
        domain = self._get_company_domain()
        if department_id:
            domain.append(('department_id', '=', int(department_id)))
        if level:
            domain.append(('position_level_id', '=', int(level)))
        if root_job_id:
            domain.append(('id', 'child_of', int(root_job_id)))

        jobs = request.env['hr.job'].sudo().search(domain, order='position_level_sequence, sequence, name')
        employees_by_job = self._prepare_employee_map(jobs)
        children_by_parent = {}
        job_ids = set(jobs.ids)
        roots = request.env['hr.job']
        for job in jobs:
            if job.parent_id and job.parent_id.id in job_ids:
                children_by_parent.setdefault(job.parent_id.id, request.env['hr.job'])
                children_by_parent[job.parent_id.id] |= job
            else:
                roots |= job

        filters = {'show_vacant': show_vacant}
        nodes = [
            self._job_to_node(job, children_by_parent, employees_by_job, filters)
            for job in roots
        ]
        nodes = [node for node in nodes if node]
        return {
            'nodes': nodes,
            'summary': {
                'positions': len(jobs),
                'filled': sum(1 for job in jobs if job.position_status == 'filled'),
                'vacant': sum(1 for job in jobs if job.position_status == 'vacant'),
            },
        }
