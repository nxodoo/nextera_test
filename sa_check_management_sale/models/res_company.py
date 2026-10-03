from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    check_sale_bounce_policy = fields.Selection(
        selection=[
            ("none", "Do nothing"),
            ("warning", "Warn on sales orders"),
            ("block", "Block confirmation"),
        ],
        string="Customers with Bounced Checks", required=True, default="warning",
    )
    check_sale_credit_include_checks = fields.Boolean(
        string="Credit Limit Includes Open Checks", default=True,
        help="Checks that already settled invoices but are not collected yet still count as customer credit.",
    )
