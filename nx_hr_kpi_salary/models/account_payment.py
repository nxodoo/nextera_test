from odoo import models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _sync_related_payroll_payslips(self):
        """Update payroll payslip states from linked validated payments."""
        target_payments = self.filtered(lambda payment: payment.state in ("in_process", "paid"))
        if not target_payments:
            return
        payroll_moves = (
            target_payments.invoice_ids
            | target_payments.reconciled_invoice_ids
            | target_payments.reconciled_bill_ids
        ).filtered("payslip_ids")
        payslips = payroll_moves.mapped("payslip_ids").filtered(lambda slip: slip.state == "done")
        if payslips:
            payslips.action_payslip_paid()

    def action_post(self):
        res = super().action_post()
        self._sync_related_payroll_payslips()
        return res

    def write(self, vals):
        res = super().write(vals)
        if "state" in vals:
            self._sync_related_payroll_payslips()
        return res
