# -*- coding: utf-8 -*-
{
    'name': 'NX Payroll - Timesheet Work Entry Source',
    'version': '18.0.1.0.5',
    'category': 'Human Resources/Payroll',
    'summary': 'Payroll based on approved timesheet hours only (no attendance or calendar days)',
    'description': '''
        NX Payroll Timesheet Work Entry Source
        ======================================

        Adds a "Timesheet" option to Work Entry Source on employee contracts.

        When Work Entry Source is Timesheet:
        - Salary is computed from actual timesheet hours × hourly wage only.
        - Attendance and calendar working days are ignored.
        - No pay is generated when there are no timesheets in the payslip period.
        - Hours are counted only within the payslip period.

        Requires hourly wage on the contract (Hour Cost).
    ''',
    'author': 'Ahmed Tarek',
    'company': 'Nextera MEA',
    'website': 'https://www.nexteramea.com',
    'depends': [
        'hr',
        'hr_contract',
        'hr_holidays',
        'hr_payroll',
        'hr_work_entry_contract',
        'hr_timesheet',
        'project',
        'timesheet_grid',
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'data/hr_payroll_timesheet_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_contract_views.xml',
        'views/hr_payslip_views.xml',
        'views/project_project_views.xml',
        'wizard/internal_project_mass_allocation_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend_lazy': [
            'nx_payroll_timesheet_work_entry/static/src/js/timer_timesheet_grid_mass_allocation.js',
            'nx_payroll_timesheet_work_entry/static/src/xml/timer_timesheet_grid_mass_allocation.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
