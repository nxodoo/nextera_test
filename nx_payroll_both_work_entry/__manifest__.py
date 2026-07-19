# -*- coding: utf-8 -*-
{
    'name': 'NX Payroll - Both Work Entry Source',
    'version': '18.0.2.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Adds "Both" option for Work Entry Source with minimum timesheet hours threshold',
    'description': '''
        NX Payroll Both Work Entry Source
        ==================================

        This module adds a new "Both" option to the Work Entry Source selection
        on employee contracts.

        Behaviour:
        ----------
        - When a contract's Work Entry Source is set to "Both":
          * The system reads the employee's daily timesheet hours.
          * If daily hours >= Minimum Timesheet Hours (configured in Payroll settings):
            → The day is counted as a FULL working day.
          * If daily hours < Minimum Timesheet Hours:
            → Only the actual timesheet hours are counted.

        Configuration:
        --------------
        Go to Payroll → Configuration → Settings and set:
        "Minimum Timesheet Hours" (default: 8 hours).

        Access Rights:
        --------------
        - Employee: can enter timesheets.
        - HR Officer: can view work entries and create payslips.
        - HR Manager: can modify Minimum Timesheet Hours setting and Work Entry Source.
    ''',
    'author': 'Ahmed Tarek',
    'company': 'Nextera MEA',
    'website': 'https://www.nexteramea.com',
    'depends': [
        'hr',
        'hr_contract',
        'hr_payroll',
        'hr_work_entry_contract',
        'hr_timesheet',
        'nx_payroll_timesheet_work_entry',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'views/res_config_settings_views.xml',
        'views/hr_contract_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
