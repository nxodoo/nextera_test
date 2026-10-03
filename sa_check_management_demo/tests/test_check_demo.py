from collections import Counter

from odoo import fields
from odoo.tests import tagged

from odoo.addons.sa_check_management.tests.common import CheckAccountingCommon


@tagged("post_install", "-at_install", "sa_check_management_demo")
class TestCheckDemo(CheckAccountingCommon):

    def test_generated_checks_are_consistent(self):
        job = self.env["check.demo.job"].create({"requested": 60, "seed": 7})
        job.run_now()
        self.assertEqual((job.state, job.done, job.failed), ("done", 60, 0))
        checks = self.env["check.check"].search([("is_demo", "=", True)])
        self.assertGreaterEqual(len(checks), 60)
        states = Counter(checks.mapped("state"))
        self.assertGreater(len(states), 6, "A realistic mix of states")
        today = fields.Date.context_today(self.env.user)
        self.assertTrue(all((c.received_date or c.issued_date or c.issue_date) <= today for c in checks))
        for check in checks.filtered(lambda c: c.state in ("collected", "cleared")):
            self.assertFalse(check._open_holding_lines(), check.display_name)
        for check in checks.filtered(lambda c: c.state == "bounced" and c.check_type == "incoming"):
            self.assertEqual(check.accounting_status, "reversed")
        events = self.env["check.event"].search([("check_id", "in", checks.ids)])
        self.assertTrue(any(event.date.date() < today for event in events), "History carries scenario dates")

    def test_background_job_runs_in_batches(self):
        job = self.env["check.demo.job"].create({"requested": 25, "seed": 3})
        job._run_batch(size=10)
        self.assertEqual((job.state, job.done), ("running", 10))
        job._run_batch(size=10)
        job._run_batch(size=10)
        self.assertEqual((job.state, job.done + job.failed), ("done", 25), "Exact counts, even with deposit groups")
        second = self.env["check.demo.job"].create({"requested": 5})
        self.assertEqual(second.next_index, job.next_index, "A new job continues the numbering")
        second.run_now()
        self.assertEqual(second.done, 5)

    def test_wizard_runs_small_requests_right_away(self):
        wizard = self.env["check.demo.wizard"].create({"count": 15})
        action = wizard.action_generate()
        job = self.env["check.demo.job"].browse(action["res_id"])
        self.assertEqual(job.state, "done")

    def test_demo_users_per_role_act_in_the_history(self):
        job = self.env["check.demo.job"].create({"requested": 40, "seed": 11})
        job.run_now()
        users = self.env["res.users"].search([("login", "like", "demo.%")])
        logins = set(users.mapped("login"))
        self.assertTrue({"demo.clerk", "demo.treasury1", "demo.treasury2", "demo.approver", "demo.manager",
                         "demo.accountant", "demo.auditor", "demo.rep1"} <= logins)
        by_login = {user.login: user for user in users}
        self.assertTrue(by_login["demo.treasury1"].has_group("sa_check_management.group_check_treasury"))
        self.assertFalse(by_login["demo.clerk"].has_group("sa_check_management.group_check_treasury"))
        self.assertTrue(by_login["demo.accountant"].has_group("account.group_account_invoice"))
        self.assertTrue(by_login["demo.auditor"].has_group("sa_check_management.group_check_auditor"))
        checks = self.env["check.check"].search([("is_demo", "=", True)])
        actors = set(self.env["check.event"].search([("check_id", "in", checks.ids)]).mapped("user_id.login"))
        self.assertIn("demo.clerk", actors, "Created by the clerk")
        self.assertTrue(actors & {"demo.treasury1", "demo.treasury2"}, "Banking done by treasury")
        rep_locations = self.env["check.location"].search([("location_type", "=", "person")])
        self.assertTrue(set(rep_locations.mapped("user_id.login")) & {"demo.rep1", "demo.rep2", "demo.rep3"})
        approvals = checks.approval_line_ids.filtered(lambda l: l.state == "approved")
        if approvals:
            self.assertTrue(set(approvals.mapped("approver_id.login")) <= {"demo.approver", "demo.manager"})
        again = self.env["check.demo.job"].create({"requested": 3})
        again.run_now()
        self.assertEqual(self.env["res.users"].search_count([("login", "=", "demo.clerk")]), 1, "Users are reused")

    def test_without_users(self):
        job = self.env["check.demo.job"].create({"requested": 5, "create_users": False})
        job.run_now()
        self.assertEqual(job.done, 5)
