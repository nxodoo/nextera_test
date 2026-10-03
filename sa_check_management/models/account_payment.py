from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    sa_check_id = fields.Many2one(
        "check.check", string="Check", index="btree_not_null", readonly=True, copy=False,
        ondelete="restrict",
    )
    sa_check_allocation_id = fields.Many2one(
        "check.allocation", string="Check Allocation", index="btree_not_null", readonly=True,
        copy=False, ondelete="set null",
    )
