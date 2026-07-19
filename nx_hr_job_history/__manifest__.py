# -*- coding: utf-8 -*-
{
    'name': 'NX Hr Job History',
    'version': '1.0',
    'description': """
NX HR Job History
=================
This module provides a structured way to manage employee job history within Odoo.

Features:
---------
- Track employee job titles over time
- Record employment periods (start and end dates)
- Manage salary history with multi-currency support
- Display job history directly in employee form
- Inline editing for better user experience

Business Benefits:
------------------
- Full visibility on employee career progression
- Better HR decision-making
- Centralized employee historical data
    """,
    'author': 'Alaa Galal Mohamed',
    'company': 'Nextera MEA',
    'depends': ['base', 'mail', 'hr', 'nx_nextera_base'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_employee_view.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
