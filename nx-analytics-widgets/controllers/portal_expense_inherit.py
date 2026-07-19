# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.nx_portal_expense.controllers.portal_expense import PortalExpenseController


class PortalExpenseInherit(PortalExpenseController):

    @http.route()
    def portal_my_expenses(self, **kw):
        return request.render('nx-analytics-widgets.nx_portal_my_expenses_override', {
            'page_name': 'portal_my_expenses',
        })
