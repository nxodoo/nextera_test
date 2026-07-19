from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def _reconcile_payments(self, to_process, edit_mode=False):
        """Mark payroll payslips as paid once the payable lines are settled.

        The standard payroll extension checks every journal line residual, which
        is too broad for payroll entries because non-reconcilable counterpart
        lines can remain and keep the payslip stuck in ``done``. We only inspect
        the receivable/payable lines that drive payment settlement.
        """
        res = super()._reconcile_payments(to_process, edit_mode=edit_mode)
        if not self.env.context.get("hr_payroll_payment_register"):
            return res

        for vals in to_process:
            payslips = vals["to_reconcile"].move_id.payslip_ids
            for payslip in payslips.filtered(lambda slip: slip.state != "paid" and slip.move_id):
                settlement_lines = payslip.move_id.line_ids.filtered(
                    lambda line: line.account_id.reconcile and not line.display_type
                )
                if settlement_lines and all(
                    line.currency_id.is_zero(line.amount_residual_currency) for line in settlement_lines
                ):
                    payslip.action_payslip_paid()
        return res
