# -*- coding: utf-8 -*-
{
    "name": "Portal Time Off",
    "version": "1.0",
    "summary": "Manage employee leave requests directly from the portal",
    "description": """
        This module allows employees to submit and view their leave requests 
        directly from the Odoo portal. Employees can:
        - Submit new leave requests with date ranges and descriptions.
        - View a list of their past and current leave requests.
        - Track the status of each request (Draft, Confirmed, Approved, Refused).
        - Receive notifications for leave request submissions (optional email).
        
        Portal users can manage their time off without accessing the backend.
    """,
    'author': 'Sayed Anwar',
    'company': 'Nextera MEA',
    "category": "Human Resources",
    "depends": ["hr", "hr_holidays", "portal", "website","resource"],
    "data": [
        "security/ir.model.access.csv",
        "views/portal_templates.xml",
        "views/portal_menu.xml",
		"views/template_success.xml",
		"views/hr_leave_allocation_view.xml",
],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}