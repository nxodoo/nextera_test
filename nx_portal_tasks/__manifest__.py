# -*- coding: utf-8 -*-
{
    'name': 'Portal Tasks',
    'version': '1.0',
    'summary': 'Portal menu to manage tasks and timesheets',
    'category': 'Project',
    'author': 'Sayed Anwar',
    'company': 'Nextera MEA',
    'depends': [
        'base',
        'website',
        'portal',
        'project',
        'hr_timesheet',
    ],
    'data': [
        'views/portal_templates.xml',
		'views/portal_menu.xml',
		'views/close_task_template.xml',
],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
