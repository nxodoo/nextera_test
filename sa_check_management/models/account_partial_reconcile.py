from odoo import api, models

from .check_banking import CTX_INTERNAL_ACCOUNTING

WATCHED_STATES = frozenset({"under_collection", "issued", "delivered", "presented"})


class AccountPartialReconcile(models.Model):
    _inherit = "account.partial.reconcile"

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        if not self.env.context.get(CTX_INTERNAL_ACCOUNTING):
            partials._sa_check_sync_from_reconciliation()
        return partials

    def _sa_check_sync_from_reconciliation(self):
        """A bank statement (or a manual match) settled a check's holding lines: close the check."""
        lines = (self.debit_move_id | self.credit_move_id).sudo()
        checks = (lines.move_id.origin_payment_id.sa_check_id | lines.move_id.sa_check_id).filtered(
            lambda check: check.state in WATCHED_STATES
        )
        if checks:
            checks._sync_from_bank_reconciliation(max(lines.mapped("date")))
