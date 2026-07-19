# -*- coding: utf-8 -*-
{
    'name': 'NX HR Employee Summary',
    'version': '1.0',
    'summary': 'Executive employee summary tab for contract renewal decisions',
    'description': """
NX HR Employee Summary
======================
Adds a "Summary" tab to the Employee Profile that gives HR and decision makers a
single, scannable view to evaluate an employee before a contract renewal.

Sections
--------
* Executive Recommendation (always visible) - contract end date, days remaining,
  system recommendation.
* Career Journey & Compensation Progression (collapsible) - years of service,
  promotions, transfers, latest changes and a career milestones timeline/table.
* Compensation Growth History (collapsible) - current monthly/annual cost and the
  full salary evolution since hire. No post-renewal projections are shown.
* Attendance & Operational Record (collapsible) - working/present/absent days,
  leave breakdown, late arrivals and disciplinary warnings.
* HR Recommendation Note (collapsible) - HR comments, manager comments and a brief
  decision summary.

Built on the Nextera section-toggle component for a consistent, foldable UI.
    """,
    'author': 'Ahmed Tarek',
    'company': 'Nextera MEA',
    'depends': ['base', 'mail', 'hr', 'hr_contract', 'hr_holidays',
                'hr_attendance', 'hr_skills', 'nx_nextera_base',
                'nx_hr_job_history', 'nx_payroll_timesheet_work_entry'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_employee_resume_view.xml',
        'views/hr_employee_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nx_hr_employee_summary/static/src/scss/summary.scss',
            'nx_hr_employee_summary/static/src/js/employee_summary.js',
            'nx_hr_employee_summary/static/src/xml/employee_summary.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
