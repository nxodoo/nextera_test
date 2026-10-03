from odoo import _, models
from odoo.tools.misc import formatLang


class AccountMove(models.Model):
    _inherit = "account.move"

    def _build_credit_warning_message(self, record, current_amount=0.0, exclude_current=False, exclude_amount=0.0):
        company = record.company_id
        open_checks = 0.0
        if company.check_sale_credit_include_checks and record.partner_id:
            open_checks = record.partner_id.commercial_partner_id._sa_check_open_settled_amount(company)
        message = super()._build_credit_warning_message(
            record, current_amount=current_amount + open_checks,
            exclude_current=exclude_current, exclude_amount=exclude_amount,
        )
        if message and open_checks:
            message += "\n" + _(
                "Including customer checks not collected yet: %(amount)s",
                amount=formatLang(self.env, open_checks, currency_obj=company.currency_id),
            )
        return message
