from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    portal_ticket_role = fields.Selection(
        selection=[
            ("user", "Portal User"),
            ("admin", "Portal Admin"),
        ],
        string="Portal Ticket Role",
        related="partner_id.portal_role",
        readonly=False,
        help="Portal User sees only their own tickets. Portal Admin sees all company tickets and orders.",
    )
