# -*- coding: utf-8 -*-
{
    'name': 'HR Job Position Department Restriction',
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Show the Department on Job Positions and restrict job selection by department',
    'description': '''
        HR Job Position Department Restriction
        =====================================

        * Adds a visible Department field on the Job Position form.
        * On the employee form, the Job Position selection only shows job
          positions that belong to the employee's department (job positions
          without a department remain available to everyone).
    ''',
    'author': 'Ahmed Tarek',
    'company': 'Nextera MEA',
    'website': 'https://www.nexteramea.com',
    'depends': ['hr'],
    'data': [
        'views/hr_job_views.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
