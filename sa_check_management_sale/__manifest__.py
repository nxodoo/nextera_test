{
    "name": "Check Management - Sales",
    "version": "18.0.1.2.0",
    "category": "Sales/Sales",
    "summary": "Count open customer checks in the credit limit and warn or block sales for customers with bounced checks",
    "author": "Sayed Anwar",
    "license": "OPL-1",
    "depends": ["sa_check_management", "sale"],
    "data": [
        "views/sale_order_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
