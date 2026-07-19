from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def write(self, vals):
        """Keep KPI evaluation states aligned with payroll payments."""
        res = super().write(vals)
        if {"state", "payment_state"} & set(vals):
            self.mapped("payslip_ids")._sync_kpi_evaluation_states()
        return res

    def action_post(self):
        """Sync KPI states after payroll journal entries are posted."""
        res = super().action_post()
        self.mapped("payslip_ids")._sync_kpi_evaluation_states()
        return res
