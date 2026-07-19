{
    "name": "Warranty / SLA Management",
    "version": "18.0.1.0.0",
    "category": "Services/Helpdesk",
    "author": "Ahmed Tarek",
    "company": "NextEra MEA",
    "summary": "Warranty templates and contracts integrated with Sales, Contacts, Helpdesk, and Portal",
    "description": """
Warranty / SLA Management for Odoo 18
=====================================

This module provides end-to-end warranty and SLA handling integrated with:
- Sales (automatic contract generation on order confirmation)
- Products (warranty templates linked to sellable products)
- Helpdesk (minutes/tickets consumption from support activity)
- Contacts (customer warranty visibility and smart actions)
- Portal (customer-facing warranty overview and progress)

Main capabilities:
- Define reusable warranty templates (months, fixed dates, tickets-based)
- Auto-create warranty contracts from confirmed sale order lines
- Track allocated/used/remaining minutes and tickets
- Daily lifecycle automation (expired / need to be extended)
- Portal pages for customer self-service visibility
""",
    "depends": [
        "base",
        "contacts",
        "product",
        "sale",
        "helpdesk",
        "helpdesk_timesheet",
        "helpdesk_sale_timesheet",
        "project",
        "hr_timesheet",
        "portal",
        "website",
        "website_slides",
        "website_helpdesk",
        "mail",
        "portal_my_tabs",
        "analytic",
    ],
    "data": [
        "security/warranty_sla_security.xml",
        "security/website_slides_security.xml",
        "security/ir.model.access.csv",
        "data/helpdesk_ticket_type_data.xml",
        "data/sequence.xml",
        "data/warranty_contract_cron.xml",
        "data/website_language_selector.xml",
        "data/legacy_view_cleanup.xml",
        "data/website_action_override.xml",
        "views/helpdesk_ticket_type_views.xml",
        "views/helpdesk_team_views.xml",
        "views/warranty_template_views.xml",
        "views/warranty_contract_views.xml",
        "views/warranty_contract_state_override_wizard_views.xml",
        "views/product_template_views.xml",
        "views/sale_order_views.xml",
        "views/res_partner_views.xml",
        "views/res_users_views.xml",
        "views/helpdesk_ticket_views.xml",
        "views/helpdesk_ticket_close_feedback_wizard_views.xml",
        "views/portal_home_templates.xml",
        "views/portal_layout_templates.xml",
        "views/portal_login_account_templates.xml",
        "views/portal_pages_templates.xml",
        "views/website_slides_templates.xml",
        "views/website_helpdesk_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "nx_warranty_sla/static/src/scss/portal_chatter_brand.scss",
            "nx_warranty_sla/static/src/scss/login_brand.scss",
        ],
        "portal.assets_chatter_style": [
            "nx_warranty_sla/static/src/scss/portal_chatter_brand.scss",
        ],
        "web.assets_frontend_lazy": [
            "nx_warranty_sla/static/src/js/portal_counter_fix.js",
            "nx_warranty_sla/static/src/js/portal_text_type.js",
            "nx_warranty_sla/static/src/js/portal_magnetic_button.js",
        ],
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
