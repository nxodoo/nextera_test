{
    'name': 'IQAMA Management',
    'version': '1.0',
    'summary': 'Residency and visa request lifecycle management',
    'description': """
IQAMA Management
================

This module manages the full residency and visa request lifecycle for employees
inside Odoo HR.

Main Features
-------------
- Configure residency and visa types by country, duration, required documents,
  renewal rules, estimated cost, and notification lead time
- Add approval on the residency on the employee in the work info
- Create employee residency and visa requests with auto-generated request numbers
- Track requests through submission, review, processing, activation, rejection,
  cancellation, and expiry states
- Load required employee and family document checklists automatically from the
  selected residency/visa type
- Manage family members, their passports, and their required supporting documents
- Route requests through approver-based review before processing
- Track fee lines and link them to HR expenses for operational billing follow-up
- Record timeline entries, history changes, travel requests, and attachment progress
- Send expiry reminders and schedule follow-up activities before documents expire
- Mark expired requests automatically through a scheduled action

Used For
--------
- Employee iqama / residency administration
- Visa application and renewal workflows
- HR document checklist management
- Internal approval and processing follow-up
- Expiry monitoring and compliance reminders
""",
    'category': 'Human Resources',
    'author': 'Ahmed Tarek',
    'depends': ['base', 'hr', 'mail', 'hr_expense', 'nx_hr_expense_line'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/iqama_cron.xml',
        'views/iqama_type_views.xml',
        'views/iqama_views.xml',
        'views/hr_iqama_fee_wizard_views.xml',
        'views/hr_iqama_family_document_wizard_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
        'views/iqama_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nx_hr_iqama_management/static/src/js/iqama_form_tabs.js',
            'nx_hr_iqama_management/static/src/js/iqama_drag_drop_binary_field.js',
            'nx_hr_iqama_management/static/src/js/section_toggle_widget.js',
            'nx_hr_iqama_management/static/src/xml/iqama_drag_drop_binary_field.xml',
            'nx_hr_iqama_management/static/src/xml/section_toggle_widget.xml',
            'nx_hr_iqama_management/static/src/scss/iqama_drag_drop_binary_field.scss',
            'nx_hr_iqama_management/static/src/scss/iqama_details_list.scss',
            'nx_hr_iqama_management/static/src/scss/hr_employee_private_info.scss',
            'nx_hr_iqama_management/static/src/scss/section_toggle.scss',
        ],
    },
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}
