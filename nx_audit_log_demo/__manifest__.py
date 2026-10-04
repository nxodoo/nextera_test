# -*- coding: utf-8 -*-
{
    'name': 'Audit Log - Demo Data',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Audit',
    'summary': 'Realistic demo evidence for the Audit Log & Compliance Engine. '
               'Uninstall to remove every demo record and demo audit event.',
    'author': 'Nextera MEA',
    'license': 'OPL-1',
    'depends': ['nx_audit_log', 'base_import'],
    'data': [
        'data/demo_actions.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
