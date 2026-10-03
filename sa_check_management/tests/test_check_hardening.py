from datetime import timedelta
from unittest.mock import patch

from psycopg2.errors import LockNotAvailable

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckForeignCurrency(CheckBankingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur_journal = cls.env["account.journal"].create({
            "name": "EUR Bank", "type": "bank", "code": "EURB", "currency_id": cls.eur.id,
        })

    def _set_rate(self, units_per_company_unit):
        Rate = self.env["res.currency.rate"]
        rate = Rate.search([("currency_id", "=", self.eur.id), ("name", "=", self.today),
                            ("company_id", "=", self.company.id)])
        if rate:
            rate.rate = units_per_company_unit
        else:
            Rate.create({"currency_id": self.eur.id, "name": self.today, "rate": units_per_company_unit,
                         "company_id": self.company.id})
        self.eur.invalidate_recordset()

    def _eur_check(self, amount=1000.0):
        invoice = self._invoice(amount, currency=self.eur)
        check = self._create_incoming(check_number=self._next_number(), amount=amount, currency_id=self.eur.id)
        self._allocate(check, invoice, amount)
        check.action_receive()
        return check, invoice

    def _deposit_eur(self, check):
        wizard = self.env["check.deposit.wizard"].with_context(default_check_ids=[(6, 0, check.ids)]).create({
            "journal_id": self.eur_journal.id,
        })
        return self.env["check.deposit"].browse(wizard.action_confirm()["res_id"])

    def test_foreign_check_settles_foreign_invoice(self):
        self._set_rate(2.0)
        check, invoice = self._eur_check(1000.0)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertAlmostEqual(check.payment_ids._seek_for_lines()[0].balance, 500.0)

    def test_collection_at_another_rate_books_the_exchange_difference(self):
        self._set_rate(2.0)
        check, _invoice = self._eur_check(1000.0)
        self._deposit_eur(check)
        self._set_rate(4.0)  # the euro lost half its value before the bank collected
        holding = check._open_holding_lines()
        self._collect(check)
        self.assertEqual(check.state, "collected")
        self.assertFalse(check._open_holding_lines())
        partials = holding.matched_credit_ids | holding.matched_debit_ids
        exchange = partials.exchange_move_id | holding.full_reconcile_id.exchange_move_id
        self.assertTrue(exchange, "The realised exchange loss is booked by Odoo")
        self.assertAlmostEqual(abs(sum(exchange.line_ids.filtered(lambda l: l.balance > 0).mapped("balance"))), 250.0)

    def test_foreign_check_cannot_go_to_company_currency_bank(self):
        self._set_rate(2.0)
        check, _invoice = self._eur_check(500.0)
        with self.assertRaises(ValidationError):
            self._deposit(check)

    def test_foreign_bounce_reopens_foreign_invoice(self):
        self._set_rate(2.0)
        check, invoice = self._eur_check(1000.0)
        self._deposit_eur(check)
        self._bounce(check)
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)
        self.assertEqual(check.accounting_status, "reversed")


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckConcurrency(CheckBankingCommon):

    def _locked_elsewhere(self):
        def raise_lock(_records):
            raise LockNotAvailable("could not obtain lock on row")
        return patch.object(type(self.env["check.check"]), "_sql_lock_rows", raise_lock)

    def test_busy_check_is_refused_without_side_effects(self):
        check = self._create_incoming(check_number=self._next_number())
        with self._locked_elsewhere(), self.assertRaises(UserError):
            check.action_receive()
        check.invalidate_recordset()
        self.assertEqual(check.state, "draft")
        self.assertFalse(check.payment_ids)
        self.assertEqual(check.event_ids.mapped("event_type"), ["created"])

    def test_busy_check_blocks_collection(self):
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        with self._locked_elsewhere(), self.assertRaises(UserError):
            self._collect(check)
        check.invalidate_recordset()
        self.assertEqual(check.state, "under_collection")
        self.assertFalse(self._entries(check, "collection"))

    def test_every_financial_step_takes_the_row_lock(self):
        Check = type(self.env["check.check"])
        original = Check._sql_lock_rows
        with patch.object(Check, "_sql_lock_rows", autospec=True, side_effect=original) as lock:
            check, _inv = self._received_check(500.0)
            self._deposit(check)
            self._collect(check)
            outgoing = self._create_outgoing(check_number=self._next_number(), amount=200.0)
            self.company.check_outgoing_approval_required = True
            outgoing.action_submit()
            outgoing.with_user(self.check_approver).action_approve()
            outgoing.action_issue()
        locked = {tuple(call.args[0].ids) for call in lock.call_args_list}
        self.assertIn((check.id,), locked)
        self.assertIn((outgoing.id,), locked)
        self.assertGreaterEqual(lock.call_count, 7, "receive, deposit, collect, submit, approve stage, approve, issue")

    def test_replayed_collection_is_refused(self):
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        self._collect(check)
        with self.assertRaises(UserError):
            self._collect(check)
        self.assertEqual(len(self._entries(check, "collection")), 1)


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckMultiCompany(CheckBankingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b_data = cls.setup_other_company(name="Check Company B")
        cls.company_b = cls.company_b_data["company"]
        cls.bank_b = cls.company_b_data["default_journal_bank"]
        cls.user_b = new_test_user(
            cls.env, login="check_user_b",
            groups="base.group_user,sa_check_management.group_check_manager",
            company_id=cls.company_b.id, company_ids=[(6, 0, cls.company_b.ids)],
        )

    def test_other_company_sees_nothing(self):
        check, _inv = self._received_check(500.0)
        deposit = self._deposit(check)
        env_b = self.env(user=self.user_b, context={"allowed_company_ids": self.company_b.ids})
        self.assertFalse(env_b["check.check"].search([("id", "=", check.id)]))
        self.assertFalse(env_b["check.deposit"].search([("id", "=", deposit.id)]))
        self.assertFalse(env_b["check.event"].search([("check_id", "=", check.id)]))
        self.env.flush_all()
        self.assertFalse(env_b["check.maturity.report"].search([]))
        data = env_b["check.check"].with_company(self.company_b).get_dashboard_data()
        self.assertEqual(data["incoming_outstanding"]["count"], 0)

    def test_no_cross_company_journal_on_outgoing_check(self):
        with self.assertRaises(UserError):
            self._create_outgoing(check_number=self._next_number(), journal_id=self.bank_b.id)

    def test_no_cross_company_deposit(self):
        check, _inv = self._received_check(500.0)
        with self.assertRaises(UserError):
            self.env["check.deposit"].create({
                "journal_id": self.bank_b.id, "company_id": self.company.id,
                "line_ids": [(0, 0, {"check_id": check.id})],
            })

    def test_no_cross_company_allocation(self):
        invoice_b = self.init_invoice("out_invoice", partner=self.customer, amounts=[300.0], taxes=[],
                                      company=self.company_b, post=True)
        check = self._create_incoming(check_number=self._next_number(), amount=300.0)
        with self.assertRaises(UserError):
            self._allocate(check, invoice_b, 300.0)

    def test_each_company_gets_its_own_accounts_and_portfolio(self):
        self.company._sa_check_accounting_setup()
        self.company_b._sa_check_accounting_setup()
        self.assertNotEqual(self.company.check_portfolio_journal_id, self.company_b.check_portfolio_journal_id)
        self.assertEqual(self.company_b.check_portfolio_journal_id.company_id, self.company_b)
        self.assertIn(self.company_b, self.company_b.check_receivable_account_id.company_ids)
        self.assertNotIn(self.company, self.company_b.check_receivable_account_id.company_ids)

    def test_company_b_runs_its_own_flow(self):
        env_b = self.env(user=self.user_b, context={"allowed_company_ids": self.company_b.ids})
        bank = self.env["res.bank"].create({"name": "Bank B"})
        check = env_b["check.check"].with_context(default_check_type="incoming").create({
            "check_number": "B-1", "partner_id": self.customer.id, "amount": 400.0,
            "due_date": self.today + timedelta(days=10), "bank_id": bank.id, "drawer_account_number": "B-ACC",
        })
        self.assertEqual(check.company_id, self.company_b)
        check.action_receive()
        self.assertEqual(check.payment_ids.sudo().company_id, self.company_b)
        self.assertEqual(check.payment_ids.sudo().journal_id, self.company_b.check_portfolio_journal_id)
