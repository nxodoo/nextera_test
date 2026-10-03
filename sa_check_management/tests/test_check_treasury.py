from datetime import timedelta

from odoo.tests import tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckTreasury(CheckBankingCommon):

    def _activities(self, record, user=None):
        domain = [("res_model", "=", record._name), ("res_id", "=", record.id)]
        if user:
            domain.append(("user_id", "=", user.id))
        return self.env["mail.activity"].search(domain)

    def _run_cron(self):
        self.env["check.check"]._cron_check_reminders()

    def _report_rows(self, checks):
        self.env.flush_all()
        return self.env["check.maturity.report"].search([("check_id", "in", checks.ids)])

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------
    def test_due_reminder_is_sent_once(self):
        check, _inv = self._received_check(500.0, due_date=self.today + timedelta(days=2))
        self._run_cron()
        activity = self._activities(check)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, check.responsible_user_id)
        self._run_cron()
        self.assertEqual(len(self._activities(check)), 1, "No duplicate while the activity is open")
        activity.action_done()
        self._run_cron()
        self.assertFalse(self._activities(check), "A completed reminder is not recreated")

    def test_due_reminder_respects_lead_time(self):
        far, _inv = self._received_check(500.0, due_date=self.today + timedelta(days=20))
        self._run_cron()
        self.assertFalse(self._activities(far))
        self.company.check_reminder_due_days = 30
        self._run_cron()
        self.assertTrue(self._activities(far))

    def test_matured_not_deposited_reminder(self):
        check, _inv = self._received_check(
            500.0, issue_date=self.today - timedelta(days=10), due_date=self.today - timedelta(days=1),
        )
        self._run_cron()
        self.assertIn("not deposited", self._activities(check).summary)

    def test_bounced_reminder(self):
        check, _inv = self._received_check(500.0, due_date=self.today + timedelta(days=60))
        self._deposit(check)
        self._bounce(check)
        self._run_cron()
        self.assertIn("bounced", self._activities(check).summary.lower())

    def test_guarantee_expiry_reminder(self):
        check, _inv = self._received_check(
            5000.0, allocate=False, purpose="guarantee", due_date=self.today + timedelta(days=90),
            guarantee_expiry_date=self.today + timedelta(days=10),
        )
        self._run_cron()
        self.assertIn("Guarantee expires", self._activities(check).summary)

    def test_approval_waiting_reminder_goes_to_approvers(self):
        self.company.check_outgoing_approval_required = True
        check = self._create_outgoing(check_number=self._next_number(), amount=500.0,
                                      due_date=self.today + timedelta(days=60))
        check.action_submit()
        self._run_cron()
        self.assertFalse(self._activities(check, self.check_approver), "Not late yet")
        self.env.cr.execute(
            "UPDATE check_approval_line SET create_date = now() - interval '5 days' WHERE check_id = %s",
            [check.id],
        )
        check.approval_line_ids.invalidate_recordset(["create_date"])
        self._run_cron()
        self.assertTrue(self._activities(check, self.check_approver))

    def test_deposit_without_results_reminder(self):
        check, _inv = self._received_check(500.0, due_date=self.today + timedelta(days=60))
        wizard = self.env["check.deposit.wizard"].with_context(default_check_ids=[(6, 0, check.ids)]).create({
            "journal_id": self.bank_journal.id, "date": self.today - timedelta(days=10),
        })
        deposit = self.env["check.deposit"].browse(wizard.action_confirm()["res_id"])
        self._run_cron()
        self.assertTrue(self._activities(deposit))

    def test_pending_handover_reminder_goes_to_receiver(self):
        safe = self.env["check.location"].create({"name": "Safe", "location_type": "safe"})
        rep = self.env["check.location"].create({"name": "Rep", "location_type": "person", "user_id": self.check_user.id})
        check, _inv = self._received_check(100.0, current_location_id=safe.id, due_date=self.today + timedelta(days=60))
        handover = self.env["check.handover"].create({
            "check_ids": [(6, 0, check.ids)], "from_location_id": safe.id, "to_location_id": rep.id,
            "date": self.today - timedelta(days=3),
        })
        handover.action_send()
        self._run_cron()
        self.assertTrue(self._activities(handover, self.check_user))

    # ------------------------------------------------------------------
    # Maturity / cash-flow report
    # ------------------------------------------------------------------
    def test_report_buckets_and_directions(self):
        overdue, _inv = self._received_check(100.0, issue_date=self.today - timedelta(days=5),
                                             due_date=self.today - timedelta(days=1))
        today, _inv = self._received_check(200.0, due_date=self.today)
        later, _inv = self._received_check(300.0, due_date=self.today + timedelta(days=90))
        outgoing = self._create_outgoing(check_number=self._next_number(), amount=50.0,
                                         due_date=self.today + timedelta(days=5))
        outgoing.action_issue()
        rows = self._report_rows(overdue | today | later | outgoing)
        bucket = {row.check_id: row.bucket for row in rows}
        self.assertEqual(bucket[overdue], "1_overdue")
        self.assertEqual(bucket[today], "2_today")
        self.assertEqual(bucket[later], "6_later")
        self.assertEqual(bucket[outgoing], "4_short", "5 days: between the 3 and 7 day horizons")
        out_row = rows.filtered(lambda row: row.check_id == outgoing)
        self.assertEqual((out_row.amount_in, out_row.amount_out, out_row.amount_net), (0.0, 50.0, -50.0))

    def test_report_excludes_resolved_and_marks_collateral(self):
        collected, _inv = self._received_check(100.0)
        self._deposit(collected)
        self._collect(collected)
        draft = self._create_incoming(check_number=self._next_number(), amount=100.0)
        guarantee, _inv = self._received_check(900.0, allocate=False, purpose="guarantee")
        rows = self._report_rows(collected | draft | guarantee)
        self.assertEqual(rows.check_id, guarantee)
        self.assertEqual(rows.category, "collateral")

    # ------------------------------------------------------------------
    # Dashboard data
    # ------------------------------------------------------------------
    def test_dashboard_kpis(self):
        self._received_check(1000.0, due_date=self.today)
        self._received_check(400.0, issue_date=self.today - timedelta(days=9), due_date=self.today - timedelta(days=2))
        bounced, _inv = self._received_check(250.0, due_date=self.today + timedelta(days=40))
        self._deposit(bounced)
        self._bounce(bounced)
        self._received_check(5000.0, allocate=False, purpose="guarantee")
        data = self.env["check.check"].get_dashboard_data()
        self.assertAlmostEqual(data["incoming_outstanding"]["amount"], 1650.0)
        self.assertEqual(data["incoming_outstanding"]["count"], 3)
        self.assertAlmostEqual(data["incoming_due_today"]["amount"], 1000.0)
        self.assertAlmostEqual(data["matured_not_deposited"]["amount"], 400.0)
        self.assertEqual(data["bounced"]["count"], 1)
        self.assertAlmostEqual(data["guarantees_held"]["amount"], 5000.0)
        months = {row["month"]: row for row in data["cash_flow"]}
        self.assertIn("overdue", months)
        self.assertAlmostEqual(months["overdue"]["incoming"], 400.0)
        self.assertTrue(all(row["outgoing"] == 0 for row in data["cash_flow"]))

    def test_dashboard_collection_rate(self):
        collected, _inv = self._received_check(100.0)
        bounced, _inv = self._received_check(100.0)
        third, _inv = self._received_check(100.0)
        self._deposit(collected | bounced | third)
        self._collect(collected | third)
        self._bounce(bounced)
        rate = self.env["check.check"].get_dashboard_data()["collection_rate"]
        self.assertEqual((rate["collected"], rate["bounced"], rate["percent"]), (2, 1, 67))

    def test_dashboard_kpi_domain_opens_matching_checks(self):
        check, _inv = self._received_check(700.0, due_date=self.today)
        domain = self.env["check.check"].get_dashboard_data()["incoming_due_today"]["domain"]
        self.assertIn(check, self.env["check.check"].search(domain))

    # ------------------------------------------------------------------
    # Printed documents
    # ------------------------------------------------------------------
    def _render(self, report, records):
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(report, records.ids)
        return html.decode()

    def test_printed_documents_render(self):
        check, invoice = self._received_check(1234.0)
        receipt = self._render("sa_check_management.report_check_receipt", check)
        self.assertIn(check.check_number, receipt)
        self.assertIn(invoice.name, receipt)
        deposit = self._deposit(check)
        slip = self._render("sa_check_management.report_check_deposit", deposit)
        self.assertIn(deposit.name, slip)
        self.assertIn(check.check_number, slip)
        safe = self.env["check.location"].create({"name": "Safe", "location_type": "safe"})
        branch = self.env["check.location"].create({"name": "Branch", "location_type": "branch"})
        other, _inv = self._received_check(50.0, current_location_id=safe.id)
        handover = self.env["check.handover"].create({
            "check_ids": [(6, 0, other.ids)], "from_location_id": safe.id, "to_location_id": branch.id,
        })
        self.assertIn(other.check_number, self._render("sa_check_management.report_check_handover", handover))
