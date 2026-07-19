# -*- coding: utf-8 -*-
{
    'name': 'NXPortal Analytics Widgets',
    'version': '1.0.0',
    'summary': 'Modern portal analytics widgets with shadcn/ui-inspired sidebar navigation and customizable dashboard cards',
    'description': """
                                                                                               NXPortal Analytics Widgets
                                                                                               ============================

                                                                                               A powerful Odoo portal enhancement module that replaces the default My Account layout
                                                                                               with a modern, analytics-focused experience.

                                                                                               Key Features:
                                                                                               -------------
                                                                                               - shadcn/ui-inspired sidebar navigation replacing default portal cards
                                                                                               - Customizable analytics dashboard widgets
                                                                                               - Grouped navigation with icons for a clean, organized portal
                                                                                               - Mobile-friendly offcanvas sidebar support
                                                                                               - Fully configurable sidebar groups and items from the backend
                                                                                               - Seamless integration with Tasks, Expenses, and HR Leave portal modules
                                                                                               - Minimal and modern design system

                                                                                               This module integrates with nx_portal_tasks, nx_portal_expense, and nx_efe_portal_hr_leave
                                                                                               to provide a unified and consistent portal experience for end users.
                                                                                                   """,
    'author': 'Hisham Megahed',
    'company': 'Nextera MEA',
    'category': 'Website',
    'license': 'LGPL-3',
    'depends': ['portal', "nx_portal_tasks", "nx_portal_expense", "nx_efe_portal_hr_leave", "portal_my_tabs"],
    'data': [
        "views/portal_breadcrumbs.xml",
        "views/portal_leave_templates.xml",
        "views/portal_open_task.xml",
        "views/portal_expense_templates.xml",
    ],
    'assets': {
        'web.assets_frontend': [
            # Owl Components
            'nx-analytics-widgets/static/src/component/*/*.js',
            'nx-analytics-widgets/static/src/component/*/*.xml',
            'nx-analytics-widgets/static/src/component/*/*.scss',
            # Interactive JS
            'nx-analytics-widgets/static/src/js/nx_stat_cards_interactive.js',
            # Styles
            'nx-analytics-widgets/static/src/scss/leave.scss',
        ]
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
