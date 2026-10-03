from odoo import api, models


class AccountPaymentMethod(models.Model):
    _inherit = "account.payment.method"

    @api.model
    def _get_payment_method_information(self):
        info = super()._get_payment_method_information()
        # Incoming lives on the portfolio journal and, for settlement at collection, on bank journals.
        info["sa_check_in"] = {"mode": "multi", "type": ("cash", "bank")}
        info["sa_check_out"] = {"mode": "multi", "type": ("bank",)}
        return info
