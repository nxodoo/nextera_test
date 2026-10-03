from datetime import timedelta

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from .common import CheckCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckCore(CheckCommon):

    # ------------------------------------------------------------------
    # Creation, direction and sequence
    # ------------------------------------------------------------------
    def test_incoming_created_from_menu_context(self):
        check = self._create_incoming()
        self.assertEqual(check.check_type, "incoming")
        self.assertEqual(check.state, "draft")
        self.assertTrue(check.name.startswith("CHK/IN/"))
        self.assertEqual(check.event_ids.mapped("event_type"), ["created"])

    def test_outgoing_created_from_menu_context(self):
        check = self._create_outgoing()
        self.assertEqual(check.check_type, "outgoing")
        self.assertTrue(check.name.startswith("CHK/OUT/"))
        self.assertEqual(check.bank_account_id, self.bank_journal.bank_account_id)

    def test_create_without_direction_is_blocked(self):
        with self.assertRaises(UserError):
            self.Check.create(self._incoming_vals())

    def test_reference_and_check_number_are_separate(self):
        check = self._create_incoming(check_number="  0007  ")
        self.assertEqual(check.check_number, "0007", "Leading zeros kept, whitespace stripped")
        self.assertNotEqual(check.name, check.check_number)
        self.assertEqual(check.display_name, f"{check.name} (0007)")

    def test_direction_cannot_change(self):
        check = self._create_incoming()
        with self.assertRaises(UserError):
            check.write({"check_type": "outgoing"})

    def test_company_amount_same_currency(self):
        check = self._create_incoming(amount=250000.0)
        self.assertEqual(check.company_amount, 250000.0)

    # ------------------------------------------------------------------
    # Validations
    # ------------------------------------------------------------------
    @mute_logger("odoo.sql_db")
    def test_amount_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            self._create_incoming(amount=0.0)

    def test_due_date_not_before_issue_date(self):
        with self.assertRaises(ValidationError):
            self._create_incoming(due_date=self.today - timedelta(days=1))

    def test_drawer_name_required_for_third_party(self):
        with self.assertRaises(ValidationError):
            self._create_incoming(drawer_is_partner=False)
        check = self._create_incoming(drawer_is_partner=False, drawer_name="Third Party")
        self.assertEqual(check.drawer_name, "Third Party")

    def test_incoming_duplicate_blocked_in_same_scope(self):
        self._create_incoming()
        with self.assertRaises(ValidationError):
            self._create_incoming()

    def test_incoming_duplicate_allowed_in_other_scope(self):
        self._create_incoming()
        other_bank = self._create_incoming(bank_id=self.bank_nbe.id)
        other_account = self._create_incoming(drawer_account_number="ACC-2")
        self.assertTrue(other_bank and other_account)

    def test_incoming_duplicate_allowed_when_approved(self):
        self._create_incoming()
        check = self._create_incoming(duplicate_approved=True)
        self.assertTrue(check.duplicate_approved)

    def test_outgoing_duplicate_blocked_per_journal(self):
        self._create_outgoing()
        with self.assertRaises(ValidationError):
            self._create_outgoing()

    # ------------------------------------------------------------------
    # State and locking
    # ------------------------------------------------------------------
    def test_direct_state_write_blocked(self):
        check = self._create_incoming()
        with self.assertRaises(UserError):
            check.write({"state": "received"})

    def test_set_state_logs_event(self):
        check = self._create_incoming()
        check._set_state("received", event_type="received", note="Received at branch")
        self.assertEqual(check.state, "received")
        event = check.event_ids.filtered(lambda e: e.event_type == "received")
        self.assertEqual((event.old_state, event.new_state), ("draft", "received"))
        self.assertEqual(event.note, "Received at branch")

    def test_set_state_rejects_other_direction(self):
        check = self._create_incoming()
        with self.assertRaises(UserError):
            check._set_state("issued")

    def test_locked_fields_after_draft(self):
        check = self._create_incoming()
        check._set_state("received")
        with self.assertRaises(UserError):
            check.write({"amount": 2000.0})
        check.write({"reference": "Allowed edit"})
        self.assertEqual(check.reference, "Allowed edit")

    def test_archive_only_draft_or_closed(self):
        check = self._create_incoming()
        check._set_state("received")
        with self.assertRaises(UserError):
            check.action_archive()
        check._set_state("cancelled")
        check.action_archive()
        self.assertFalse(check.active)

    def test_copy_blocked(self):
        check = self._create_incoming()
        with self.assertRaises(UserError):
            check.copy()

    def test_unlink_only_draft(self):
        draft = self._create_incoming(check_number="D-1")
        draft.unlink()
        self.assertFalse(draft.exists())
        received = self._create_incoming(check_number="D-2")
        received._set_state("received")
        with self.assertRaises(UserError):
            received.unlink()

    # ------------------------------------------------------------------
    # History immutability
    # ------------------------------------------------------------------
    def test_events_are_immutable(self):
        event = self._create_incoming().event_ids
        with self.assertRaises(UserError):
            event.write({"note": "tampered"})
        with self.assertRaises(UserError):
            event.unlink()

    # ------------------------------------------------------------------
    # Access rights and companies
    # ------------------------------------------------------------------
    def test_user_can_create_but_not_delete(self):
        user_env = self.env(user=self.check_user)
        check = self._create_incoming(env=user_env)
        self.assertEqual(check.event_ids.user_id, self.check_user)
        with self.assertRaises(AccessError):
            check.unlink()

    def test_user_cannot_create_events_directly(self):
        check = self._create_incoming()
        with self.assertRaises(AccessError):
            self.env["check.event"].with_user(self.check_user).create({
                "check_id": check.id, "event_type": "correction",
            })

    def test_auditor_read_only(self):
        check = self._create_incoming()
        self.assertEqual(check.with_user(self.check_auditor).name, check.name)
        with self.assertRaises(AccessError):
            self._create_incoming(env=self.env(user=self.check_auditor), check_number="A-1")

    def test_other_company_cannot_see_checks(self):
        check = self._create_incoming()
        other_company = self.env["res.company"].create({"name": "Other Check Co"})
        outsider = new_test_user(
            self.env, login="check_outsider",
            groups="base.group_user,sa_check_management.group_check_user",
            company_id=other_company.id, company_ids=[(6, 0, other_company.ids)],
        )
        visible = self.env["check.check"].with_user(outsider).search([("id", "=", check.id)])
        self.assertFalse(visible)
