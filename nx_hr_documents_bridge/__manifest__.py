# -*- coding: utf-8 -*-
{
    "name": "Nextera HR Documents ↔ Documents App",
    "summary": "File employee HR documents into a Documents workspace folder",
    "description": """
Bridge: HR employee documents → Documents app
=============================================
Employee documents uploaded on the HR checklist are stored as plain
attachments, which means they never show up in the Documents app. This
bridge files a copy into a Documents folder so they are browsable,
searchable and shareable like any other document.

* Pick a default folder in Settings → Custody/HR.
* Optionally override the folder per document type.
* Uploading, replacing or clearing a file keeps the Documents entry in sync.

Installed automatically when both `nx_hr_analytics_dashboard` and the
Enterprise `documents` app are present — the dashboard module itself keeps
no dependency on Enterprise.
""",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "author": "Ahmed Tarek",
    "license": "LGPL-3",
    "depends": ["nx_hr_analytics_dashboard", "documents"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/hr_employee_document_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
