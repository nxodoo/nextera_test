from odoo import api, fields, models


SEVERITY_PRIORITY_MAP = {
    "low": "1",
    "medium": "2",
    "high": "3",
}


class HelpdeskTicketType(models.Model):
    _name = "nx.helpdesk.ticket.type"
    _description = "Helpdesk Ticket Type"
    _order = "sequence, id"

    name = fields.Char(
        string="Ticket Type",
        required=True,
    )
    sequence = fields.Integer(
        default=10,
    )
    active = fields.Boolean(
        default=True,
    )
    severity = fields.Selection(
        selection=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
        ],
        string="Severity",
        required=True,
        default="low",
    )
    priority = fields.Selection(
        selection=[
            ("1", "Low"),
            ("2", "Medium"),
            ("3", "High"),
        ],
        string="Priority",
        compute="_compute_priority",
        store=True,
        readonly=True,
    )
    sla_policy_id = fields.Many2one(
        "helpdesk.sla",
        string="SLA Policy",
        domain=[("active", "=", True)],
    )

    @api.depends("severity")
    def _compute_priority(self):
        for ticket_type in self:
            ticket_type.priority = SEVERITY_PRIORITY_MAP.get(ticket_type.severity, "1")

    _sql_constraints = [
        ("nx_helpdesk_ticket_type_name_uniq", "unique(name)", "Ticket type name must be unique."),
    ]
