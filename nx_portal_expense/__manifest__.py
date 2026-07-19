# -*- coding: utf-8 -*-
{
    'name': 'Portal Expense',
    'version': '1.0',
    'author': 'Sayed Anwar',
    'company': 'Nextera MEA',
    'depends': ['base', 'hr_expense'],
    'data': [
		'views/portal_menu.xml',
		'views/portal_my_expenses.xml',
		'views/portal_expense_templates.xml',
		'views/breadcrumbs.xml',
],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}