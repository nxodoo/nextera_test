from odoo import fields, models


class CheckBounceReason(models.Model):
    _name = "check.bounce.reason"
    _description = "Check Bounce Reason"
    _order = "sequence, id"

    _sql_constraints = [
        ("code_unique", "UNIQUE(code)", "The bounce reason code must be unique."),
    ]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    requires_note = fields.Boolean(help="Users must describe the reason when they select it.")
    active = fields.Boolean(default=True)
