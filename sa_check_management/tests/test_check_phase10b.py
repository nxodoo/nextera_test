from datetime import timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckPhase10B(CheckBankingCommon):

    def _rule(self, action):
        return self.env["check.action.rule"].create({"action": action})

    def _requests(self, check):
        return self.env["check.action.request"].search([("check_id", "=", check.id)])

    # ------------------------------------------------------------------
    # Sensitive actions need a second person
    # ------------------------------------------------------------------
    def test_without_rule_the_action_runs_directly(self):
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        self._wizard(check, "withdraw", user=self.check_manager, reason="Customer asked").action_confirm()
        self.assertEqual(check.state, "received")
        self.assertFalse(self._requests(check))

    def test_guarded_action_creates_a_request(self):
        self._rule("withdraw")
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        result = self._wizard(check, "withdraw", user=self.check_treasury, reason="Customer asked").action_confirm()
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(check.state, "under_collection", "Nothing runs before approval")
        request = self._requests(check)
        self.assertEqual((request.state, request.requested_by_id), ("pending", self.check_treasury))
        self.assertTrue(request.activity_ids, "Approvers are notified")
        self.assertTrue(check.pending_request_count)

    def test_guarded_action_cannot_bypass_the_request(self):
        self._rule("withdraw")
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        with self.assertRaises(UserError):
            check.with_user(self.check_manager)._apply_withdraw("Direct call")
        self.assertEqual(check.state, "under_collection")

    def test_approval_runs_the_action(self):
        self._rule("withdraw")
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        self._wizard(check, "withdraw", user=self.check_treasury, reason="Customer asked").action_confirm()
        request = self._requests(check)
        with self.assertRaises(AccessError):
            request.with_user(self.check_user).action_approve()
        request.with_user(self.check_manager).action_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.decided_by_id, self.check_manager)
        self.assertEqual(check.state, "received")
        event = check.event_ids.filtered(lambda e: e.event_type == "withdrawn")
        self.assertIn(request.name, event.note)
        self.assertEqual(event.user_id, self.check_manager)

    def test_requester_cannot_approve_own_request(self):
        self._rule("withdraw")
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        self._wizard(check, "withdraw", reason="Mine").action_confirm()  # the test user is a manager
        with self.assertRaises(UserError):
            self._requests(check).action_approve()

    def test_rejection_needs_a_note(self):
        self._rule("lose")
        check, _inv = self._received_check(500.0)
        self._wizard(check, "lose", user=self.check_treasury, reason="Lost by rep").action_confirm()
        request = self._requests(check).with_user(self.check_manager)
        with self.assertRaises(UserError):
            request.action_reject()
        request.decision_note = "Search the branch first"
        request.action_reject()
        self.assertEqual(request.state, "rejected")
        self.assertEqual(check.state, "received")

    def test_cancel_rule_spares_drafts(self):
        self._rule("cancel")
        draft = self._create_incoming(check_number=self._next_number())
        self._wizard(draft, "cancel", reason="Typo").action_confirm()
        self.assertEqual(draft.state, "cancelled")
        received, _inv = self._received_check(300.0)
        self._wizard(received, "cancel", user=self.check_treasury, reason="Wrong customer").action_confirm()
        self.assertEqual(received.state, "received")
        self.assertEqual(self._requests(received).action, "cancel")

    def test_one_pending_request_per_action(self):
        self._rule("lose")
        check, _inv = self._received_check(500.0)
        self._wizard(check, "lose", user=self.check_treasury, reason="Lost").action_confirm()
        with self.assertRaises(ValidationError):
            self._wizard(check, "lose", user=self.check_treasury, reason="Lost again").action_confirm()

    def test_reset_to_draft_through_request(self):
        self._rule("reset_draft")
        self.company.check_settlement_policy = "collection"
        check, _inv = self._received_check(300.0)
        self._wizard(check, "reset_draft", user=self.check_treasury, reason="Wrong bank").action_confirm()
        self.assertEqual(check.state, "received")
        self._requests(check).with_user(self.check_manager).action_approve()
        self.assertEqual(check.state, "draft")

    def test_release_guarantee_through_request_keeps_recipient(self):
        self._rule("release")
        check, _inv = self._received_check(3000.0, allocate=False, purpose="guarantee")
        self._wizard(check, "release", user=self.check_treasury, reason="Contract closed",
                     recipient="Client courier").action_confirm()
        self._requests(check).with_user(self.check_manager).action_approve()
        self.assertEqual(check.state, "returned")
        self.assertEqual(check.return_recipient, "Client courier")

    def test_check_user_cannot_request(self):
        self._rule("lose")
        check, _inv = self._received_check(500.0)
        with self.assertRaises(AccessError):
            self._wizard(check, "lose", user=self.check_user, reason="x").action_confirm()

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------
    def _manager_activities(self, record):
        return self.env["mail.activity"].search([
            ("res_model", "=", record._name), ("res_id", "=", record.id),
            ("user_id", "=", self.check_manager.id), ("summary", "ilike", "Escalation"),
        ])

    def test_old_bounce_is_escalated_once(self):
        check, _inv = self._received_check(500.0, due_date=self.today + timedelta(days=90))
        self._deposit(check)
        self._bounce(check)
        self.env["check.check"]._cron_check_reminders()
        self.assertFalse(self._manager_activities(check), "Not late yet")
        check.sudo().write({"last_bounce_date": self.today - timedelta(days=5)})
        self.env["check.check"]._cron_check_reminders()
        self.env["check.check"]._cron_check_reminders()
        self.assertEqual(len(self._manager_activities(check)), 1)

    def test_old_request_is_escalated(self):
        self._rule("lose")
        check, _inv = self._received_check(500.0)
        self._wizard(check, "lose", user=self.check_treasury, reason="Lost").action_confirm()
        request = self._requests(check)
        self.env.cr.execute("UPDATE check_action_request SET create_date = now() - interval '6 days' WHERE id = %s",
                            [request.id])
        request.invalidate_recordset(["create_date"])
        self.env["check.check"]._cron_check_reminders()
        self.assertTrue(self._manager_activities(request))

    # ------------------------------------------------------------------
    # Guarantee memorandum entries
    # ------------------------------------------------------------------
    def test_memorandum_for_incoming_guarantee(self):
        self.company.check_guarantee_memorandum = True
        check, _inv = self._received_check(5000.0, allocate=False, purpose="guarantee")
        memo = self._entries(check, "memorandum")
        self.assertEqual(set(memo.line_ids.account_id.mapped("account_type")), {"off_balance"})
        self.assertAlmostEqual(sum(memo.line_ids.filtered(lambda l: l.balance > 0).mapped("balance")), 5000.0)
        self._wizard(check, "release", user=self.check_manager, reason="Done", recipient="Client").action_confirm()
        self.assertTrue(memo.reversal_move_ids)
        self.assertFalse(check._active_entries(("memorandum",)))

    def test_invoked_guarantee_swaps_memorandum_for_real_entry(self):
        self.company.check_guarantee_memorandum = True
        check, _inv = self._received_check(2000.0, allocate=False, purpose="guarantee")
        self._wizard(check, "invoke", user=self.check_manager, reason="Default").action_confirm()
        self.assertFalse(check._active_entries(("memorandum",)))
        self.assertEqual(check.accounting_status, "posted")

    def test_memorandum_for_outgoing_guarantee(self):
        self.company.check_guarantee_memorandum = True
        check = self._create_outgoing(check_number=self._next_number(), amount=4000.0, purpose="guarantee")
        check.action_issue()
        self.assertTrue(self._entries(check, "memorandum"))
        self._wizard(check, "release", user=self.check_manager, reason="Tender closed", recipient="Courier").action_confirm()
        self.assertFalse(check._active_entries(("memorandum",)))

    def test_no_memorandum_when_disabled(self):
        check, _inv = self._received_check(5000.0, allocate=False, purpose="guarantee")
        self.assertFalse(self._entries(check, "memorandum"))

    # ------------------------------------------------------------------
    # Partner checks and statement
    # ------------------------------------------------------------------
    def test_partner_check_counter_and_statement(self):
        open_check, _inv = self._received_check(700.0)
        bounced, _inv = self._received_check(300.0)
        self._deposit(bounced)
        self._bounce(bounced)
        self._create_incoming(check_number=self._next_number())  # draft: not counted
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.sa_check_count, 2)
        wizard = self.env["check.partner.statement.wizard"].create({"partner_id": self.customer.id})
        sections = wizard._statement_sections()
        self.assertEqual(sections[0]["checks"], open_check)
        self.assertEqual(sections[1]["checks"], bounced)
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "sa_check_management.report_check_partner_statement", wizard.ids,
        )
        self.assertIn(open_check.check_number, html.decode())
        wizard.date_from = self.today + timedelta(days=1)
        wizard.date_to = self.today
        with self.assertRaises(UserError):
            wizard.action_print()
