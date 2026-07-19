{
    "name": "HR Expense Lines",
    "version": "18.0.1.0.0",
    "summary": "Manage expense requests with detailed expense lines",
    "description": """
HR Expense Lines
================

This module extends Odoo Expenses with structured expense line details inside a
single expense request.

Main Features
-------------
- Add multiple detailed expense lines under one HR expense request
- Configure reusable expense line types with linked financial accounts
- Control optional maximum amount per expense line type
- Calculate expense totals automatically from the detailed lines
- Keep expense currency and accounting values aligned with line data
- Generate accounting move lines from each detailed expense line
- Support line-level attachments for audit and supporting documents
- Add expense line analysis views for operational and reporting use
- Enforce multi-company access rules for expense lines and line types

Used For
--------
- Detailed staff expense breakdowns
- Account-driven expense categorization
- Line-level attachment and documentation tracking
- Expense reporting and pivot analysis by type, employee, date, and state
""",
    "author": "Ahmed Tarek",
    "license": "LGPL-3",
    "depends": [
        "hr_expense",
        "account",
        "analytic",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/expense_line_type_views.xml",
        "views/hr_expense_views.xml",
        "views/expense_line_analysis_views.xml",
    ],
    "installable": True,
    "application": False,
}
