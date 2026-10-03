from odoo import fields, models

CHECK_ENTRY_TYPES = [
    ("deposit", "Deposit"),
    ("collection", "Collection"),
    ("clearing", "Clearing"),
    ("endorsement", "Endorsement"),
    ("discount", "Discount"),
    ("discount_repay", "Discount Repayment"),
    ("memorandum", "Guarantee Memorandum"),
    ("fee", "Bank Fee"),
]


class AccountMove(models.Model):
    _inherit = "account.move"

    # Copied on reversal on purpose: the reversal of a check entry stays linked to the check.
    sa_check_id = fields.Many2one("check.check", string="Check", index="btree_not_null", readonly=True)
    sa_check_entry_type = fields.Selection(CHECK_ENTRY_TYPES, string="Check Entry Type", readonly=True)
