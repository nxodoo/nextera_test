from odoo import _, fields, models
from odoo.exceptions import UserError

from .check_banking import CTX_INTERNAL_ACCOUNTING

COLLATERAL = frozenset({"guarantee", "security"})
# While held (incoming) or out with the beneficiary (outgoing) the memorandum entry stays open.
HOLDING_STATES = frozenset({"received", "issued", "delivered", "presented"})


class ResCompany(models.Model):
    _inherit = "res.company"

    check_guarantee_memorandum = fields.Boolean(
        string="Guarantee Memorandum Entries",
        help="Record guarantee and security checks in off-balance accounts while they are held or outstanding.",
    )
    check_memo_held_account_id = fields.Many2one("account.account", string="Guarantee Checks Held")
    check_memo_held_contra_account_id = fields.Many2one("account.account", string="Guarantee Checks Held (Contra)")
    check_memo_given_account_id = fields.Many2one("account.account", string="Guarantee Checks Given")
    check_memo_given_contra_account_id = fields.Many2one("account.account", string="Guarantee Checks Given (Contra)")

    def _sa_check_memo_accounts(self, direction):
        """(debit, credit) off-balance accounts for guarantees received or given; created on first use."""
        self.ensure_one()
        held = direction == "incoming"
        main_field = "check_memo_held_account_id" if held else "check_memo_given_contra_account_id"
        other_field = "check_memo_held_contra_account_id" if held else "check_memo_given_account_id"
        names = {
            "check_memo_held_account_id": _("Guarantee Checks Held"),
            "check_memo_held_contra_account_id": _("Guarantee Checks Held (Contra)"),
            "check_memo_given_account_id": _("Guarantee Checks Given"),
            "check_memo_given_contra_account_id": _("Guarantee Checks Given (Contra)"),
        }
        for field_name in (main_field, other_field):
            if not self[field_name]:
                self.sudo()[field_name] = self._sa_check_create_off_balance_account(names[field_name])
        return self[main_field], self[other_field]

    def _sa_check_create_off_balance_account(self, name):
        self.ensure_one()
        Account = self.env["account.account"].sudo().with_company(self)
        start = Account.search([*Account._check_company_domain(self), ("account_type", "=", "off_balance")], limit=1)
        code = Account._search_new_account_code(start.code if start else "999000")
        return Account.create({"name": name, "code": code, "account_type": "off_balance"})

    def _sa_check_memo_journal(self):
        self.ensure_one()
        journal = self.env["account.journal"].sudo().search([
            ("company_id", "=", self.id), ("type", "=", "general"),
        ], limit=1)
        if not journal:
            raise UserError(_("Create a miscellaneous journal for %s to post guarantee memorandum entries.", self.name))
        return journal


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    check_guarantee_memorandum = fields.Boolean(related="company_id.check_guarantee_memorandum", readonly=False)


class CheckCheck(models.Model):
    _inherit = "check.check"

    def _after_transition(self, action):
        super()._after_transition(action)
        internal = self.with_context(**{CTX_INTERNAL_ACCOUNTING: True})
        if action in ("receive", "issue"):
            internal._post_memorandum_entry()
        elif internal._active_entries(("memorandum",)) and (action == "invoke" or self.state not in HOLDING_STATES):
            internal._reverse_check_accounting(include_payments=False, entry_types=("memorandum",))

    def _post_memorandum_entry(self):
        self.ensure_one()
        if self.purpose not in COLLATERAL or not self.company_id.check_guarantee_memorandum:
            return
        company = self.company_id.sudo()
        debit, credit = company._sa_check_memo_accounts(self.check_type)
        date = (self.received_date if self.check_type == "incoming" else self.issued_date) or fields.Date.context_today(self)
        balance = self.currency_id._convert(self.amount, company.currency_id, company, date)
        name = _("Guarantee check %s", self.display_name)
        common = {"partner_id": self.partner_id.id, "name": name, "currency_id": self.currency_id.id}
        move = self._create_check_entry("memorandum", company._sa_check_memo_journal(), date, [
            {**common, "account_id": debit.id, "amount_currency": self.amount, "balance": balance},
            {**common, "account_id": credit.id, "amount_currency": -self.amount, "balance": -balance},
        ])
        self._log_event("accounting", note=_("Memorandum entry: %s", move.name), source=move)
