# -*- coding: utf-8 -*-
{
    'name': 'NextEra Egypt Payroll Tax',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Central Egyptian income-tax configuration for Payroll',
    'description': '''
        Egypt Payroll Tax
        =================
        A central configuration screen inside Payroll Configuration to manage
        Egyptian income tax: define tax brackets, manage versions, test the
        monthly tax calculation, and feed the computed tax into the salary
        structure / payslip through the "Income Tax" (EGY_TAX) salary rule.
    ''',
    'author': 'Ahmed Tarek',
    'company': 'Nextera MEA',
    'website': 'https://www.nexteramea.com',
    'depends': [
        'hr_payroll',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/salary_rule_data.xml',
        'views/egypt_payroll_tax_views.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
