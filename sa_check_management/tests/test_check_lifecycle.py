from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CheckCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckLifecycle(CheckCommon):

    def _event_types(self, check):
        return check.event_ids.sorted("id").mapped("event_type")

    def _approved_outgoing(self, **overrides):
        check = self._create_outgoing(**overrides)
        check.action_submit()
        check.with_user(self.check_approver).action_approve()
        return check

    # ------------------------------------------------------------------
    # Incoming
    # ------------------------------------------------------------------
    def test_receive_sets_state_date_and_event(self):
        check = self._create_incoming()
        check.action_receive()
        self.assertEqual(check.state, "received")
        self.assertEqual(check.received_date, self.today)
        event = check.event_ids.filtered(lambda e: e.event_type == "received")
        self.assertEqual((event.old_state, event.new_state), ("draft", "received"))

    def test_receive_requires_bank(self):
        check = self._create_incoming(bank_id=False)
        with self.assertRaises(UserError):
            check.action_receive()
        self.assertEqual(check.state, "draft")

    def test_receive_twice_is_rejected(self):
        check = self._create_incoming()
        check.action_receive()
        with self.assertRaises(UserError):
            check.action_receive()
        self.assertEqual(self._event_types(check), ["created", "received", "accounting"])

    def test_action_from_other_direction_is_rejected(self):
        incoming = self._create_incoming()
        outgoing = self._create_outgoing()
        with self.assertRaises(UserError):
            incoming._transition("issue")
        with self.assertRaises(UserError):
            outgoing._transition("receive")

    def test_return_requires_reason_and_recipient(self):
        check = self._create_incoming()
        check.action_receive()
        with self.assertRaises(UserError):
            self._wizard(check, "return", recipient="Ahmed").action_confirm()
        with self.assertRaises(UserError):
            self._wizard(check, "return", reason="Customer request").action_confirm()
        self.assertEqual(check.state, "received")

    def test_return_received_check(self):
        check = self._create_incoming()
        check.action_receive()
        self._wizard(
            check, "return", reason="Customer request", recipient="Ahmed Ali",
            attachment="ZXZpZGVuY2U=", attachment_name="receipt.txt",
        ).action_confirm()
        self.assertEqual(check.state, "returned")
        self.assertEqual(check.return_recipient, "Ahmed Ali")
        self.assertEqual(check.returned_date, self.today)
        self.assertIn("Ahmed Ali", check.event_ids.filtered(lambda e: e.event_type == "returned").note)
        attachment = self.env["ir.attachment"].search([
            ("res_model", "=", "check.check"), ("res_id", "=", check.id),
        ])
        self.assertEqual(attachment.name, "receipt.txt")

    def test_return_from_draft_is_rejected(self):
        check = self._create_incoming()
        with self.assertRaises(UserError):
            self._wizard(check, "return", reason="x", recipient="y").action_confirm()

    def test_wizard_rejects_future_date(self):
        check = self._create_incoming()
        check.action_receive()
        wizard = self._wizard(
            check, "return", reason="x", recipient="y",
            action_date=self.today + timedelta(days=1),
        )
        with self.assertRaises(UserError):
            wizard.action_confirm()

    # ------------------------------------------------------------------
    # Cancel and reset
    # ------------------------------------------------------------------
    def test_user_can_cancel_draft(self):
        check = self._create_incoming(env=self.env(user=self.check_user))
        self._wizard(check, "cancel", user=self.check_user, reason="Wrong entry").action_confirm()
        self.assertEqual(check.state, "cancelled")
        self.assertEqual(check.cancel_reason, "Wrong entry")
        self.assertEqual(check.cancelled_date, self.today)

    def test_cancel_after_draft_requires_manager(self):
        check = self._create_incoming()
        check.action_receive()
        with self.assertRaises(AccessError):
            self._wizard(check, "cancel", user=self.check_user, reason="x").action_confirm()
        self._wizard(check, "cancel", user=self.check_manager, reason="Voided").action_confirm()
        self.assertEqual(check.state, "cancelled")

    def test_cancel_requires_reason(self):
        check = self._create_incoming()
        with self.assertRaises(UserError):
            self._wizard(check, "cancel", reason="   ").action_confirm()

    def test_cancel_delivered_outgoing_is_rejected(self):
        check = self._approved_outgoing()
        check.action_issue()
        self._wizard(check, "deliver", recipient="Vendor rep").action_confirm()
        with self.assertRaises(UserError):
            self._wizard(check, "cancel", reason="x").action_confirm()

    def test_reset_received_to_draft(self):
        # Without accounting entries (settlement at collection) a received check can be reset.
        self.env.company.check_settlement_policy = "collection"
        check = self._create_incoming()
        check.action_receive()
        with self.assertRaises(AccessError):
            check.with_user(self.check_user).action_reset_to_draft()
        check.with_user(self.check_manager).action_reset_to_draft()
        self.assertEqual(check.state, "draft")
        self.assertFalse(check.received_date)
        check.write({"amount": 1500.0})
        self.assertEqual(check.amount, 1500.0)

    def test_auditor_cannot_run_actions(self):
        check = self._create_incoming()
        with self.assertRaises(AccessError):
            check.with_user(self.check_auditor).action_receive()

    # ------------------------------------------------------------------
    # Outgoing and approval
    # ------------------------------------------------------------------
    def test_outgoing_full_flow(self):
        check = self._create_outgoing()
        check.action_submit()
        self.assertEqual(check.state, "pending_approval")
        self.assertEqual(check.submitted_by_id, self.env.user)
        check.with_user(self.check_approver).action_approve()
        self.assertEqual(check.state, "approved")
        self.assertEqual(check.approved_by_id, self.check_approver)
        check.action_issue()
        self.assertEqual((check.state, check.issued_date), ("issued", self.today))
        self._wizard(check, "deliver", recipient="Vendor rep", note="At our office").action_confirm()
        self.assertEqual(check.state, "delivered")
        self.assertEqual(check.delivery_recipient, "Vendor rep")
        self.assertEqual(
            self._event_types(check),
            ["created", "approval", "approval", "issued", "accounting", "delivered"],
        )

    def test_creator_cannot_approve_own_check(self):
        self.env.user.groups_id |= self.env.ref("sa_check_management.group_check_approver")
        check = self._create_outgoing()
        check.action_submit()
        with self.assertRaises(UserError):
            check.action_approve()
        self.assertEqual(check.state, "pending_approval")

    def test_creator_can_approve_without_segregation(self):
        self.env.company.check_approval_segregation = False
        self.env.user.groups_id |= self.env.ref("sa_check_management.group_check_approver")
        check = self._create_outgoing()
        check.action_submit()
        check.action_approve()
        self.assertEqual(check.state, "approved")

    def test_user_cannot_approve(self):
        check = self._create_outgoing()
        check.action_submit()
        with self.assertRaises(AccessError):
            check.with_user(self.check_user).action_approve()

    def test_issue_from_draft_needs_approval_when_required(self):
        check = self._create_outgoing()
        with self.assertRaises(UserError):
            check.action_issue()

    def test_issue_from_draft_without_approval_policy(self):
        self.env.company.check_outgoing_approval_required = False
        check = self._create_outgoing()
        check.action_issue()
        self.assertEqual(check.state, "issued")

    def test_submit_blocked_when_approval_not_required(self):
        self.env.company.check_outgoing_approval_required = False
        check = self._create_outgoing()
        with self.assertRaises(UserError):
            check.action_submit()

    def test_issue_requires_journal(self):
        self.env.company.check_outgoing_approval_required = False
        check = self._create_outgoing(journal_id=False)
        with self.assertRaises(UserError):
            check.action_issue()

    def test_reject_returns_to_draft_with_reason(self):
        check = self._create_outgoing()
        check.action_submit()
        with self.assertRaises(UserError):
            self._wizard(check, "reject", user=self.check_approver).action_confirm()
        self._wizard(check, "reject", user=self.check_approver, reason="Amount too high").action_confirm()
        self.assertEqual(check.state, "draft")
        self.assertEqual(check.rejection_reason, "Amount too high")

    def test_approved_check_is_locked(self):
        check = self._approved_outgoing()
        with self.assertRaises(UserError):
            check.write({"amount": 900.0})

    def test_reset_approved_clears_approval(self):
        check = self._approved_outgoing()
        check.with_user(self.check_manager).action_reset_to_draft()
        self.assertEqual(check.state, "draft")
        self.assertFalse(check.approved_by_id)
        self.assertFalse(check.submitted_by_id)
