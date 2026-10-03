from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CheckAccountingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckAccounting(CheckAccountingCommon):

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def test_setup_is_idempotent(self):
        self.company._sa_check_accounting_setup()
        journal = self.company.check_portfolio_journal_id
        receivable = self.company.check_receivable_account_id
        self.company._sa_check_accounting_setup()
        self.assertEqual(self.company.check_portfolio_journal_id, journal)
        self.assertEqual(self.company.check_receivable_account_id, receivable)
        self.assertEqual(journal.type, "cash")
        self.assertTrue(receivable.reconcile)
        line = self.company._sa_check_incoming_method_line()
        self.assertEqual(line.journal_id, journal)
        self.assertEqual(line.payment_account_id, receivable)

    # ------------------------------------------------------------------
    # Incoming posting and allocation shapes
    # ------------------------------------------------------------------
    def test_receive_settles_single_invoice(self):
        invoice = self._invoice(1000.0)
        check = self._create_incoming(amount=1000.0)
        self._allocate(check, invoice, 1000.0)
        check.action_receive()
        self.assertEqual(check.accounting_status, "posted")
        self.assertEqual(len(check.payment_ids), 1)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertIn(invoice.payment_state, ("in_payment", "paid"))
        payment = check.payment_ids
        self.assertEqual(payment.outstanding_account_id, self.company.check_receivable_account_id)
        self.assertEqual(payment.journal_id, self.company.check_portfolio_journal_id)
        self.assertIn("accounting", check.event_ids.mapped("event_type"))

    def test_one_check_many_invoices(self):
        invoices = [self._invoice(amount) for amount in (500.0, 700.0, 300.0)]
        check = self._create_incoming(amount=1500.0)
        for invoice in invoices:
            self._allocate(check, invoice, invoice.amount_total)
        check.action_receive()
        self.assertEqual(len(check.payment_ids), 3)
        for invoice in invoices:
            self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_many_checks_one_invoice(self):
        invoice = self._invoice(900.0)
        first = self._create_incoming(check_number="A-1", amount=400.0)
        second = self._create_incoming(check_number="A-2", amount=500.0)
        self._allocate(first, invoice, 400.0)
        self._allocate(second, invoice, 500.0)
        first.action_receive()
        self.assertAlmostEqual(invoice.amount_residual, 500.0)
        second.action_receive()
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_partial_allocation_leaves_invoice_open(self):
        invoice = self._invoice(1000.0)
        check = self._create_incoming(amount=600.0)
        self._allocate(check, invoice, 600.0)
        check.action_receive()
        self.assertAlmostEqual(invoice.amount_residual, 400.0)
        self.assertEqual(invoice.payment_state, "partial")

    def test_unallocated_remainder_stays_as_partner_credit(self):
        invoice = self._invoice(700.0)
        check = self._create_incoming(amount=1000.0)
        self._allocate(check, invoice, 700.0)
        self.assertAlmostEqual(check.unallocated_amount, 300.0)
        check.action_receive()
        self.assertEqual(len(check.payment_ids), 2)
        credit = check.payment_ids.filtered(lambda p: not p.sa_check_allocation_id)
        self.assertAlmostEqual(credit.amount, 300.0)
        counterpart = credit._seek_for_lines()[1]
        self.assertAlmostEqual(abs(counterpart.amount_residual), 300.0)

    def test_check_without_allocation_posts_one_payment(self):
        check = self._create_incoming(amount=250.0)
        check.action_receive()
        self.assertEqual(len(check.payment_ids), 1)
        self.assertAlmostEqual(check.payment_ids.amount, 250.0)

    # ------------------------------------------------------------------
    # Allocation rules
    # ------------------------------------------------------------------
    def test_allocation_cannot_exceed_open_amount(self):
        invoice = self._invoice(500.0)
        check = self._create_incoming(amount=1000.0)
        with self.assertRaises(ValidationError):
            self._allocate(check, invoice, 600.0)

    def test_allocations_cannot_exceed_check_amount(self):
        first, second = self._invoice(800.0), self._invoice(800.0)
        check = self._create_incoming(amount=1000.0)
        self._allocate(check, first, 800.0)
        with self.assertRaises(ValidationError):
            self._allocate(check, second, 300.0)

    def test_allocation_requires_same_partner(self):
        invoice = self._invoice(500.0, partner=self.other_customer)
        check = self._create_incoming(amount=500.0)
        with self.assertRaises(ValidationError):
            self._allocate(check, invoice, 500.0)

    def test_incoming_check_cannot_allocate_vendor_bill(self):
        bill = self._bill(500.0, partner=self.customer)
        check = self._create_incoming(amount=500.0)
        with self.assertRaises(ValidationError):
            self._allocate(check, bill, 500.0)

    def test_allocation_requires_same_currency(self):
        invoice = self._invoice(500.0, currency=self.eur)
        check = self._create_incoming(amount=500.0)
        with self.assertRaises(ValidationError):
            self._allocate(check, invoice, 500.0)

    def test_guarantee_check_cannot_allocate_or_post(self):
        invoice = self._invoice(500.0)
        check = self._create_incoming(amount=500.0, purpose="guarantee")
        with self.assertRaises(ValidationError):
            self._allocate(check, invoice, 500.0)
        check.action_receive()
        self.assertEqual(check.accounting_status, "not_applicable")
        self.assertFalse(check.payment_ids)

    def test_advance_without_entries_setting(self):
        self.company.check_advance_creates_entries = False
        check = self._create_incoming(amount=500.0, purpose="advance")
        check.action_receive()
        self.assertEqual(check.accounting_status, "not_applicable")

    def test_allocations_frozen_after_receive(self):
        invoice, other = self._invoice(1000.0), self._invoice(200.0)
        check = self._create_incoming(amount=1200.0)
        allocation = self._allocate(check, invoice, 1000.0)
        check.action_receive()
        with self.assertRaises(UserError):
            allocation.write({"amount": 900.0})
        with self.assertRaises(UserError):
            self._allocate(check, other, 200.0)

    # ------------------------------------------------------------------
    # Outgoing
    # ------------------------------------------------------------------
    def test_issue_settles_vendor_bill(self):
        bill = self._bill(500.0)
        check = self._create_outgoing(amount=500.0)
        self._allocate(check, bill, 500.0)
        check.action_issue()
        self.assertEqual(check.accounting_status, "posted")
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        payment = check.payment_ids
        self.assertEqual(payment.journal_id, self.bank_journal)
        self.assertEqual(payment.outstanding_account_id, self.company.check_payable_account_id)
        self.assertEqual(payment.payment_type, "outbound")

    def test_issue_blocked_on_journal_currency_mismatch(self):
        self.bank_journal.currency_id = self.eur
        check = self._create_outgoing(amount=500.0)
        with self.assertRaises(UserError):
            check.action_issue()

    # ------------------------------------------------------------------
    # Reversal, policy, idempotency and failure
    # ------------------------------------------------------------------
    def test_cancel_reverses_and_reopens_invoice(self):
        invoice = self._invoice(1000.0)
        check = self._create_incoming(amount=1000.0)
        self._allocate(check, invoice, 1000.0)
        check.action_receive()
        payment = check.payment_ids
        self._wizard(check, "cancel", user=self.check_manager, reason="Wrong customer").action_confirm()
        self.assertEqual(check.state, "cancelled")
        self.assertEqual(check.accounting_status, "reversed")
        self.assertEqual(payment.state, "canceled")
        self.assertTrue(payment.move_id.reversal_move_ids)
        self.assertEqual(payment.move_id.state, "posted", "Original entry is kept, not deleted")
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)
        self.assertFalse(check._has_accounting_entries())

    def test_return_reverses_entries(self):
        invoice = self._invoice(400.0)
        check = self._create_incoming(amount=400.0)
        self._allocate(check, invoice, 400.0)
        check.action_receive()
        self._wizard(check, "return", reason="Customer asked", recipient="Ahmed").action_confirm()
        self.assertEqual(check.accounting_status, "reversed")
        self.assertAlmostEqual(invoice.amount_residual, 400.0)

    def test_reset_to_draft_blocked_with_entries(self):
        check = self._create_incoming(amount=300.0)
        check.action_receive()
        with self.assertRaises(UserError):
            check.with_user(self.check_manager).action_reset_to_draft()

    def test_collection_policy_does_not_post_at_receipt(self):
        self.company.check_settlement_policy = "collection"
        invoice = self._invoice(500.0)
        check = self._create_incoming(amount=500.0)
        self._allocate(check, invoice, 500.0)
        check.action_receive()
        self.assertEqual(check.accounting_status, "none")
        self.assertFalse(check.payment_ids)
        self.assertAlmostEqual(invoice.amount_residual, 500.0)

    def test_posting_is_idempotent(self):
        check = self._create_incoming(amount=300.0)
        check.action_receive()
        check._post_check_accounting()
        self.assertEqual(len(check.payment_ids), 1)

    def test_accounting_failure_rolls_back_transition(self):
        invoice = self._invoice(500.0)
        check = self._create_incoming(amount=500.0)
        self._allocate(check, invoice, 500.0)
        with patch.object(
            type(self.env["check.check"]), "_reconcile_allocations",
            side_effect=UserError("Simulated accounting failure"),
        ):
            with self.assertRaises(UserError):
                check.action_receive()
        check.invalidate_recordset()
        invoice.invalidate_recordset()
        self.assertEqual(check.state, "draft")
        self.assertFalse(check.payment_ids)
        self.assertEqual(check.event_ids.mapped("event_type"), ["created"])
        self.assertAlmostEqual(invoice.amount_residual, 500.0)

    def test_check_user_without_accounting_rights_can_receive(self):
        user_env = self.env(user=self.check_user)
        check = self._create_incoming(env=user_env, amount=300.0)
        check.action_receive()
        self.assertEqual(check.accounting_status, "posted")
        self.assertEqual(check.sudo().payment_ids.create_uid, self.check_user)

    def test_non_accounting_user_can_read_posted_check(self):
        check = self._create_incoming(amount=300.0)
        check.action_receive()
        as_user = check.with_user(self.check_user)
        self.assertEqual(as_user.payment_count, 1)
        self.assertEqual(as_user.accounting_status, "posted")
        self.assertTrue(as_user._has_accounting_entries())
