{
    "name": "Check Management - Demo Data Generator",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Generate hundreds to tens of thousands of realistic checks through the real check workflow",
    "description": "For test and demo databases only: generated checks post real accounting entries.",
    "author": "Sayed Anwar",
    "license": "OPL-1",
    "depends": ["sa_check_management"],
    "data": [
        "security/ir.model.access.csv",
        "data/check_demo_cron.xml",
        "wizard/check_demo_wizard_views.xml",
        "views/check_demo_job_views.xml",
    ],
    "installable": True,
}
