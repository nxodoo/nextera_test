# -*- coding: utf-8 -*-
{
    'name': 'Sub Leave Type',
    'version': '1.0',
    'summary': 'Link a sub leave type to a parent leave allocation with shared balance',
    'description': """
        Allows HR to define a Sub Leave Type inside a Leave Allocation.

        Features:
        - A Parent Leave Allocation (e.g. Annual Leave) can reference a Sub Leave Type
          (e.g. Casual Leave) with its own day limit and per-request maximum.
        - When an employee takes a Sub Leave, the system deducts from both the
          sub leave limit and the parent (Annual) leave balance simultaneously.
        - Enforces maximum days per request, sub leave balance, and parent balance checks.
        - Full approval workflow: Draft → Confirm → HR Approval → Validated / Refused.
    """,
    'author': 'Ahmed Tarek',
    'company': 'Nextera MEA',
    'category': 'Human Resources',
    'depends': ['hr', 'hr_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_leave_allocation_views.xml',
        'views/hr_leave_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nx_sub_leave_type/static/src/dashboard/sub_leave_card_patch.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
