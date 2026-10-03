from datetime import timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckPhase10A(CheckBankingCommon):

    # ------------------------------------------------------------------
    # Valuation rate policy
    # ------------------------------------------------------------------
    def _usd_rates(self):
        """1 EUR = 2 company units on the issue date, 3 on the due date, 4 on the collection date."""
        issue, due, collect = self.today - timedelta(days=10), self.today + timedelta(days=20), self.today
        Rate = self.env["res.currency.rate"]
        self.eur.rate_ids.unlink()
        for day, units in ((issue, 2.0), (collect, 4.0), (due, 3.0)):
            Rate.create({"currency_id": self.eur.id, "name": day, "rate": 1.0 / units, "company_id": self.company.id})
        return issue, due, collect

    def test_valuation_follows_the_policy(self):
        issue, due, _collect = self._usd_rates()
        check = self._create_incoming(check_number=self._next_number(), amount=100.0, currency_id=self.eur.id,
                                      issue_date=issue, due_date=due)
        self.assertAlmostEqual(check.company_amount, 200.0)
        self.company.check_rate_policy = "due"
        self.assertAlmostEqual(check.company_amount, 300.0)
        self.company.check_rate_policy = "collection"
        self.assertAlmostEqual(check.company_amount, 300.0, msg="Due date until the bank collects")

    def test_entries_keep_their_own_date_rate(self):
        issue, due, _collect = self._usd_rates()
        self.company.check_rate_policy = "due"
        check = self._create_incoming(check_number=self._next_number(), amount=100.0, currency_id=self.eur.id,
                                      issue_date=issue, due_date=due)
        check.action_receive()
        self.assertAlmostEqual(check.company_amount, 300.0)
        liquidity = check.payment_ids._seek_for_lines()[0]
        self.assertAlmostEqual(liquidity.balance, 400.0, msg="Posted at today's rate, whatever the valuation policy")

    # ------------------------------------------------------------------
    # Partial discounting with per-bank terms
    # ------------------------------------------------------------------
    def _term(self, **values):
        self.company.check_discount_enabled = True
        return self.env["check.discount.term"].create({"journal_id": self.bank_journal.id, **values})

    def _wizard_for(self, check, term):
        return self.env["check.discount.wizard"].with_context(default_check_id=check.id).create({"term_id": term.id})

    def test_discounting_must_be_enabled(self):
        self.company.check_discount_enabled = False
        term = self.env["check.discount.term"].create({"journal_id": self.bank_journal.id})
        check, _inv = self._received_check(1000.0, due_date=self.today + timedelta(days=30))
        with self.assertRaises(UserError):
            self._wizard_for(check, term).action_confirm()

    def test_terms_compute_advance_and_charges(self):
        term = self._term(advance_rate=80.0, interest_rate=18.25, fixed_fee=10.0)
        check, _inv = self._received_check(10000.0, due_date=self.today + timedelta(days=100))
        wizard = self._wizard_for(check, term)
        self.assertAlmostEqual(wizard.advance, 8000.0)
        # 8000 x 18.25% x 100 / 365 = 400, plus the fixed fee
        self.assertAlmostEqual(wizard.fee, 410.0)
        self.assertAlmostEqual(wizard.net_amount, 7590.0)

    def test_partial_discount_accounting_through_maturity(self):
        term = self._term(advance_rate=80.0)
        check, invoice = self._received_check(10000.0, due_date=self.today + timedelta(days=60))
        wizard = self._wizard_for(check, term)
        wizard.fee = 300.0
        wizard.action_confirm()
        self.assertEqual(check.state, "discounted")
        self.assertAlmostEqual(check.discount_advance_amount, 8000.0)
        liability = self.company.check_discount_liability_account_id
        entry = self._entries(check, "discount")
        self.assertAlmostEqual(entry.line_ids.filtered(lambda l: l.account_id == liability).balance, -8000.0)
        self._collect(check)
        collection = self._entries(check, "collection")
        bank_line = collection.line_ids.filtered(lambda l: l.account_id.account_type == "asset_current"
                                                 and l.account_id != self.company.check_receivable_account_id
                                                 and l.balance > 0 and l.account_id != liability)
        self.assertAlmostEqual(sum(bank_line.mapped("balance")), 2000.0, msg="The bank credits the rest of the check")
        self.assertFalse(check._open_holding_lines())
        open_liability = self.env["account.move.line"].search([("account_id", "=", liability.id), ("reconciled", "=", False)])
        self.assertAlmostEqual(sum(open_liability.mapped("amount_residual")), 0.0)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_partial_discount_bounce_repays_only_the_advance(self):
        term = self._term(advance_rate=70.0)
        check, invoice = self._received_check(1000.0, due_date=self.today + timedelta(days=60))
        wizard = self._wizard_for(check, term)
        wizard.fee = 0.0
        wizard.action_confirm()
        self._bounce(check)
        repay = self._entries(check, "discount_repay")
        liability = self.company.check_discount_liability_account_id
        self.assertAlmostEqual(repay.line_ids.filtered(lambda l: l.account_id == liability).balance, 700.0)
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)

    def test_wizard_keeps_advance_when_fee_is_given(self):
        term = self._term(advance_rate=80.0)
        check, _inv = self._received_check(1000.0, due_date=self.today + timedelta(days=60))
        wizard = self.env["check.discount.wizard"].with_context(default_check_id=check.id).create({
            "term_id": term.id, "fee": 25.0,
        })
        self.assertAlmostEqual(wizard.advance, 800.0)
        self.assertAlmostEqual(wizard.fee, 25.0)

    def test_advance_cannot_exceed_check(self):
        term = self._term()
        check, _inv = self._received_check(1000.0, due_date=self.today + timedelta(days=60))
        wizard = self._wizard_for(check, term)
        wizard.advance = 1200.0
        with self.assertRaises(UserError):
            wizard.action_confirm()

    # ------------------------------------------------------------------
    # Presented
    # ------------------------------------------------------------------
    def test_mark_presented_then_clear(self):
        bill = self._bill(500.0)
        check = self._create_outgoing(check_number=self._next_number(), amount=500.0)
        self._allocate(check, bill, 500.0)
        check.action_issue()
        self._wizard(check, "deliver", recipient="Vendor").action_confirm()
        check.with_user(self.check_treasury).action_mark_presented()
        self.assertEqual(check.state, "presented")
        self._bank_match(check._open_holding_lines())
        self.assertEqual(check.state, "cleared")

    # ------------------------------------------------------------------
    # Changes made outside the check
    # ------------------------------------------------------------------
    def test_invoice_reset_to_draft_flags_the_check(self):
        check, invoice = self._received_check(800.0)
        self.assertFalse(check.accounting_attention)
        invoice.button_draft()
        self.assertTrue(check.accounting_attention)
        self.assertIn("unreconciled", check.accounting_attention_note)
        self.assertTrue(check.activity_ids)

    def test_payment_cancelled_from_accounting_flags_the_check(self):
        check, _invoice = self._received_check(800.0)
        check.payment_ids.move_id.button_draft()
        self.assertTrue(check.accounting_attention)
        self.assertIn("reset to draft", check.accounting_attention_note)

    def test_check_workflow_does_not_flag(self):
        check, _invoice = self._received_check(800.0)
        self._deposit(check)
        self._bounce(check)
        self._deposit(check)
        self._collect(check)
        cancelled, _inv = self._received_check(300.0)
        self._wizard(cancelled, "cancel", user=self.check_manager, reason="Error").action_confirm()
        self.assertFalse((check | cancelled).filtered("accounting_attention"))

    def test_review_flag_cleared_by_manager_only(self):
        check, invoice = self._received_check(800.0)
        invoice.button_draft()
        with self.assertRaises(AccessError):
            check.with_user(self.check_treasury).action_mark_accounting_reviewed()
        check.with_user(self.check_manager).action_mark_accounting_reviewed()
        self.assertFalse(check.accounting_attention)
        self.assertIn("correction", check.event_ids.mapped("event_type"))
