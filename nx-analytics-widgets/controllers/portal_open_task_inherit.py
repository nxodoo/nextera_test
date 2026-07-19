# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.nx_portal_tasks.controllers.portal_task import PortalTaskController


class PortalTaskInherit(PortalTaskController):

    @http.route()
    def portal_open_tasks(self, page=1, **kw):
        # Analytics data (project cards, flow chart, line chart)
        # is now fetched client-side by the OWL TaskDashboardApp component.

        return request.render(
            'nx-analytics-widgets.nx_portal_open_tasks_list_override',
            {
                'page_name': 'portal_my_tasks_edit',
            }
        )
