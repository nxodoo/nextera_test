import base64
import io
from datetime import timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckPhase9Core(CheckBankingCommon):

    # ------------------------------------------------------------------
    # Duplicate prevention (point 7)
    # ------------------------------------------------------------------
    def test_drawer_account_is_required_on_incoming(self):
        with self.assertRaises(ValidationError):
            self._create_incoming(check_number=self._next_number(), drawer_account_number=False)

    def test_duplicates_detected_whatever_the_typing(self):
        self._create_incoming(check_number="000123", drawer_account_number="1000-2345")
        with self.assertRaises(ValidationError):
            self._create_incoming(check_number="123", drawer_account_number="10002345")
        with self.assertRaises(ValidationError):
            self._create_incoming(check_number=" 0123 ", drawer_account_number="1000 2345")

    # ------------------------------------------------------------------
    # Legal cases stand alone (point 3)
    # ------------------------------------------------------------------
    def _legal_check(self, amount=900.0, case="CASE-1"):
        check, invoice = self._received_check(amount)
        self._deposit(check)
        self._bounce(check)
        self.env["check.legal.wizard"].with_context(default_check_id=check.id).create({
            "case_number": case, "action_date": self.today - timedelta(days=12),
        }).action_confirm()
        return check

    def test_legal_cases_are_separate_on_the_dashboard(self):
        legal = self._legal_check(900.0)
        bounced, _inv = self._received_check(300.0)
        self._deposit(bounced)
        self._bounce(bounced)
        data = self.env["check.check"].get_dashboard_data()
        self.assertEqual(data["legal_cases"]["count"], 1)
        self.assertAlmostEqual(data["legal_cases"]["amount"], 900.0)
        self.assertEqual(data["legal_cases"]["rows"][0]["id"], legal.id)
        self.assertEqual(data["legal_cases"]["rows"][0]["days"], 12)
        self.assertEqual(data["bounced"]["count"], 1, "Legal cases are not counted as bounced")
        self.assertNotIn(legal, self.env["check.check"].search(data["incoming_outstanding"]["domain"]))

    def test_legal_cases_excluded_from_cash_flow(self):
        legal = self._legal_check()
        self.env.flush_all()
        self.assertFalse(self.env["check.maturity.report"].search([("check_id", "=", legal.id)]))

    def test_legal_report_lists_open_and_closed_cases(self):
        open_case = self._legal_check(case="CASE-OPEN")
        closed_case = self._legal_check(case="CASE-CLOSED")
        self.env["check.settle.wizard"].with_context(default_check_id=closed_case.id).create({
            "note": "Court settlement",
        }).action_confirm()
        action = self.env["ir.actions.act_window"]._for_xml_id("sa_check_management.action_check_legal_cases")
        cases = self.env["check.check"].search(safe_eval(action["domain"]))
        self.assertIn(open_case, cases)
        self.assertIn(closed_case, cases, "Closed cases stay in the legal report")
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "sa_check_management.report_check_legal", open_case.ids,
        )
        self.assertIn("CASE-OPEN", html.decode())

    # ------------------------------------------------------------------
    # Discounting (point 13)
    # ------------------------------------------------------------------
    def _discount_term(self, **values):
        self.company.check_discount_enabled = True
        term = self.env["check.discount.term"].search([("journal_id", "=", self.bank_journal.id)])
        values = {"advance_rate": 100.0, "interest_rate": 0.0, "fixed_fee": 0.0, **values}
        if term:
            term.write(values)
            return term
        return self.env["check.discount.term"].create({"journal_id": self.bank_journal.id, **values})

    def _discount(self, check, fee=50.0, date=None, advance=None):
        term = self._discount_term()
        vals = {"term_id": term.id, "fee": fee, "action_date": date or self.today}
        if advance is not None:
            vals["advance"] = advance
        self.env["check.discount.wizard"].with_context(default_check_id=check.id).create(vals).action_confirm()

    def _liability_open(self):
        account = self.company.check_discount_liability_account_id
        lines = self.env["account.move.line"].search([("account_id", "=", account.id), ("parent_state", "=", "posted")])
        return sum(lines.mapped("amount_residual"))

    def test_discount_posts_advance_and_liability(self):
        check, invoice = self._received_check(1000.0, due_date=self.today + timedelta(days=60))
        self._discount(check, fee=40.0)
        self.assertEqual(check.state, "discounted")
        self.assertAlmostEqual(check.discount_net_amount, 960.0)
        entry = self._entries(check, "discount")
        cost = entry.line_ids.filtered(lambda line: line.account_id == self.company.check_discount_cost_account_id)
        self.assertAlmostEqual(cost.balance, 40.0)
        self.assertAlmostEqual(self._liability_open(), -1000.0)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertEqual(check.current_location_id.journal_id, self.bank_journal)

    def test_discounted_check_collected_at_maturity(self):
        check, _inv = self._received_check(1000.0, due_date=self.today + timedelta(days=60))
        self._discount(check)
        self._collect(check)
        self.assertEqual(check.state, "collected")
        self.assertFalse(check._open_holding_lines())
        self.assertAlmostEqual(self._liability_open(), 0.0)
        self.assertFalse(check.current_location_id)

    def test_discounted_check_bounces(self):
        check, invoice = self._received_check(1000.0, due_date=self.today + timedelta(days=60))
        self._discount(check)
        self._bounce(check)
        self.assertEqual(check.state, "bounced")
        self.assertTrue(self._entries(check, "discount_repay"))
        self.assertAlmostEqual(self._liability_open(), 0.0)
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)
        self.assertEqual(check.accounting_status, "reversed")

    def test_discount_rules(self):
        guarantee, _inv = self._received_check(500.0, allocate=False, purpose="guarantee",
                                               due_date=self.today + timedelta(days=30))
        with self.assertRaises(UserError):
            self._discount(guarantee)
        due, _inv = self._received_check(500.0, due_date=self.today)
        with self.assertRaises(UserError):
            self._discount(due)
        self.company.check_settlement_policy = "collection"
        unposted, _inv = self._received_check(500.0, due_date=self.today + timedelta(days=30))
        with self.assertRaises(UserError):
            self._discount(unposted)

    def test_discounted_on_dashboard_not_in_cash_flow(self):
        check, _inv = self._received_check(800.0, due_date=self.today + timedelta(days=45))
        self._discount(check)
        data = self.env["check.check"].get_dashboard_data()
        self.assertEqual(data["discounted"]["count"], 1)
        self.assertEqual(data["discounted"]["rows"][0]["days"], 45)
        self.env.flush_all()
        self.assertFalse(self.env["check.maturity.report"].search([("check_id", "=", check.id)]))

    # ------------------------------------------------------------------
    # Legacy import
    # ------------------------------------------------------------------
    def _xlsx(self, rows):
        from openpyxl import Workbook
        from ..wizard.check_import_wizard import COLUMNS
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(COLUMNS)
        for row in rows:
            sheet.append([row.get(column, "") for column in COLUMNS])
        stream = io.BytesIO()
        workbook.save(stream)
        return base64.b64encode(stream.getvalue())

    def _import(self, rows, post_entries=True):
        wizard = self.env["check.import.wizard"].create({
            "file": self._xlsx(rows), "filename": "checks.xlsx", "post_entries": post_entries,
        })
        return wizard, wizard.action_import()

    def _row(self, **overrides):
        row = {
            "direction": "incoming", "check_number": self._next_number(), "partner": self.customer.name,
            "amount": 1500, "issue_date": str(self.today - timedelta(days=20)),
            "due_date": str(self.today + timedelta(days=20)), "bank": "CIB Test", "drawer_account": "IMP-1",
            "state": "received",
        }
        row.update(overrides)
        return row

    def test_import_creates_checks_in_current_state(self):
        rows = [
            self._row(),
            self._row(state="under_collection", journal=self.bank_journal.code),
            self._row(direction="outgoing", partner=self.vendor.name, bank="", drawer_account="",
                      state="delivered", journal=self.bank_journal.code),
        ]
        _wizard, action = self._import(rows)
        checks = self.env["check.check"].search(action["domain"]).sorted("id")
        self.assertEqual(checks.mapped("state"), ["received", "under_collection", "delivered"])
        for check in checks:
            self.assertTrue(check.is_imported)
            self.assertEqual(check.event_ids.mapped("event_type").count("imported"), 1)
            self.assertNotIn("received", check.event_ids.mapped("event_type"), "No fake history")
            self.assertEqual(check.accounting_status, "posted")
        deposited = checks[1]
        self.assertEqual(deposited.current_deposit_id.state, "confirmed")
        self._collect(deposited)
        self.assertEqual(deposited.state, "collected")
        delivered = checks[2]
        self._bank_match(delivered._open_holding_lines())
        self.assertEqual(delivered.state, "cleared")

    def test_import_without_opening_entries_posts_at_collection(self):
        _wizard, action = self._import([self._row()], post_entries=False)
        check = self.env["check.check"].search(action["domain"])
        self.assertEqual(check.accounting_status, "none")
        self.assertFalse(check.payment_ids)
        self._deposit(check)
        self._collect(check)
        self.assertEqual(check.accounting_status, "posted")
        self.assertEqual(check.payment_ids.journal_id, self.bank_journal)

    def test_import_reports_row_errors(self):
        wizard = self.env["check.import.wizard"].create({
            "file": self._xlsx([self._row(direction="sideways"), self._row(partner="Nobody At All"),
                                self._row(state="under_collection")]),
            "filename": "checks.xlsx",
        })
        wizard.action_validate()
        self.assertIn("Row 2", wizard.result)
        self.assertIn("Row 3", wizard.result)
        self.assertIn("Row 4", wizard.result)
        with self.assertRaises(UserError):
            wizard.action_import()
        self.assertFalse(self.env["check.check"].search([("is_imported", "=", True)]))

    def test_import_template_download(self):
        wizard = self.env["check.import.wizard"].create({})
        action = wizard.action_download_template()
        self.assertIn("checks_import_template.xlsx", action["url"])
        self.assertTrue(wizard.template_file)
