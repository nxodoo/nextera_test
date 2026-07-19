# -*- coding: utf-8 -*-
{
    'name': 'NX Portal ESS',
    'version': '1.0.0',
    'summary': 'Employee Self-Service portal mode (OWL single-page app)',
    'description': """
        Adds a new 'ESS' portal mode alongside the existing Warranty SLA and
        Activity portal modes. When enabled from Website settings, the /my portal
        renders a modern Employee Self-Service single-page app (OWL) styled with
        the NX warranty teal palette.

        Sections (all wired to real data):
          * Dashboard  - profile header, KPI cards, quick actions, recent requests
          * Leave      - balances, history and new leave requests
          * Attendance - recent check in/out history and monthly summary
          * Payroll    - payslip list and payslip detail
          * Letters    - HR letter requests (new model)
          * Trips      - business trip requests (new model)
    """,
    'author': 'NEXTERA MEA',
    'company': 'NEXTERA MEA',
    'category': 'Website',
    'license': 'LGPL-3',
    'depends': [
        'portal',
        'website',
        'portal_my_tabs',
        'hr',
        'hr_holidays',
        'hr_attendance',
        # NOTE: 'hr_payroll' is intentionally NOT a hard dependency. Depending
        # on it force-installs the (broken) l10n_us_hr_payroll auto-install
        # module. The Payroll tab detects hr.payslip at runtime instead.
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ess_sequence.xml',
        'views/hr_letter_request_views.xml',
        'views/hr_business_trip_views.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'nx_portal_ess/static/src/scss/ess_portal.scss',
            'nx_portal_ess/static/src/js/ess_service.js',
            'nx_portal_ess/static/src/js/components/*.js',
            'nx_portal_ess/static/src/js/components/*.xml',
            'nx_portal_ess/static/src/js/ess_app.js',
            'nx_portal_ess/static/src/js/ess_app.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
