from datetime import timedelta

from odoo import Command, fields
from odoo.tests import new_test_user

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class CheckCommon(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Assertions compare English messages; keep them independent of installed languages.
        cls.env = cls.env(context=dict(cls.env.context, lang="en_US"))
        cls.env.user.lang = "en_US"
        # AccountTestInvoicingCommon runs as a non-superuser accounting user.
        cls.env.user.groups_id |= cls.env.ref("sa_check_management.group_check_manager")
        cls.Check = cls.env["check.check"]
        cls.bank_cib = cls.env["res.bank"].create({"name": "CIB Test"})
        cls.bank_nbe = cls.env["res.bank"].create({"name": "NBE Test"})
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.today = fields.Date.context_today(cls.env.user)
        cls.check_user = cls._new_check_user("check_user", "group_check_user")
        cls.check_manager = cls._new_check_user("check_manager", "group_check_manager")
        cls.check_auditor = cls._new_check_user("check_auditor", "group_check_auditor")
        cls.check_approver = cls._new_check_user("check_approver", "group_check_approver")
        cls.check_treasury = cls._new_check_user("check_treasury", "group_check_treasury")

    @classmethod
    def _new_check_user(cls, login, group):
        company = cls.env.company
        return new_test_user(
            cls.env, login=login, lang="en_US",
            groups=f"base.group_user,sa_check_management.{group}",
            company_id=company.id, company_ids=[(6, 0, company.ids)],
        )

    def _incoming_vals(self, **overrides):
        vals = {
            "check_number": "000123",
            "partner_id": self.partner_a.id,
            "amount": 1000.0,
            "issue_date": self.today,
            "due_date": self.today + timedelta(days=30),
            "bank_id": self.bank_cib.id,
            "drawer_account_number": "ACC-1",
        }
        vals.update(overrides)
        return vals

    def _outgoing_vals(self, **overrides):
        vals = {
            "check_number": "100001",
            "partner_id": self.partner_b.id,
            "amount": 500.0,
            "issue_date": self.today,
            "due_date": self.today + timedelta(days=15),
            "journal_id": self.bank_journal.id,
        }
        vals.update(overrides)
        return vals

    def _create_incoming(self, env=None, **overrides):
        model = (env or self.env)["check.check"].with_context(default_check_type="incoming")
        return model.create(self._incoming_vals(**overrides))

    def _create_outgoing(self, env=None, **overrides):
        model = (env or self.env)["check.check"].with_context(default_check_type="outgoing")
        return model.create(self._outgoing_vals(**overrides))

    def _wizard(self, checks, action, user=None, **vals):
        model = self.env["check.action.wizard"]
        if user:
            model = model.with_user(user)
        return model.with_context(
            default_check_action=action,
            default_check_ids=[(6, 0, checks.ids)],
        ).create(vals)


class CheckAccountingCommon(CheckCommon):
    """Partners without payment terms, invoices/bills and allocation helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.check_outgoing_approval_required = False
        cls.eur = cls.setup_other_currency("EUR")
        # Partners without payment terms: one receivable/payable line per document.
        cls.customer = cls.env["res.partner"].create({"name": "Check Customer"})
        cls.vendor = cls.env["res.partner"].create({"name": "Check Vendor"})
        cls.other_customer = cls.env["res.partner"].create({"name": "Other Customer"})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _invoice(self, amount, partner=None, currency=None):
        return self.init_invoice(
            "out_invoice", partner=partner or self.customer, amounts=[amount], taxes=[],
            currency=currency, post=True,
        )

    def _bill(self, amount, partner=None):
        return self.init_invoice(
            "in_invoice", partner=partner or self.vendor, amounts=[amount], taxes=[], post=True,
        )

    def _open_line(self, move):
        return move.line_ids.filtered(
            lambda line: line.account_id.account_type in ("asset_receivable", "liability_payable")
        )

    def _create_incoming(self, env=None, **overrides):
        overrides.setdefault("partner_id", self.customer.id)
        return super()._create_incoming(env=env, **overrides)

    def _create_outgoing(self, env=None, **overrides):
        overrides.setdefault("partner_id", self.vendor.id)
        return super()._create_outgoing(env=env, **overrides)

    def _allocate(self, check, move, amount):
        return self.env["check.allocation"].create({
            "check_id": check.id,
            "move_line_id": self._open_line(move).id,
            "amount": amount,
        })



class CheckBankingCommon(CheckAccountingCommon):
    """Received checks, deposits, collections, bounces and bank matches."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reason_funds = cls.env.ref("sa_check_management.bounce_reason_insufficient_funds")
        cls.reason_other = cls.env.ref("sa_check_management.bounce_reason_other")
        cls._number = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _next_number(self):
        type(self)._number += 1
        return f"BK-{self._number}"

    def _received_check(self, amount=1000.0, allocate=True, **overrides):
        invoice = self._invoice(amount)
        check = self._create_incoming(check_number=self._next_number(), amount=amount, **overrides)
        if allocate:
            self._allocate(check, invoice, amount)
        check.action_receive()
        return check, invoice

    def _deposit(self, checks, user=None):
        model = self.env["check.deposit.wizard"]
        if user:
            model = model.with_user(user)
        wizard = model.with_context(default_check_ids=[(6, 0, checks.ids)]).create({
            "journal_id": self.bank_journal.id,
        })
        return self.env["check.deposit"].browse(wizard.action_confirm()["res_id"])

    def _collect(self, checks, user=None, fee=0.0):
        model = self.env["check.collection.wizard"]
        if user:
            model = model.with_user(user)
        model.with_context(default_check_ids=[(6, 0, checks.ids)]).create({"fee_amount": fee}).action_confirm()

    def _bounce(self, check, reason=None, fee=0.0, note=False, user=None):
        model = self.env["check.bounce.wizard"]
        if user:
            model = model.with_user(user)
        model.with_context(default_check_id=check.id).create({
            "reason_id": (reason or self.reason_funds).id,
            "fee_amount": fee,
            "note": note,
            "bank_reference": "REJ-1",
        }).action_confirm()

    def _bank_match(self, lines):
        """Simulate a bank statement matched on the check's holding lines."""
        total = sum(lines.mapped("amount_residual"))
        account = lines.account_id
        move = self.env["account.move"].create({
            "journal_id": self.bank_journal.id,
            "line_ids": [
                Command.create({"account_id": self.bank_journal.default_account_id.id, "balance": total, "name": "Statement"}),
                Command.create({"account_id": account.id, "balance": -total, "name": "Statement",
                                "partner_id": lines.partner_id[:1].id}),
            ],
        })
        move.action_post()
        (move.line_ids.filtered(lambda line: line.account_id == account) | lines).reconcile()
        return move

    def _entries(self, check, entry_type):
        return check.sa_move_ids.filtered(lambda move: move.sa_check_entry_type == entry_type and not move.reversed_entry_id)

