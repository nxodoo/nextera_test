# -*- coding: utf-8 -*-
{
    "name": "Nextera HR Analytics Dashboard",
    "summary": "HR analytics landing dashboard and employee document compliance",
    "description": """
HR Analytics Dashboard
======================
* Executive HR analytics dashboard as the landing screen of the Employees app.
* Employee document compliance: configurable document types with applicability
  rules (gender / department / job), per-employee document checklist, and
  compliance tracking that feeds the dashboard.
""",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "author": "Nextera",
    "license": "LGPL-3",
    "depends": ["hr", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/hr_employee_document_type_data.xml",
        "views/hr_employee_document_type_views.xml",
        "views/hr_employee_document_views.xml",
        "views/hr_employee_views.xml",
        "views/hr_dashboard_action.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "nx_hr_analytics_dashboard/static/src/dashboard/hr_dashboard.scss",
            "nx_hr_analytics_dashboard/static/src/dashboard/hr_dashboard.xml",
            "nx_hr_analytics_dashboard/static/src/dashboard/hr_dashboard.js",
        ],
    },
    "installable": True,
    "application": False,
}
