from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .check_lifecycle import ACTION_EVENTS, ACTION_GROUPS, GROUP_MANAGER, TRANSITIONS

GROUP_TREASURY = "sa_check_management.group_check_treasury"

# Our own accounting must not be mistaken for a bank match by the reconciliation hook.
CTX_INTERNAL_ACCOUNTING = "sa_check_internal_accounting"
# The bank already settled the holding lines (statement match): close the check without posting.
CTX_BANK_MATCHED = "sa_check_bank_matched"

TRANSITIONS["incoming"].update({
    "deposit": (frozenset({"received"}), "under_collection"),
    "redeposit": (frozenset({"bounced"}), "under_collection"),
    "collect": (frozenset({"under_collection"}), "collected"),
    "bounce": (frozenset({"under_collection"}), "bounced"),
    "withdraw": (frozenset({"under_collection"}), "received"),
    "undo_redeposit": (frozenset({"under_collection"}), "bounced"),
})
TRANSITIONS["outgoing"].update({
    "clear": (frozenset({"issued", "delivered", "presented"}), "cleared"),
    "present": (frozenset({"delivered"}), "presented"),
})
ACTION_GROUPS.update({
    "deposit": GROUP_TREASURY,
    "redeposit": GROUP_TREASURY,
    "collect": GROUP_TREASURY,
    "bounce": GROUP_TREASURY,
    "clear": GROUP_TREASURY,
    "present": GROUP_TREASURY,
    "withdraw": GROUP_MANAGER,
    "undo_redeposit": GROUP_MANAGER,
})
ACTION_EVENTS.update({
    "deposit": "deposited",
    "redeposit": "redeposited",
    "collect": "collected",
    "bounce": "bounced",
    "withdraw": "withdrawn",
    "undo_redeposit": "withdrawn",
    "clear": "cleared",
    "present": "state_change",
})


class CheckCheck(models.Model):
    _inherit = "check.check"

    deposit_line_ids = fields.One2many("check.deposit.line", "check_id", string="Deposits", readonly=True)
    current_deposit_line_id = fields.Many2one(
        "check.deposit.line", compute="_compute_current_deposit_line_id",
    )
    current_deposit_id = fields.Many2one(
        "check.deposit", string="Current Deposit", compute="_compute_current_deposit_line_id",
    )
    bounce_count = fields.Integer(readonly=True, copy=False)
    last_bounce_date = fields.Date(readonly=True, copy=False)
    last_bounce_reason_id = fields.Many2one("check.bounce.reason", readonly=True, copy=False)
    last_bounce_reference = fields.Char(string="Bank Rejection Reference", readonly=True, copy=False)
    last_bounce_note = fields.Text(readonly=True, copy=False)
    entry_count = fields.Integer(compute="_compute_entry_count")

    @api.depends("deposit_line_ids.state", "deposit_line_ids.deposit_state")
    def _compute_current_deposit_line_id(self):
        for check in self:
            pending = check.deposit_line_ids.filtered(
                lambda line: line.state == "pending" and line.deposit_state == "confirmed"
            )
            check.current_deposit_line_id = pending[-1:]
            check.current_deposit_id = pending[-1:].deposit_id

    @api.depends("payment_ids", "sa_move_ids")
    def _compute_entry_count(self):
        for check in self:
            check.entry_count = len(check._all_check_moves())

    # ------------------------------------------------------------------
    # Buttons and wizard-backed actions
    # ------------------------------------------------------------------
    def action_open_deposit_wizard(self):
        return self._open_banking_wizard("check.deposit.wizard", _("Deposit Checks"))

    def action_open_collection_wizard(self):
        title = _("Collect Check") if self[:1].check_type == "incoming" else _("Mark Check Cleared")
        return self._open_banking_wizard("check.collection.wizard", title)

    def action_open_bounce_wizard(self):
        self.ensure_one()
        return self._open_banking_wizard("check.bounce.wizard", _("Bounced Check"))

    def action_open_withdraw_wizard(self):
        return self._open_action_wizard("withdraw")

    def _open_banking_wizard(self, model, title):
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": model,
            "view_mode": "form",
            "target": "new",
            "context": {"default_check_ids": [(6, 0, self.ids)], "default_check_id": self[:1].id},
        }

    def action_view_entries(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_move_journal_line")
        action.update({
            "domain": [("id", "in", self._all_check_moves().ids)],
            "context": {"create": False},
        })
        return action

    def action_mark_presented(self):
        self._transition("present", note=_("The beneficiary presented the check to the bank."))
        return True

    def _apply_collect(self, date, note=False):
        self._transition("collect", note=note, extra_vals={"collected_date": date})

    def _apply_clear(self, date, note=False):
        self._transition("clear", note=note, extra_vals={"cleared_date": date})

    def _apply_bounce(self, reason, date, note=False, reference=False):
        for check in self:
            event_note = "\n".join(filter(None, [reason.name, note, reference and _("Bank reference: %s", reference)]))
            check._transition("bounce", note=event_note, extra_vals={
                "bounce_count": check.bounce_count + 1,
                "last_bounce_date": date,
                "last_bounce_reason_id": reason.id,
                "last_bounce_reference": reference or False,
                "last_bounce_note": note or False,
            })

    def _apply_withdraw(self, reason):
        for check in self:
            line = check.current_deposit_line_id
            action = "withdraw" if not line or line.attempt == 1 else "undo_redeposit"
            check._transition(action, note=reason)

    # ------------------------------------------------------------------
    # Transition integration
    # ------------------------------------------------------------------
    def _action_default_vals(self, action):
        vals = super()._action_default_vals(action)
        today = fields.Date.context_today(self)
        if action == "collect":
            vals["collected_date"] = today
        elif action == "clear":
            vals["cleared_date"] = today
        return vals

    def _validate_transition(self, action):
        super()._validate_transition(action)
        validator = {
            "deposit": self._validate_in_confirmed_deposit,
            "redeposit": self._validate_redeposit,
            "collect": self._validate_in_confirmed_deposit,
            "bounce": self._validate_in_confirmed_deposit,
        }.get(action)
        if validator:
            validator()

    def _validate_in_confirmed_deposit(self):
        self.ensure_one()
        if not self.current_deposit_line_id:
            raise UserError(_("Check %(check)s is not in a confirmed deposit.", check=self.display_name))

    def _validate_redeposit(self):
        self._validate_in_confirmed_deposit()
        if self.env.su or self.env.user.has_group(GROUP_MANAGER):
            return
        done = self.deposit_line_ids.filtered(lambda line: line.attempt > 1 and line.state in ("collected", "bounced"))
        if len(done) >= self.company_id.check_max_redeposits:
            raise UserError(_(
                "Check %(check)s reached the maximum of %(max)s re-deposits; a Check Manager must re-deposit it.",
                check=self.display_name, max=self.company_id.check_max_redeposits,
            ))

    def _after_transition(self, action):
        internal = self.with_context(**{CTX_INTERNAL_ACCOUNTING: True})
        super(CheckCheck, internal)._after_transition(action)
        handler = getattr(internal, f"_after_{action}", None)
        if handler:
            handler()

    def _after_deposit(self):
        self._post_deposit_entry()

    def _after_redeposit(self):
        self._post_check_accounting(date=fields.Date.context_today(self))
        self._post_deposit_entry()

    def _after_collect(self):
        line = self.current_deposit_line_id
        if not self.env.context.get(CTX_BANK_MATCHED):
            self._post_collection(line.journal_id, self.collected_date)
        line._set_line_state("collected", self.collected_date)

    def _after_bounce(self):
        self._reverse_check_accounting()
        self.current_deposit_line_id._set_line_state("bounced", self.last_bounce_date)

    def _after_withdraw(self):
        self._reverse_check_accounting(include_payments=False)
        self.current_deposit_line_id._set_line_state("withdrawn", fields.Date.context_today(self))

    def _after_undo_redeposit(self):
        self._reverse_check_accounting()
        self.current_deposit_line_id._set_line_state("withdrawn", fields.Date.context_today(self))

    def _after_clear(self):
        if not self.env.context.get(CTX_BANK_MATCHED):
            self._post_clearing(self.cleared_date)

    # ------------------------------------------------------------------
    # Accounting of banking steps
    # ------------------------------------------------------------------
    def _post_deposit_entry(self):
        self.ensure_one()
        if not self.company_id.check_deposit_entry or self.accounting_status != "posted":
            return
        company = self.company_id._sa_check_accounting_setup()
        self._create_transfer_entry(
            "deposit", company.check_portfolio_journal_id, self.current_deposit_line_id.deposit_date,
            self._open_holding_lines(), company._sa_check_under_collection_account(),
        )

    def _post_collection(self, journal, date):
        self.ensure_one()
        company = self.company_id._sa_check_accounting_setup()
        if self.accounting_status == "posted":
            self._create_transfer_entry(
                "collection", journal, date, self._open_holding_lines(),
                company._sa_check_bank_account(journal, "inbound"),
            )
        elif self.accounting_status == "none":
            self._post_check_accounting(
                method_line=company._sa_check_bank_method_line(journal, "inbound"), date=date, at_collection=True,
            )

    def _post_clearing(self, date):
        self.ensure_one()
        company = self.company_id._sa_check_accounting_setup()
        if self.accounting_status == "posted":
            self._create_transfer_entry(
                "clearing", self.journal_id, date, self._open_holding_lines(),
                company._sa_check_bank_account(self.journal_id, "outbound"),
            )
        elif self.accounting_status == "none":
            self._post_check_accounting(
                method_line=company._sa_check_bank_method_line(self.journal_id, "outbound"),
                date=date, at_collection=True,
            )

    def _post_bank_fee(self, amount, date, journal, charge_partner=False, label=None, currency=None):
        """Post a bank fee in ``currency`` (default: the bank's): expense or partner against the bank.

        The bank side is converted to the bank journal's currency; both sides share one company balance.
        """
        self.ensure_one()
        internal = self.with_context(**{CTX_INTERNAL_ACCOUNTING: True})
        company = self.company_id._sa_check_accounting_setup()
        if charge_partner:
            debit_account = self.partner_id.with_company(company).property_account_receivable_id
        else:
            debit_account = company._sa_check_fee_account()
        bank_currency = journal.sudo().currency_id or company.currency_id
        fee_currency = currency or bank_currency
        balance = fee_currency._convert(amount, company.currency_id, company, date)
        bank_amount = fee_currency._convert(amount, bank_currency, company, date)
        name = label or _("Bank fee for check %s", self.display_name)
        move = internal._create_check_entry("fee", journal, date, [
            {"account_id": debit_account.id, "partner_id": self.partner_id.id, "name": name,
             "balance": balance, "amount_currency": amount, "currency_id": fee_currency.id},
            {"account_id": company._sa_check_bank_account(journal, "outbound").id, "name": name,
             "balance": -balance, "amount_currency": -bank_amount, "currency_id": bank_currency.id},
        ])
        internal._log_event("accounting", note=_("Bank fee posted: %s", move.name), source=move)
        return move

    def _create_transfer_entry(self, entry_type, journal, date, source_lines, target_account):
        """Move the open balance of ``source_lines`` to ``target_account`` and reconcile the sources."""
        self.ensure_one()
        if not source_lines:
            return self.env["account.move"]
        company = self.company_id
        total_currency = sum(source_lines.mapped("amount_residual_currency"))
        balance = self.currency_id._convert(total_currency, company.currency_id, company, date)
        name = _("Check %(check)s", check=self.display_name)
        common = {"partner_id": self.partner_id.id, "name": name, "currency_id": self.currency_id.id}
        move = self._create_check_entry(entry_type, journal, date, [
            {**common, "account_id": source_lines.account_id[:1].id,
             "balance": -balance, "amount_currency": -total_currency},
            {**common, "account_id": target_account.id,
             "balance": balance, "amount_currency": total_currency},
        ])
        closing_line = move.line_ids.filtered(lambda line: line.account_id == source_lines.account_id[:1])
        (closing_line | source_lines).reconcile()
        self._log_event("accounting", note=_("Posted: %s", move.name), source=move)
        return move

    def _create_check_entry(self, entry_type, journal, date, line_vals):
        self.ensure_one()
        move = self.env["account.move"].sudo().with_company(self.company_id).create({
            "move_type": "entry",
            "journal_id": journal.id,
            "date": date,
            "ref": f"{self.name} - {self.check_number}",
            "sa_check_id": self.id,
            "sa_check_entry_type": entry_type,
            "line_ids": [fields.Command.create(vals) for vals in line_vals],
        })
        move.action_post()
        return move

    # ------------------------------------------------------------------
    # Holding lines and bank matching
    # ------------------------------------------------------------------
    def _holding_accounts(self):
        self.ensure_one()
        company = self.company_id
        if self.check_type == "incoming":
            return company.check_receivable_account_id | company.check_under_collection_account_id
        return company.check_payable_account_id

    def _all_check_moves(self):
        self.ensure_one()
        moves = self.sudo().payment_ids.move_id | self.sudo().sa_move_ids
        return moves | moves.reversal_move_ids

    def _open_holding_lines(self):
        """Open journal items that still represent this check on a holding account."""
        self.ensure_one()
        accounts = self._holding_accounts()
        return self._all_check_moves().filtered(lambda move: move.state == "posted").line_ids.filtered(
            lambda line: line.account_id in accounts
            and not line.reconciled
            and not line.currency_id.is_zero(line.amount_residual_currency)
        )

    def _sync_from_bank_reconciliation(self, date):
        for check in self.sudo():
            action = check._bank_match_action()
            if action and not check._open_holding_lines():
                date_field = "collected_date" if action == "collect" else "cleared_date"
                check.with_context(**{CTX_BANK_MATCHED: True})._transition(action, extra_vals={date_field: date})

    def _bank_match_action(self):
        self.ensure_one()
        if self.accounting_status != "posted":
            return False
        if self.check_type == "incoming" and self.state == "under_collection" and self.current_deposit_line_id:
            return "collect"
        if self.check_type == "outgoing" and self.state in ("issued", "delivered", "presented"):
            return "clear"
        return False
