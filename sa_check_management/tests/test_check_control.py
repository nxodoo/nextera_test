from datetime import timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, new_test_user, tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckControl(CheckBankingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Location = cls.env["check.location"]
        cls.safe = Location.create({"name": "Main Safe", "location_type": "safe"})
        cls.rep_location = Location.create({"name": "Rep Ahmed", "location_type": "person", "user_id": cls.check_user.id})
        cls.branch = Location.create({"name": "Alex Branch", "location_type": "branch"})
        cls.company.check_default_location_id = cls.safe

    # ------------------------------------------------------------------
    # Custody
    # ------------------------------------------------------------------
    def _handover(self, checks, origin, target, user=None):
        model = self.env["check.handover"]
        if user:
            model = model.with_user(user)
        return model.create({
            "check_ids": [(6, 0, checks.ids)],
            "from_location_id": origin.id,
            "to_location_id": target.id,
        })

    def test_received_check_starts_in_default_location(self):
        check, _inv = self._received_check(100.0)
        self.assertEqual(check.current_location_id, self.safe)

    def test_handover_waits_for_receiver(self):
        first, _inv = self._received_check(100.0)
        second, _inv = self._received_check(200.0)
        handover = self._handover(first | second, self.safe, self.rep_location)
        handover.action_send()
        self.assertEqual(handover.state, "pending")
        self.assertEqual(first.current_location_id, self.safe, "Custody moves only on acceptance")
        with self.assertRaises(AccessError):
            handover.with_user(self.check_treasury).action_accept()
        handover.with_user(self.check_user).action_accept()
        self.assertEqual(handover.state, "done")
        self.assertEqual(handover.accepted_by_id, self.check_user)
        for check in first | second:
            self.assertEqual(check.current_location_id, self.rep_location)
            self.assertEqual(check.current_holder_id, self.check_user)
            self.assertIn("handover", check.event_ids.mapped("event_type"))

    def test_location_without_holder_accepted_by_treasury(self):
        check, _inv = self._received_check(100.0)
        handover = self._handover(check, self.safe, self.branch)
        handover.action_send()
        with self.assertRaises(AccessError):
            handover.with_user(self.check_user).action_accept()
        handover.with_user(self.check_treasury).action_accept()
        self.assertEqual(check.current_location_id, self.branch)

    def test_refused_handover_keeps_custody(self):
        check, _inv = self._received_check(100.0)
        handover = self._handover(check, self.safe, self.rep_location)
        handover.action_send()
        with self.assertRaises(UserError):
            handover.with_user(self.check_user).action_reject()
        handover.with_user(self.check_user).write({"rejection_reason": "Amount differs from the list"})
        handover.with_user(self.check_user).action_reject()
        self.assertEqual(handover.state, "cancelled")
        self.assertEqual(check.current_location_id, self.safe)

    def test_handover_without_confirmation(self):
        self.company.check_handover_confirmation = False
        check, _inv = self._received_check(100.0)
        handover = self._handover(check, self.safe, self.branch)
        handover.action_send()
        self.assertEqual(handover.state, "done")
        self.assertEqual(check.current_location_id, self.branch)

    def test_handover_rules(self):
        held, _inv = self._received_check(100.0)
        with self.assertRaises(UserError):
            self._handover(held, self.branch, self.rep_location).action_send()
        deposited, _inv = self._received_check(100.0)
        self._deposit(deposited)
        with self.assertRaises(UserError):
            self._handover(deposited, self.safe, self.branch).action_send()
        self._handover(held, self.safe, self.rep_location).action_send()
        with self.assertRaises(UserError):
            self._handover(held, self.safe, self.branch).action_send()
        with self.assertRaises(ValidationError):
            self._handover(held, self.safe, self.safe)

    def test_custody_follows_bank_and_exit(self):
        check, _inv = self._received_check(100.0)
        self._deposit(check)
        self.assertEqual(check.current_location_id.location_type, "bank")
        self.assertEqual(check.current_location_id.journal_id, self.bank_journal)
        self._collect(check)
        self.assertFalse(check.current_location_id)

    def test_location_cannot_be_edited_after_receipt(self):
        check, _inv = self._received_check(100.0)
        with self.assertRaises(UserError):
            check.write({"current_location_id": self.branch.id})

    def test_done_handover_is_immutable(self):
        check, _inv = self._received_check(100.0)
        handover = self._handover(check, self.safe, self.branch)
        self.company.check_handover_confirmation = False
        handover.action_send()
        with self.assertRaises(UserError):
            handover.write({"to_location_id": self.rep_location.id})
        with self.assertRaises(UserError):
            handover.unlink()

    # ------------------------------------------------------------------
    # Checkbooks
    # ------------------------------------------------------------------
    def _checkbook(self, first=100001, last=100005, journal=None):
        book = self.env["check.book"].create({
            "journal_id": (journal or self.bank_journal).id,
            "first_number": first, "last_number": last, "padding": 6,
        })
        book.action_activate()
        return book

    def _leaf(self, book, number):
        return book.leaf_ids.filtered(lambda leaf: leaf.number == number)

    def test_activate_generates_leaves_and_requires_them(self):
        book = self._checkbook(1, 5)
        self.assertEqual(book.leaf_ids.mapped("number"), ["000001", "000002", "000003", "000004", "000005"])
        self.assertTrue(self.bank_journal.sa_check_require_leaf)
        with self.assertRaises(ValidationError):
            self.env["check.book"].create({"journal_id": self.bank_journal.id, "first_number": 4, "last_number": 9})

    def test_leaf_reserved_used_and_number_set(self):
        book = self._checkbook()
        leaf = self._leaf(book, "100001")
        check = self._create_outgoing(check_number="ignored", leaf_id=leaf.id)
        self.assertEqual(check.check_number, "100001")
        self.assertEqual((leaf.state, leaf.check_id), ("reserved", check))
        check.action_issue()
        self.assertEqual(leaf.state, "used")

    def test_leaf_selection_through_form(self):
        """The leaf fills the read-only check number in the browser before saving."""
        book = self._checkbook()
        model = self.env["check.check"].with_user(self.check_user).with_context(default_check_type="outgoing")
        with Form(model) as form:
            form.partner_id = self.vendor
            form.amount = 300.0
            form.due_date = self.today + timedelta(days=3)
            form.journal_id = self.bank_journal
            form.leaf_id = self._leaf(book, "100003")
            self.assertEqual(form.check_number, "100003")
            check = form.save()
        self.assertEqual(check.leaf_id.state, "reserved")

    def test_issue_requires_leaf_on_controlled_journal(self):
        self._checkbook()
        check = self._create_outgoing(check_number="999999")
        with self.assertRaises(UserError):
            check.action_issue()

    def test_leaf_cannot_be_reused(self):
        book = self._checkbook()
        leaf = self._leaf(book, "100002")
        self._create_outgoing(check_number="x", leaf_id=leaf.id)
        with self.assertRaises(ValidationError):
            self._create_outgoing(check_number="y", leaf_id=leaf.id)

    def test_changing_leaf_in_draft_releases_previous(self):
        book = self._checkbook()
        first, second = self._leaf(book, "100001"), self._leaf(book, "100002")
        check = self._create_outgoing(check_number="x", leaf_id=first.id)
        check.write({"leaf_id": second.id})
        self.assertEqual(first.state, "available")
        self.assertFalse(first.check_id)
        self.assertEqual(second.state, "reserved")
        self.assertEqual(check.check_number, "100002")

    def test_cancel_after_issue_voids_leaf_cancel_draft_releases_it(self):
        book = self._checkbook()
        issued_leaf, draft_leaf = self._leaf(book, "100001"), self._leaf(book, "100002")
        issued = self._create_outgoing(check_number="x", leaf_id=issued_leaf.id)
        issued.action_issue()
        self._wizard(issued, "cancel", user=self.check_manager, reason="Printing error").action_confirm()
        self.assertEqual(issued_leaf.state, "void")
        draft = self._create_outgoing(check_number="y", leaf_id=draft_leaf.id)
        self._wizard(draft, "cancel", reason="Not needed").action_confirm()
        self.assertEqual(draft_leaf.state, "available")
        self.assertFalse(draft.leaf_id)

    def test_mark_leaf_lost_or_damaged(self):
        book = self._checkbook()
        leaf, reserved = self._leaf(book, "100003"), self._leaf(book, "100004")
        with self.assertRaises(UserError):
            leaf.with_user(self.check_treasury).action_mark_lost()
        leaf.with_user(self.check_manager).action_mark_lost()
        self.assertEqual(leaf.state, "lost")
        self._create_outgoing(check_number="z", leaf_id=reserved.id)
        with self.assertRaises(UserError):
            reserved.with_user(self.check_manager).action_mark_damaged()

    def test_leaves_cannot_be_edited_directly(self):
        book = self._checkbook()
        with self.assertRaises(UserError):
            self._leaf(book, "100001").with_user(self.check_manager).write({"state": "available"})

    def test_close_checkbook_voids_unused_leaves(self):
        book = self._checkbook()
        book.action_close()
        self.assertEqual(set(book.leaf_ids.mapped("state")), {"void"})

    # ------------------------------------------------------------------
    # Approval matrix
    # ------------------------------------------------------------------
    def _approval_matrix(self):
        groups = {name: self.env["res.groups"].create({"name": f"Check Test {name}"}) for name in ("FM", "CFO", "GM")}
        users = {}
        for name, group in groups.items():
            users[name] = new_test_user(
                self.env, login=f"approver_{name.lower()}",
                groups="base.group_user,sa_check_management.group_check_user",
                company_id=self.company.id, company_ids=[(6, 0, self.company.ids)],
            )
            users[name].groups_id |= group
        Rule = self.env["check.approval.rule"]
        Rule.create({"name": "Finance Manager", "sequence": 10, "min_amount": 0.0, "group_id": groups["FM"].id})
        Rule.create({"name": "CFO", "sequence": 20, "min_amount": 50000.0, "group_id": groups["CFO"].id})
        Rule.create({"name": "General Manager", "sequence": 30, "min_amount": 500000.0, "group_id": groups["GM"].id})
        self.company.check_outgoing_approval_required = True
        return groups, users

    def _submitted(self, amount):
        check = self._create_outgoing(check_number=self._next_number(), amount=amount)
        check.action_submit()
        return check

    def test_stages_follow_amount(self):
        self._approval_matrix()
        self.assertEqual(len(self._submitted(30000.0).approval_line_ids), 1)
        self.assertEqual(len(self._submitted(100000.0).approval_line_ids), 2)
        self.assertEqual(
            self._submitted(600000.0).approval_line_ids.mapped("name"),
            ["Finance Manager", "CFO", "General Manager"],
        )

    def test_stages_are_approved_in_order(self):
        _groups, users = self._approval_matrix()
        check = self._submitted(100000.0)
        self.assertEqual(check.approval_stage, "Finance Manager")
        with self.assertRaises(AccessError):
            check.with_user(users["CFO"]).action_approve()
        check.with_user(users["FM"]).action_approve()
        self.assertEqual(check.state, "pending_approval")
        self.assertEqual(check.approval_stage, "CFO")
        check.with_user(users["CFO"]).action_approve()
        self.assertEqual(check.state, "approved")
        self.assertEqual(check.approved_by_id, users["CFO"])
        self.assertEqual(check.approval_line_ids.mapped("state"), ["approved", "approved"])

    def test_one_person_cannot_approve_two_stages(self):
        groups, users = self._approval_matrix()
        users["FM"].groups_id |= groups["CFO"]
        check = self._submitted(100000.0)
        check.with_user(users["FM"]).action_approve()
        with self.assertRaises(UserError):
            check.with_user(users["FM"]).action_approve()

    def test_reject_at_second_stage(self):
        _groups, users = self._approval_matrix()
        check = self._submitted(100000.0)
        check.with_user(users["FM"]).action_approve()
        self._wizard(check, "reject", user=users["CFO"], reason="Budget exceeded").action_confirm()
        self.assertEqual(check.state, "draft")
        self.assertEqual(check.rejection_reason, "Budget exceeded")
        self.assertEqual(check.approval_line_ids.mapped("state"), ["approved", "rejected"])

    def test_resubmission_starts_a_new_round(self):
        _groups, users = self._approval_matrix()
        check = self._submitted(30000.0)
        self._wizard(check, "reject", user=users["FM"], reason="Wrong vendor").action_confirm()
        check.action_submit()
        current = check.approval_line_ids.filtered(lambda line: line.round == 2)
        self.assertEqual(current.state, "pending")
        check.with_user(users["FM"]).action_approve()
        self.assertEqual(check.state, "approved")

    def test_cancel_pending_check_cancels_its_stages(self):
        self._approval_matrix()
        check = self._submitted(30000.0)
        self._wizard(check, "cancel", user=self.check_manager, reason="Not needed").action_confirm()
        self.assertEqual(check.approval_line_ids.state, "cancelled")
