# -*- coding: utf-8 -*-
{
    'name': 'Employee Custody Management',
    'version': '1.0',
    'summary': 'This module allows you manage employees custodies.',
    'description': '''
        Using this module, You can manage hemployee custody by creating a custody request and journal entry related to it
    ''',
    'category': 'Accounting',
    'author': 'Sayed Anwar',
    'company': 'Nextera MEA',
    'depends': ['base', 'mail', 'accountant', 'hr', 'stock', 'product_expiry'],
    'data': [
        'security/custody_security.xml',
        'security/ir.model.access.csv',
        'data/seq_custody_request.xml',
        'views/action.xml',
        'views/menu.xml',
        'wizard/custody_create_wizard_view.xml',
        'wizard/custody_product_return_wizard_view.xml',
        'views/custody_request_views.xml',
        'views/res_config_settings_views.xml',
		'wizard/custody_bill_payment_wizard_view.xml',
		'views/account_move_views.xml',
		'views/account_journal_views.xml',
		'views/account_payment_view.xml',
		'wizard/custody_return_wizard_view.xml',
],
    'assets': {
        'web.assets_backend': [
            'nx_employee_custody_management/static/src/scss/custody.scss',
            'nx_employee_custody_management/static/src/js/custody_list_controller.js',
        ],
    },
    'images': ['static/description/icon.png'],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}

