# -*- coding: utf-8 -*-
{
    'name': 'NXPortal My Tabs',
    'version': '1.0.0',
    'summary': 'Replace My Account cards with a shadcn/ui-inspired sidebar navigation',
    'description': """
                           Replaces the default portal layout with a modern sidebar navigation
                           inspired by shadcn/ui sidebar component. Features grouped navigation,
                           icons, mobile offcanvas support, and clean minimal design.
                           Sidebar groups and items are fully configurable from the backend.
                       """,
    'author': 'Hisham Megahed',
    'category': 'Website',
    'license': 'LGPL-3',
    'depends': ['base', 'portal', 'web', 'website', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/portal_sidebar_data.xml',
        'views/portal_sidebar_views.xml',
        'views/portal_sidebar_components.xml',
        'views/portal_sidebar_desktop.xml',
        'views/portal_sidebar_mobile.xml',
        'views/portal_tabs.xml',
        'views/setting.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'portal_my_tabs/static/src/scss/portal_tabs.scss',
            'portal_my_tabs/static/src/js/sidebar_trigger.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
