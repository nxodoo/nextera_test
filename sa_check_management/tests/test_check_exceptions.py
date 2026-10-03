from datetime import timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckExceptions(CheckBankingCommon):

    def _bounced_check(self, amount=1000.0):
        check, invoice = self._received_check(amount)
        self._deposit(check)
        self._bounce(check)
        return check, invoice

    def _replace(self, check, user=None, **vals):
        model = self.env["check.replacement.wizard"]
        if user:
            model = model.with_user(user)
        vals.setdefault("check_number", self._next_number())
        wizard = model.with_context(default_check_id=check.id).create(vals)
        return self.env["check.check"].browse(wizard.action_confirm()["res_id"])

    def _settle(self, check, note="Paid cash at branch", user=None):
        model = self.env["check.settle.wizard"]
        if user:
            model = model.with_user(user)
        model.with_context(default_check_id=check.id).create({"note": note}).action_confirm()

    def _legal(self, check, case_number="CASE-77"):
        self.env["check.legal.wizard"].with_context(default_check_id=check.id).create({
            "case_number": case_number, "court": "Cairo Economic Court",
        }).action_confirm()

    def _issued_outgoing(self, amount=500.0, **overrides):
        bill = self._bill(amount)
        check = self._create_outgoing(check_number=self._next_number(), amount=amount, **overrides)
        self._allocate(check, bill, amount)
        check.action_issue()
        return check, bill

    # ------------------------------------------------------------------
    # Replacement (incoming)
    # ------------------------------------------------------------------
    def test_replace_bounced_check(self):
        old, invoice = self._bounced_check(1000.0)
        new = self._replace(old)
        self.assertEqual(old.state, "replaced")
        self.assertEqual(old.replaced_by_check_id, new)
        self.assertEqual(new.replaces_check_id, old)
        self.assertEqual(new.state, "received")
        self.assertEqual(new.partner_id, old.partner_id)
        self.assertAlmostEqual(new.allocated_amount, 1000.0)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertIn("replaced", old.event_ids.mapped("event_type"))
        self.assertIn("replaced", new.event_ids.mapped("event_type"))

    def test_replace_received_check_reverses_old_entries(self):
        old, invoice = self._received_check(800.0)
        old_payment = old.payment_ids
        new = self._replace(old)
        self.assertEqual(old.accounting_status, "reversed")
        self.assertEqual(old_payment.state, "canceled")
        self.assertEqual(new.accounting_status, "posted")
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_replacement_with_smaller_amount_leaves_invoice_open(self):
        old, invoice = self._bounced_check(1000.0)
        new = self._replace(old, amount=600.0)
        self.assertAlmostEqual(new.allocated_amount, 600.0)
        self.assertAlmostEqual(invoice.amount_residual, 400.0)

    def test_replacement_with_larger_amount_keeps_unallocated(self):
        old, invoice = self._bounced_check(1000.0)
        new = self._replace(old, amount=1200.0)
        self.assertAlmostEqual(new.unallocated_amount, 200.0)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_replacement_without_allocation_transfer(self):
        old, invoice = self._bounced_check(1000.0)
        new = self._replace(old, transfer_allocations=False)
        self.assertFalse(new.allocation_ids)
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)

    def test_replacement_can_stay_draft(self):
        old, _invoice = self._bounced_check(500.0)
        new = self._replace(old, receive_now=False)
        self.assertEqual(new.state, "draft")
        self.assertTrue(new.allocation_ids)

    def test_replacement_chain_cannot_loop(self):
        first, _inv = self._bounced_check(500.0)
        second = self._replace(first)
        with self.assertRaises(ValidationError):
            first.sudo().write({"replaces_check_id": second.id})
        with self.assertRaises(ValidationError):
            second.sudo().write({"replaces_check_id": second.id})

    def test_cannot_replace_draft_or_collected_check(self):
        draft = self._create_incoming(check_number=self._next_number(), amount=100.0)
        with self.assertRaises(UserError):
            self._replace(draft)
        collected, _inv = self._received_check(100.0)
        self._deposit(collected)
        self._collect(collected)
        with self.assertRaises(UserError):
            self._replace(collected)

    # ------------------------------------------------------------------
    # Settlement and legal action
    # ------------------------------------------------------------------
    def test_settle_bounced_check(self):
        check, invoice = self._bounced_check(700.0)
        self._settle(check)
        self.assertEqual(check.state, "settled")
        self.assertEqual(check.settled_date, self.today)
        self.assertEqual(check.settle_note, "Paid cash at branch")
        self.assertAlmostEqual(invoice.amount_residual, 700.0, msg="Settlement is recorded by its own payment")

    def test_settle_requires_note(self):
        check, _inv = self._bounced_check(700.0)
        with self.assertRaises(UserError):
            self._settle(check, note="   ")

    def test_legal_then_settle_or_return(self):
        first, _inv = self._bounced_check(900.0)
        self._legal(first)
        self.assertEqual(first.state, "legal")
        self.assertEqual(first.legal_case_number, "CASE-77")
        self._settle(first, note="Court settlement")
        self.assertEqual(first.state, "settled")
        second, _inv = self._bounced_check(400.0)
        self._legal(second, case_number="CASE-78")
        self._wizard(second, "return", reason="Case dropped", recipient="Customer lawyer").action_confirm()
        self.assertEqual(second.state, "returned")

    def test_legal_requires_bounced_check(self):
        check, _inv = self._received_check(300.0)
        with self.assertRaises(UserError):
            self._legal(check)

    # ------------------------------------------------------------------
    # Lost incoming check
    # ------------------------------------------------------------------
    def test_lost_check_requires_manager_and_reopens_invoice(self):
        check, invoice = self._received_check(500.0)
        with self.assertRaises(AccessError):
            self._wizard(check, "lose", user=self.check_treasury, reason="Lost by rep").action_confirm()
        self._wizard(check, "lose", user=self.check_manager, reason="Lost by rep").action_confirm()
        self.assertEqual(check.state, "lost")
        self.assertEqual(check.lost_reason, "Lost by rep")
        self.assertEqual(check.accounting_status, "reversed")
        self.assertAlmostEqual(invoice.amount_residual, 500.0)

    # ------------------------------------------------------------------
    # Outgoing: stop payment, bank rejection, replacement, stale
    # ------------------------------------------------------------------
    def test_stop_payment_requires_reference_and_reopens_bill(self):
        check, bill = self._issued_outgoing()
        self._wizard(check, "deliver", recipient="Vendor rep").action_confirm()
        with self.assertRaises(UserError):
            self._wizard(check, "stop", reason="Vendor dispute").action_confirm()
        self._wizard(check, "stop", reason="Vendor dispute", reference="STOP-1").action_confirm()
        self.assertEqual(check.state, "stopped")
        self.assertEqual(check.stop_reference, "STOP-1")
        self.assertAlmostEqual(bill.amount_residual, 500.0)
        with self.assertRaises(UserError):
            check._apply_clear(self.today)

    def test_bank_rejects_outgoing_check(self):
        check, bill = self._issued_outgoing()
        self.env["check.bounce.wizard"].with_context(default_check_id=check.id).create({
            "reason_id": self.reason_funds.id, "fee_amount": 25.0,
        }).action_confirm()
        self.assertEqual(check.state, "rejected")
        self.assertEqual(check.bounce_count, 1)
        self.assertAlmostEqual(bill.amount_residual, 500.0)
        fee = self._entries(check, "fee")
        self.assertEqual(fee.line_ids.filtered(lambda l: l.balance > 0).account_id, self.company.check_fee_account_id)

    def test_replace_rejected_outgoing_check(self):
        check, bill = self._issued_outgoing()
        self.env["check.bounce.wizard"].with_context(default_check_id=check.id).create({
            "reason_id": self.reason_funds.id,
        }).action_confirm()
        new = self._replace(check)
        self.assertEqual(check.state, "replaced")
        self.assertEqual(new.check_type, "outgoing")
        self.assertEqual(new.state, "draft")
        self.assertEqual(new.journal_id, check.journal_id)
        new.action_issue()
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))

    def test_settle_rejected_outgoing_check(self):
        check, _bill = self._issued_outgoing()
        self.env["check.bounce.wizard"].with_context(default_check_id=check.id).create({
            "reason_id": self.reason_funds.id,
        }).action_confirm()
        self._settle(check, note="Paid by bank transfer")
        self.assertEqual(check.state, "settled")

    def test_stale_outgoing_check(self):
        old_date = self.today - timedelta(days=250)
        stale, bill = self._issued_outgoing(issue_date=old_date, due_date=old_date + timedelta(days=5))
        fresh, _bill = self._issued_outgoing()
        self.assertTrue(stale.is_stale)
        self.assertFalse(fresh.is_stale)
        found = self.env["check.check"].search([("is_stale", "=", True), ("id", "in", (stale | fresh).ids)])
        self.assertEqual(found, stale)
        with self.assertRaises(UserError):
            self._wizard(fresh, "void_stale", user=self.check_manager, reason="x").action_confirm()
        with self.assertRaises(AccessError):
            self._wizard(stale, "void_stale", user=self.check_treasury, reason="Expired").action_confirm()
        self._wizard(stale, "void_stale", user=self.check_manager, reason="Expired").action_confirm()
        self.assertEqual(stale.state, "cancelled")
        self.assertAlmostEqual(bill.amount_residual, 500.0)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    def test_treasury_without_accounting_rights_handles_exceptions(self):
        old, invoice = self._bounced_check(600.0)
        new = self._replace(old, user=self.check_treasury)
        self.assertEqual(new.state, "received")
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        other, _inv = self._bounced_check(300.0)
        self._settle(other, user=self.check_treasury)
        self.assertEqual(other.state, "settled")

    def test_check_user_cannot_replace(self):
        old, _inv = self._bounced_check(300.0)
        with self.assertRaises(AccessError):
            self._replace(old, user=self.check_user)
