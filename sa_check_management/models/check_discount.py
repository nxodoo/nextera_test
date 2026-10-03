from odoo import _, fields, models
from odoo.exceptions import UserError

from .check_banking import CTX_INTERNAL_ACCOUNTING, GROUP_TREASURY
from .check_lifecycle import ACTION_EVENTS, ACTION_GROUPS, TRANSITIONS

TRANSITIONS["incoming"].update({
    "discount": (frozenset({"received"}), "discounted"),
    "discount_collect": (frozenset({"discounted"}), "collected"),
    "discount_bounce": (frozenset({"discounted"}), "bounced"),
})
ACTION_GROUPS.update({
    "discount": GROUP_TREASURY,
    "discount_collect": GROUP_TREASURY,
    "discount_bounce": GROUP_TREASURY,
})
ACTION_EVENTS.update({
    "discount": "discounted",
    "discount_collect": "collected",
    "discount_bounce": "bounced",
})


class CheckCheck(models.Model):
    _inherit = "check.check"

    discount_enabled = fields.Boolean(related="company_id.check_discount_enabled")
    discount_journal_id = fields.Many2one("account.journal", string="Discounted At", readonly=True, copy=False)
    discount_date = fields.Date(readonly=True, copy=False)
    discount_advance_amount = fields.Monetary(
        string="Bank Advance", currency_field="currency_id", readonly=True, copy=False,
        help="What the bank lent against the check; the liability repaid at maturity.",
    )
    discount_fee = fields.Monetary(string="Discount Charges", currency_field="currency_id", readonly=True, copy=False)
    discount_net_amount = fields.Monetary(
        string="Received from Bank", currency_field="currency_id", readonly=True, copy=False,
    )

    # ------------------------------------------------------------------
    # Buttons and wizard-backed actions
    # ------------------------------------------------------------------
    def action_open_discount_wizard(self):
        self.ensure_one()
        return self._open_exception_wizard("check.discount.wizard", _("Discount Check at Bank"))

    def _apply_discount(self, journal, date, advance, fee=0.0, note=False):
        self.ensure_one()
        self._transition("discount", note=note or _("Discounted at %s", journal.sudo().display_name), extra_vals={
            "discount_journal_id": journal.id,
            "discount_date": date,
            "discount_advance_amount": advance,
            "discount_fee": fee,
            "discount_net_amount": advance - fee,
        })

    def _apply_discount_collect(self, date, note=False):
        self._transition("discount_collect", note=note, extra_vals={"collected_date": date})

    def _apply_discount_bounce(self, reason, date, note=False, reference=False):
        for check in self:
            event_note = "\n".join(filter(None, [reason.name, note, reference and _("Bank reference: %s", reference)]))
            check._transition("discount_bounce", note=event_note, extra_vals={
                "bounce_count": check.bounce_count + 1,
                "last_bounce_date": date,
                "last_bounce_reason_id": reason.id,
                "last_bounce_reference": reference or False,
                "last_bounce_note": note or False,
            })

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------
    def _validate_transition(self, action):
        super()._validate_transition(action)
        if action == "discount":
            self._validate_discountable()

    def _validate_discountable(self):
        self.ensure_one()
        if not self.company_id.check_discount_enabled:
            raise UserError(_("Check discounting is not enabled for %(company)s.", company=self.company_id.name))
        if self.purpose in ("guarantee", "security"):
            raise UserError(_("Guarantee and security checks cannot be discounted."))
        if self.accounting_status != "posted":
            raise UserError(_(
                "Check %(check)s has no receipt entry; only checks settled at receipt can be discounted.",
                check=self.display_name,
            ))

    # ------------------------------------------------------------------
    # Accounting (handlers run through the generic _after_<action> dispatch)
    # ------------------------------------------------------------------
    def _after_discount(self):
        """Dr bank (net) + Dr discount charges / Cr discounted checks liability."""
        company = self.company_id._sa_check_accounting_setup()
        journal = self.discount_journal_id.sudo()
        name = _("Discount of check %s", self.display_name)
        liability = company._sa_check_discount_liability_account()
        lines = [
            self._entry_line(company._sa_check_bank_account(journal, "inbound"), self.discount_net_amount, name, partner=False),
            self._entry_line(liability, -self.discount_advance_amount, name),
        ]
        if not self.currency_id.is_zero(self.discount_fee):
            lines.append(self._entry_line(company._sa_check_discount_cost_account(), self.discount_fee, name, partner=False))
        self._balance_entry_lines(lines)
        move = self._create_check_entry("discount", journal, self.discount_date, lines)
        self._log_event("accounting", note=_("Posted: %s", move.name), source=move)

    def _after_discount_collect(self):
        """At maturity: the advance repays the liability and the bank credits the rest of the check."""
        company = self.company_id._sa_check_accounting_setup()
        journal = self.discount_journal_id.sudo()
        holding = self._open_holding_lines()
        name = _("Maturity of discounted check %s", self.display_name)
        total = sum(holding.mapped("amount_residual_currency"))
        remainder = total - self.discount_advance_amount
        lines = [self._entry_line(holding.account_id[:1], -total, name, date=self.collected_date)]
        lines.append(self._entry_line(company._sa_check_discount_liability_account(), self.discount_advance_amount,
                                      name, date=self.collected_date))
        if not self.currency_id.is_zero(remainder):
            lines.append(self._entry_line(company._sa_check_bank_account(journal, "inbound"), remainder, name,
                                          partner=False, date=self.collected_date))
        self._balance_entry_lines(lines)
        move = self._create_check_entry("collection", journal, self.collected_date, lines)
        closing = move.line_ids.filtered(lambda line: line.account_id == holding.account_id[:1])
        (closing | holding).reconcile()
        self._reconcile_discount_liability()
        self._log_event("accounting", note=_("Posted: %s", move.name), source=move)

    def _after_discount_bounce(self):
        """The bank takes the advance back and the customer owes the check again."""
        company = self.company_id._sa_check_accounting_setup()
        journal = self.discount_journal_id.sudo()
        name = _("Repayment of discounted check %s", self.display_name)
        liability = company._sa_check_discount_liability_account()
        advance = self.discount_advance_amount
        lines = [
            self._entry_line(liability, advance, name, date=self.last_bounce_date),
            self._entry_line(company._sa_check_bank_account(journal, "outbound"), -advance, name,
                             partner=False, date=self.last_bounce_date),
        ]
        self._balance_entry_lines(lines)
        move = self._create_check_entry("discount_repay", journal, self.last_bounce_date, lines)
        self._reconcile_discount_liability()
        self._log_event("accounting", note=_("Posted: %s", move.name), source=move)
        self._reverse_check_accounting(entry_types=())

    def _entry_line(self, account, amount, name, partner=True, date=None):
        self.ensure_one()
        company = self.company_id
        date = date or self.discount_date or fields.Date.context_today(self)
        return {
            "account_id": account.id,
            "partner_id": self.partner_id.id if partner else False,
            "name": name,
            "currency_id": self.currency_id.id,
            "amount_currency": amount,
            "balance": self.currency_id._convert(amount, company.currency_id, company, date),
        }

    def _balance_entry_lines(self, lines):
        """Put any rounding difference of the conversion on the last line."""
        difference = sum(line["balance"] for line in lines)
        if difference:
            lines[-1]["balance"] -= difference

    def _reconcile_discount_liability(self):
        self.ensure_one()
        liability = self.company_id.check_discount_liability_account_id
        lines = self._all_check_moves().filtered(lambda move: move.state == "posted").line_ids.filtered(
            lambda line: line.account_id == liability and not line.reconciled
        )
        if len(lines) > 1:
            lines.with_context(**{CTX_INTERNAL_ACCOUNTING: True}).reconcile()
