from datetime import timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckPhase11(CheckBankingCommon):

    # ------------------------------------------------------------------
    # Maturity horizons
    # ------------------------------------------------------------------
    def test_horizons_drive_report_and_dashboard(self):
        self.company.write({"check_horizon_short_days": 2, "check_horizon_mid_days": 5, "check_horizon_long_days": 10})
        soon, _inv = self._received_check(100.0, due_date=self.today + timedelta(days=2))
        short, _inv = self._received_check(100.0, due_date=self.today + timedelta(days=4))
        medium, _inv = self._received_check(100.0, due_date=self.today + timedelta(days=9))
        later, _inv = self._received_check(100.0, due_date=self.today + timedelta(days=11))
        self.env.flush_all()
        rows = self.env["check.maturity.report"].search([("check_id", "in", (soon | short | medium | later).ids)])
        buckets = {row.check_id: row.bucket for row in rows}
        self.assertEqual([buckets[c] for c in (soon, short, medium, later)], ["3_soon", "4_short", "5_medium", "6_later"])
        data = self.env["check.check"].get_dashboard_data()
        self.assertEqual(data["horizons"], {"short": 2, "mid": 5, "long": 10})
        self.assertEqual(data["incoming_due_week"]["count"], 2, "Within 5 days")
        self.assertEqual(data["incoming_due_month"]["count"], 3, "Within 10 days")

    def test_horizons_must_increase(self):
        with self.assertRaises(ValidationError):
            self.company.write({"check_horizon_short_days": 7, "check_horizon_mid_days": 3})

    # ------------------------------------------------------------------
    # Manual valuation rate (optional)
    # ------------------------------------------------------------------
    def test_manual_rate_only_when_enabled(self):
        check = self._create_incoming(check_number=self._next_number(), amount=100.0, currency_id=self.eur.id)
        automatic = check.company_amount
        with self.assertRaises(UserError):
            check.write({"valuation_rate": 50.0})
        self.company.check_allow_manual_rate = True
        with self.assertRaises(UserError):
            check.with_user(self.check_treasury).write({"valuation_rate": 50.0})
        check.write({"valuation_rate": 50.0})
        self.assertAlmostEqual(check.company_amount, 5000.0)
        check.write({"valuation_rate": 0.0})
        self.assertAlmostEqual(check.company_amount, automatic, msg="Empty rate falls back to the automatic policy")
        check.write({"valuation_rate": 50.0})
        self.company.check_allow_manual_rate = False
        self.assertAlmostEqual(check.company_amount, automatic, msg="Disabling the option restores automatic valuation")

    # ------------------------------------------------------------------
    # Outgoing check lost after issue
    # ------------------------------------------------------------------
    def test_outgoing_lost_after_issue_marks_leaf_lost(self):
        book = self.env["check.book"].create({"journal_id": self.bank_journal.id, "first_number": 700, "last_number": 702})
        book.action_activate()
        leaf = book.leaf_ids[:1]
        bill = self._bill(400.0)
        check = self._create_outgoing(check_number="x", leaf_id=leaf.id, amount=400.0)
        self._allocate(check, bill, 400.0)
        check.action_issue()
        self._wizard(check, "deliver", recipient="Courier").action_confirm()
        self._wizard(check, "lose", user=self.check_manager, reason="Lost by courier").action_confirm()
        self.assertEqual(check.state, "lost")
        self.assertEqual(leaf.state, "lost")
        self.assertAlmostEqual(bill.amount_residual, 400.0)

    # ------------------------------------------------------------------
    # Group by bounce reason
    # ------------------------------------------------------------------
    def test_group_by_bounce_reason(self):
        first, _inv = self._received_check(100.0)
        second, _inv = self._received_check(200.0)
        self._deposit(first | second)
        self._bounce(first)
        self._bounce(second, reason=self.reason_other, note="Bank system")
        groups = self.env["check.check"]._read_group(
            [("id", "in", (first | second).ids)], ["last_bounce_reason_id"], ["company_amount:sum"],
        )
        self.assertEqual({reason.code: amount for reason, amount in groups},
                         {"insufficient_funds": 100.0, "other": 200.0})
        view = self.env["check.check"].get_views([(False, "search")])["views"]["search"]["arch"]
        self.assertIn("group_bounce_reason", view)

    # ------------------------------------------------------------------
    # Dashboard: outgoing due today / this month
    # ------------------------------------------------------------------
    def test_dashboard_outgoing_due_today_and_month(self):
        today = self._create_outgoing(check_number=self._next_number(), amount=300.0, due_date=self.today)
        month = self._create_outgoing(check_number=self._next_number(), amount=500.0,
                                      due_date=self.today + timedelta(days=20))
        (today | month).action_issue()
        data = self.env["check.check"].get_dashboard_data()
        self.assertAlmostEqual(data["outgoing_due_today"]["amount"], 300.0)
        self.assertAlmostEqual(data["outgoing_due_month"]["amount"], 800.0)

    # ------------------------------------------------------------------
    # Repair allocations after an invoice changed in Accounting
    # ------------------------------------------------------------------
    def _repair(self, check):
        action = check.with_user(self.check_manager).action_open_reallocation_wizard()
        return self.env["check.reallocation.wizard"].browse(action["res_id"])

    def test_repair_moves_money_to_another_invoice(self):
        check, invoice = self._received_check(800.0)
        replacement_invoice = self._invoice(800.0)
        invoice.button_draft()
        invoice.button_cancel()
        self.assertTrue(check.accounting_attention)
        wizard = self._repair(check)
        self.assertEqual(wizard.open_line_ids.resolution, "other")
        self.assertFalse(wizard.open_line_ids.same_available)
        wizard.target_ids.filtered(lambda t: t.document_name == replacement_invoice.name).selected = True
        wizard.action_confirm()
        self.assertTrue(replacement_invoice.currency_id.is_zero(replacement_invoice.amount_residual))
        self.assertEqual(check.allocation_ids.move_id, replacement_invoice)
        self.assertFalse(check.accounting_attention, "Review closes once nothing is left open")

    def test_repair_reconciles_again_with_reposted_invoice(self):
        check, invoice = self._received_check(600.0)
        invoice.button_draft()
        invoice.action_post()
        wizard = self._repair(check)
        self.assertTrue(wizard.open_line_ids.same_available)
        self.assertEqual(wizard.open_line_ids.resolution, "same")
        wizard.action_confirm()
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertFalse(check.accounting_attention)

    def test_repair_can_keep_amount_as_credit(self):
        check, invoice = self._received_check(500.0)
        invoice.button_draft()
        invoice.button_cancel()
        wizard = self._repair(check)
        wizard.open_line_ids.resolution = "credit"
        wizard.action_confirm()
        self.assertFalse(check.accounting_attention)

    def test_repair_is_for_managers_and_accountants(self):
        check, invoice = self._received_check(500.0)
        invoice.button_draft()
        with self.assertRaises(Exception):
            check.with_user(self.check_treasury).action_open_reallocation_wizard()

    # ------------------------------------------------------------------
    # Bank fees in another currency
    # ------------------------------------------------------------------
    def test_bank_fee_in_another_currency(self):
        check, _inv = self._received_check(1000.0)
        self._deposit(check)
        self.env["check.collection.wizard"].with_context(default_check_ids=[(6, 0, check.ids)]).create({
            "fee_amount": 20.0, "fee_currency_id": self.eur.id,
        }).action_confirm()
        fee = self._entries(check, "fee")
        expense = fee.line_ids.filtered(lambda l: l.account_id == self.company.check_fee_account_id)
        bank = fee.line_ids - expense
        self.assertEqual((expense.currency_id, expense.amount_currency), (self.eur, 20.0))
        company_balance = self.eur._convert(20.0, self.company.currency_id, self.company, self.today)
        self.assertAlmostEqual(expense.balance, company_balance)
        self.assertEqual(bank.currency_id, self.company.currency_id, "The bank side stays in the bank's currency")
        self.assertAlmostEqual(bank.amount_currency, -company_balance)
