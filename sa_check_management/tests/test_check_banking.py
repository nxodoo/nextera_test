from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckBanking(CheckBankingCommon):

    # ------------------------------------------------------------------
    # Deposit batches
    # ------------------------------------------------------------------
    def test_deposit_batch_confirms_checks(self):
        first, _inv = self._received_check(1000.0)
        second, _inv = self._received_check(500.0)
        deposit = self._deposit(first | second)
        self.assertEqual(deposit.state, "confirmed")
        self.assertEqual(deposit.check_count, 2)
        self.assertAlmostEqual(deposit.total_amount, 1500.0)
        for check in first | second:
            self.assertEqual(check.state, "under_collection")
            self.assertEqual(check.current_deposit_id, deposit)
            self.assertEqual(check.current_deposit_line_id.attempt, 1)
            self.assertIn("deposited", check.event_ids.mapped("event_type"))

    def test_draft_check_cannot_be_deposited(self):
        check = self._create_incoming(check_number=self._next_number(), amount=100.0)
        with self.assertRaises(ValidationError):
            self._deposit(check)

    def test_check_cannot_be_in_two_open_deposits(self):
        check, _inv = self._received_check(300.0)
        self.env["check.deposit"].create({
            "journal_id": self.bank_journal.id,
            "line_ids": [Command.create({"check_id": check.id})],
        })
        with self.assertRaises(ValidationError):
            self._deposit(check)

    def test_guarantee_check_cannot_be_deposited(self):
        check, _inv = self._received_check(300.0, allocate=False, purpose="guarantee")
        with self.assertRaises(ValidationError):
            self._deposit(check)

    def test_currency_must_match_bank(self):
        check = self._create_incoming(check_number=self._next_number(), amount=300.0, currency_id=self.eur.id)
        check.action_receive()
        with self.assertRaises(ValidationError):
            self._deposit(check)

    def test_cancel_draft_deposit(self):
        check, _inv = self._received_check(300.0)
        deposit = self.env["check.deposit"].create({
            "journal_id": self.bank_journal.id,
            "line_ids": [Command.create({"check_id": check.id})],
        })
        deposit.action_cancel()
        self.assertEqual(deposit.state, "cancelled")
        self.assertEqual(deposit.line_ids.state, "cancelled")
        self.assertEqual(check.state, "received")
        self._deposit(check)
        self.assertEqual(check.state, "under_collection")

    def test_cancel_confirmed_deposit_requires_manager(self):
        first, _inv = self._received_check(300.0)
        second, _inv = self._received_check(200.0)
        deposit = self._deposit(first | second)
        with self.assertRaises(AccessError):
            deposit.with_user(self.check_treasury).action_cancel()
        deposit.with_user(self.check_manager).action_cancel()
        self.assertEqual(deposit.state, "cancelled")
        self.assertEqual((first | second).mapped("state"), ["received", "received"])

    def test_cancel_deposit_with_collected_check_blocked(self):
        first, _inv = self._received_check(300.0)
        second, _inv = self._received_check(200.0)
        deposit = self._deposit(first | second)
        self._collect(first)
        with self.assertRaises(UserError):
            deposit.with_user(self.check_manager).action_cancel()

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------
    def test_collect_posts_collection_entry(self):
        check, invoice = self._received_check(1000.0)
        deposit = self._deposit(check)
        self._collect(check)
        self.assertEqual(check.state, "collected")
        self.assertEqual(check.collected_date, self.today)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertFalse(check._open_holding_lines())
        entry = self._entries(check, "collection")
        self.assertEqual(entry.journal_id, self.bank_journal)
        self.assertEqual(deposit.state, "done")
        self.assertEqual(check.deposit_line_ids.state, "collected")

    def test_collect_twice_is_rejected(self):
        check, _inv = self._received_check(400.0)
        self._deposit(check)
        self._collect(check)
        with self.assertRaises(UserError):
            check._apply_collect(self.today)
        self.assertEqual(len(self._entries(check, "collection")), 1)

    def test_bank_match_collects_automatically(self):
        check, _inv = self._received_check(800.0)
        self._deposit(check)
        self._bank_match(check._open_holding_lines())
        self.assertEqual(check.state, "collected")
        self.assertFalse(self._entries(check, "collection"), "The bank match is the collection entry")
        self.assertEqual(check.deposit_line_ids.state, "collected")

    def test_collection_policy_settles_at_collection(self):
        self.company.check_settlement_policy = "collection"
        check, invoice = self._received_check(600.0)
        self.assertFalse(check.payment_ids)
        self._deposit(check)
        self._collect(check)
        self.assertEqual(check.accounting_status, "posted")
        self.assertEqual(check.payment_ids.journal_id, self.bank_journal)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_collection_fee_is_expense(self):
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        self._collect(check, fee=10.0)
        fee = self._entries(check, "fee")
        fee_line = fee.line_ids.filtered(lambda line: line.account_id == self.company.check_fee_account_id)
        self.assertAlmostEqual(fee_line.balance, 10.0)

    def test_collection_failure_rolls_back(self):
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        with patch.object(
            type(self.env["check.check"]), "_create_transfer_entry",
            side_effect=UserError("Simulated failure"),
        ):
            with self.assertRaises(UserError):
                self._collect(check)
        check.invalidate_recordset()
        check.deposit_line_ids.invalidate_recordset()
        self.assertEqual(check.state, "under_collection")
        self.assertEqual(check.deposit_line_ids.state, "pending")

    # ------------------------------------------------------------------
    # Bounce
    # ------------------------------------------------------------------
    def test_bounce_reverses_and_reopens_invoice(self):
        check, invoice = self._received_check(1000.0)
        deposit = self._deposit(check)
        self._bounce(check)
        self.assertEqual(check.state, "bounced")
        self.assertEqual(check.bounce_count, 1)
        self.assertEqual(check.last_bounce_reason_id, self.reason_funds)
        self.assertEqual(check.last_bounce_reference, "REJ-1")
        self.assertEqual(check.accounting_status, "reversed")
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)
        self.assertFalse(check._open_holding_lines())
        self.assertEqual(check.deposit_line_ids.state, "bounced")
        self.assertEqual(deposit.state, "done")

    def test_bounce_fee_as_company_expense(self):
        check, _inv = self._received_check(1000.0)
        self._deposit(check)
        self._bounce(check, fee=50.0)
        fee = self._entries(check, "fee")
        debit = fee.line_ids.filtered(lambda line: line.balance > 0)
        self.assertEqual(debit.account_id, self.company.check_fee_account_id)
        self.assertAlmostEqual(debit.balance, 50.0)

    def test_bounce_fee_charged_to_partner(self):
        self.company.check_bounce_fee_policy = "partner"
        check, _inv = self._received_check(1000.0)
        self._deposit(check)
        self._bounce(check, fee=50.0)
        debit = self._entries(check, "fee").line_ids.filtered(lambda line: line.balance > 0)
        self.assertEqual(debit.account_id.account_type, "asset_receivable")
        self.assertEqual(debit.partner_id, self.customer)
        self.assertFalse(debit.reconciled, "The fee stays open on the customer")

    def test_bounce_other_reason_requires_note(self):
        check, _inv = self._received_check(300.0)
        self._deposit(check)
        with self.assertRaises(UserError):
            self._bounce(check, reason=self.reason_other)
        self._bounce(check, reason=self.reason_other, note="Bank system outage")
        self.assertEqual(check.last_bounce_note, "Bank system outage")

    # ------------------------------------------------------------------
    # Re-deposit
    # ------------------------------------------------------------------
    def test_redeposit_resettles_and_collects(self):
        check, invoice = self._received_check(1000.0)
        self._deposit(check)
        self._bounce(check)
        self._deposit(check)
        self.assertEqual(check.state, "under_collection")
        self.assertEqual(check.accounting_status, "posted")
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertEqual(check.current_deposit_line_id.attempt, 2)
        self.assertIn("redeposited", check.event_ids.mapped("event_type"))
        self._collect(check)
        self.assertEqual(check.state, "collected")
        self.assertEqual(sorted(check.deposit_line_ids.mapped("state")), ["bounced", "collected"])

    def test_redeposit_blocked_when_invoice_paid_meanwhile(self):
        check, invoice = self._received_check(1000.0)
        self._deposit(check)
        self._bounce(check)
        replacement = self._create_incoming(check_number=self._next_number(), amount=1000.0)
        self._allocate(replacement, invoice, 1000.0)
        replacement.action_receive()
        with self.assertRaises(UserError):
            self._deposit(check)
        check.invalidate_recordset()
        self.assertEqual(check.state, "bounced")

    def test_redeposit_limit(self):
        self.company.check_max_redeposits = 1
        check, _inv = self._received_check(500.0)
        self._deposit(check, user=self.check_treasury)
        self._bounce(check, user=self.check_treasury)
        self._deposit(check, user=self.check_treasury)
        self._bounce(check, user=self.check_treasury)
        with self.assertRaises(UserError):
            self._deposit(check, user=self.check_treasury)
        self._deposit(check, user=self.check_manager)
        self.assertEqual(check.state, "under_collection")
        self.assertEqual(check.current_deposit_line_id.attempt, 3)

    # ------------------------------------------------------------------
    # Withdrawal
    # ------------------------------------------------------------------
    def test_withdraw_requires_manager_and_keeps_settlement(self):
        check, invoice = self._received_check(700.0)
        deposit = self._deposit(check)
        with self.assertRaises(AccessError):
            self._wizard(check, "withdraw", user=self.check_treasury, reason="Customer request").action_confirm()
        self._wizard(check, "withdraw", user=self.check_manager, reason="Customer request").action_confirm()
        self.assertEqual(check.state, "received")
        self.assertEqual(check.accounting_status, "posted")
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertEqual(check.deposit_line_ids.state, "withdrawn")
        self.assertEqual(deposit.state, "done")

    # ------------------------------------------------------------------
    # Deposit entry option (checks under collection)
    # ------------------------------------------------------------------
    def test_deposit_entry_moves_to_under_collection(self):
        self.company.check_deposit_entry = True
        check, _inv = self._received_check(900.0)
        self._deposit(check)
        under_collection = self.company.check_under_collection_account_id
        self.assertTrue(self._entries(check, "deposit"))
        self.assertEqual(check._open_holding_lines().account_id, under_collection)
        self._collect(check)
        self.assertEqual(check.state, "collected")
        self.assertFalse(check._open_holding_lines())

    def test_deposit_entry_reversed_on_withdraw(self):
        self.company.check_deposit_entry = True
        check, _inv = self._received_check(900.0)
        self._deposit(check)
        self._wizard(check, "withdraw", user=self.check_manager, reason="Error").action_confirm()
        self.assertEqual(check._open_holding_lines().account_id, self.company.check_receivable_account_id)

    def test_deposit_entry_reversed_on_bounce(self):
        self.company.check_deposit_entry = True
        check, invoice = self._received_check(900.0)
        self._deposit(check)
        self._bounce(check)
        self.assertFalse(check._open_holding_lines())
        self.assertAlmostEqual(invoice.amount_residual, 900.0)

    # ------------------------------------------------------------------
    # Outgoing clearing
    # ------------------------------------------------------------------
    def _issued_outgoing(self, amount=500.0):
        bill = self._bill(amount)
        check = self._create_outgoing(check_number=self._next_number(), amount=amount)
        self._allocate(check, bill, amount)
        check.action_issue()
        return check, bill

    def test_outgoing_clear_with_wizard(self):
        check, _bill = self._issued_outgoing()
        self._wizard(check, "deliver", recipient="Vendor rep").action_confirm()
        self._collect(check)
        self.assertEqual(check.state, "cleared")
        self.assertEqual(check.cleared_date, self.today)
        self.assertTrue(self._entries(check, "clearing"))
        self.assertFalse(check._open_holding_lines())

    def test_outgoing_bank_match_clears_automatically(self):
        check, _bill = self._issued_outgoing()
        self._bank_match(check._open_holding_lines())
        self.assertEqual(check.state, "cleared")
        self.assertFalse(self._entries(check, "clearing"))

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    def test_treasury_without_accounting_rights_runs_banking(self):
        self.assertFalse(self.check_treasury.has_group("account.group_account_invoice"))
        first, _inv = self._received_check(300.0)
        second, invoice = self._received_check(400.0)
        self._deposit(first | second, user=self.check_treasury)
        self._collect(first, user=self.check_treasury, fee=5.0)
        self._bounce(second, user=self.check_treasury, fee=5.0)
        self.assertEqual((first.state, second.state), ("collected", "bounced"))
        self.assertAlmostEqual(invoice.amount_residual, 400.0)

    def test_check_user_cannot_deposit(self):
        check, _inv = self._received_check(300.0)
        with self.assertRaises(AccessError):
            self._deposit(check, user=self.check_user)
