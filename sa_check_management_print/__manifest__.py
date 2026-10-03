{
    "name": "Check Management - Check Printing",
    "version": "18.0.1.1.0",
    "category": "Accounting/Accounting",
    "summary": "Print outgoing checks on bank check leaves, with Arabic and English amount in words",
    "author": "Sayed Anwar",
    "license": "OPL-1",
    "depends": ["sa_check_management"],
    "data": [
        "security/ir.model.access.csv",
        "security/check_print_security.xml",
        "report/check_print_templates.xml",
        "views/check_print_layout_views.xml",
        "views/check_check_views.xml",
        "data/check_print_layout_data.xml",
    ],
    "installable": True,
    "application": False,
}
