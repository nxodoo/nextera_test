from odoo import _, fields, models
from odoo.exceptions import UserError

from .check_check import STATE_SELECTION

EVENT_TYPES = [
    ("created", "Created"),
    ("state_change", "State Change"),
    ("received", "Received"),
    ("issued", "Issued"),
    ("delivered", "Delivered"),
    ("deposited", "Deposited"),
    ("redeposited", "Re-deposited"),
    ("withdrawn", "Withdrawn from Bank"),
    ("collected", "Collected"),
    ("cleared", "Cleared"),
    ("bounced", "Bounced"),
    ("rejected", "Rejected by Bank"),
    ("returned", "Returned"),
    ("replaced", "Replaced"),
    ("settled", "Settled by Other Payment"),
    ("endorsed", "Endorsed"),
    ("unendorsed", "Returned by Endorsee"),
    ("released", "Guarantee Released"),
    ("invoked", "Guarantee Invoked"),
    ("discounted", "Discounted at Bank"),
    ("legal", "Legal Action"),
    ("lost", "Lost"),
    ("stopped", "Stop Payment"),
    ("cancelled", "Cancelled"),
    ("handover", "Handover"),
    ("approval", "Approval"),
    ("accounting", "Accounting Entry"),
    ("correction", "Correction"),
    ("imported", "Imported"),
]


class CheckEvent(models.Model):
    _name = "check.event"
    _description = "Check Event"
    _order = "date desc, id desc"

    check_id = fields.Many2one("check.check", required=True, index=True, ondelete="cascade", readonly=True)
    event_type = fields.Selection(EVENT_TYPES, required=True, readonly=True)
    date = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one("res.users", required=True, readonly=True, default=lambda self: self.env.user)
    old_state = fields.Selection(STATE_SELECTION, readonly=True)
    new_state = fields.Selection(STATE_SELECTION, readonly=True)
    note = fields.Text(readonly=True)
    res_model = fields.Char(string="Source Model", readonly=True)
    res_id = fields.Many2oneReference(string="Source Record", model_field="res_model", readonly=True)
    check_type = fields.Selection(related="check_id.check_type", store=True)
    partner_id = fields.Many2one(related="check_id.partner_id", store=True)
    company_id = fields.Many2one(related="check_id.company_id", store=True, index=True)

    def write(self, vals):
        raise UserError(_("Check history is immutable. Record a correction event instead."))

    def unlink(self):
        raise UserError(_("Check history cannot be deleted."))
