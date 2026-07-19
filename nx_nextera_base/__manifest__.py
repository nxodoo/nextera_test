# -*- coding: utf-8 -*-
{
    'name': 'Nx Nextera Base',
    'version': '1.0',
    'summary': 'Reusable UI components and section toggle widget for Nextera modules',
    'description': """
Nextera Base UI Framework

This module provides reusable frontend components to enhance the user interface
across all Nextera custom modules.

Main Features:
- Section Toggle Widget (collapsible UI sections)
- Dynamic section metadata (title, icon, color)
- Smooth animations and modern UI styling
- OWL-based reusable components
- SCSS styling for consistent design

This module serves as a base dependency for other Nextera modules.
    """,
    'author': 'Alaa Galal Mohamed',
    'company': 'Nextera Mea',
    'depends': ['base', 'mail', 'hr'],
    'data': ['views/hr_employee_view.xml', ],
    'assets': {
        'web.assets_backend': [
            'nx_nextera_base/static/src/js/section_toggle_widget.js',
            'nx_nextera_base/static/src/xml/section_toggle_widget.xml',
            'nx_nextera_base/static/src/scss/career_section.scss',

        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
