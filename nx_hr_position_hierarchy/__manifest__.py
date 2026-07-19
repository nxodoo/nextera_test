# -*- coding: utf-8 -*-
{
    'name': 'HR Position Based Org Chart',
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Build the HR org chart from job position hierarchy with vacancy support',
    'description': """
        Position Based Org Chart
        ========================

        * Adds parent/child hierarchy, fixed levels, headcount, and status to job positions.
        * Provides a position-based org chart that displays filled and vacant positions.
        * Keeps job position creation centralized in Job Positions configuration.
        * Adds recruitment posting deadlines and expiry controls.
    """,
    'author': 'Ahmed Tarek',
    'company': 'Nextera MEA',
    'website': 'https://www.nexteramea.com',
    'depends': [
        'hr',
        'hr_org_chart',
        'hr_recruitment',
        'web_hierarchy',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/position_level_data.xml',
        'data/position_level_sync_data.xml',
        'data/ir_cron_data.xml',
        'views/hr_position_level_views.xml',
        'views/hr_job_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_applicant_views.xml',
        'views/org_chart_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nx_hr_position_hierarchy/static/src/js/position_org_chart.js',
            'nx_hr_position_hierarchy/static/src/xml/position_org_chart.xml',
            'nx_hr_position_hierarchy/static/src/scss/position_org_chart.scss',
        ],
    },
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
