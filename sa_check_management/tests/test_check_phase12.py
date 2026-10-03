import base64
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckPhase12(CheckBankingCommon):

    # ------------------------------------------------------------------
    # Checkbook leaf import
    # ------------------------------------------------------------------
    def _list_book(self):
        return self.env["check.book"].create({"journal_id": self.bank_journal.id, "generation": "list"})

    def _import(self, book, numbers=None, file_content=None, filename=None):
        vals = {"numbers": numbers}
        if file_content:
            vals.update({"file": base64.b64encode(file_content.encode()), "filename": filename})
        action = book.action_open_leaf_import()
        wizard = self.env["check.book.import.wizard"].with_context(**action["context"]).create(vals)
        wizard.action_import()

    def test_import_leaves_from_text_and_file(self):
        book = self._list_book()
        self._import(book, numbers="A-100\nA-105, A-200;A-105",
                     file_content="number\nA-300\nA-301\n", filename="leaves.csv")
        self.assertEqual(book.leaf_ids.mapped("number"), ["A-100", "A-105", "A-200", "A-300", "A-301"])
        book.action_activate()
        self.assertEqual(book.state, "active")
        self.assertTrue(self.bank_journal.sa_check_require_leaf)
        leaf = book.leaf_ids.filtered(lambda l: l.number == "A-200")
        check = self._create_outgoing(check_number="x", leaf_id=leaf.id)
        self.assertEqual(check.check_number, "A-200")
        check.action_issue()
        self.assertEqual(leaf.state, "used")

    def test_list_book_needs_leaves_before_use(self):
        with self.assertRaises(UserError):
            self._list_book().action_activate()

    def test_imported_number_cannot_exist_twice_for_the_bank(self):
        first = self._list_book()
        self._import(first, numbers="B-1\nB-2")
        with self.assertRaises(UserError):
            self._import(self._list_book(), numbers="B-2\nB-3")

    def test_range_books_do_not_import(self):
        book = self.env["check.book"].create({"journal_id": self.bank_journal.id, "first_number": 1, "last_number": 3})
        with self.assertRaises(UserError):
            book._import_leaves(["X-1"])

    def test_import_needs_numbers(self):
        with self.assertRaises(UserError):
            self._import(self._list_book(), numbers="  ")

    def test_list_books_skip_range_rules(self):
        range_book = self.env["check.book"].create({"journal_id": self.bank_journal.id, "first_number": 1,
                                                    "last_number": 5})
        range_book.action_activate()
        book = self._list_book()
        self.assertFalse(book.first_number, "No range is needed for an imported list")
        with self.assertRaises(UserError):
            self._import(book, numbers="000003")  # already a leaf of the range book
        self._import(book, numbers="C-9")
        book.action_activate()
        self.assertEqual(book.leaf_ids.number, "C-9")

    # ------------------------------------------------------------------
    # Outgoing check past due and not cleared
    # ------------------------------------------------------------------
    def _activities(self, record, user):
        return self.env["mail.activity"].search([
            ("res_model", "=", record._name), ("res_id", "=", record.id), ("user_id", "=", user.id),
        ])

    def test_past_due_outgoing_check_is_reminded_once(self):
        past = self.today - timedelta(days=1)
        check = self._create_outgoing(check_number=self._next_number(), amount=300.0,
                                      issue_date=past - timedelta(days=5), due_date=past)
        check.action_issue()
        fresh = self._create_outgoing(check_number=self._next_number(), amount=300.0,
                                      due_date=self.today + timedelta(days=10))
        fresh.action_issue()
        self.env["check.check"]._cron_check_reminders()
        self.env["check.check"]._cron_check_reminders()
        activities = self._activities(check, check.responsible_user_id).filtered(
            lambda a: "past due" in (a.summary or ""))
        self.assertEqual(len(activities), 1)
        self.assertFalse(self._activities(fresh, fresh.responsible_user_id).filtered(
            lambda a: "past due" in (a.summary or "")))

    def test_cleared_or_guarantee_checks_are_not_reminded(self):
        past = self.today - timedelta(days=1)
        guarantee = self._create_outgoing(check_number=self._next_number(), amount=300.0, purpose="guarantee",
                                          issue_date=past - timedelta(days=5), due_date=past)
        guarantee.action_issue()
        self.env["check.check"]._cron_check_reminders()
        self.assertFalse(self._activities(guarantee, guarantee.responsible_user_id).filtered(
            lambda a: "past due" in (a.summary or "")))

    def test_long_past_due_outgoing_check_is_escalated(self):
        old = self.today - timedelta(days=10)
        check = self._create_outgoing(check_number=self._next_number(), amount=300.0,
                                      issue_date=old - timedelta(days=5), due_date=old)
        check.action_issue()
        self.env["check.check"]._cron_check_reminders()
        escalation = self._activities(check, self.check_manager).filtered(lambda a: "Escalation" in (a.summary or ""))
        self.assertEqual(len(escalation), 1)

    # ------------------------------------------------------------------
    # Bounce Analysis
    # ------------------------------------------------------------------
    def test_bounce_analysis_covers_every_check_that_bounced(self):
        redeposited, _inv = self._received_check(400.0)
        self._deposit(redeposited)
        self._bounce(redeposited)
        self._deposit(redeposited)
        self._collect(redeposited)
        open_bounce, _inv = self._received_check(250.0)
        self._deposit(open_bounce)
        self._bounce(open_bounce, reason=self.reason_other, note="Signature")
        never, _inv = self._received_check(100.0)
        action = self.env["ir.actions.act_window"]._for_xml_id("sa_check_management.action_check_bounce_analysis")
        found = self.env["check.check"].search(safe_eval(action["domain"]))
        self.assertIn(redeposited, found, "Collected later, but it bounced once")
        self.assertIn(open_bounce, found)
        self.assertNotIn(never, found)
        groups = self.env["check.check"]._read_group(
            [("id", "in", (redeposited | open_bounce).ids)], ["last_bounce_reason_id"], ["company_amount:sum"],
        )
        self.assertEqual({reason.code: amount for reason, amount in groups}, {"insufficient_funds": 400.0, "other": 250.0})
        pivot = self.env["check.check"].get_views([(self.env.ref("sa_check_management.check_check_view_pivot_bounce").id, "pivot")])
        self.assertIn("last_bounce_reason_id", pivot["views"]["pivot"]["arch"])
