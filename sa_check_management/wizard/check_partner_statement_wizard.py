from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

OPEN_STATES = {
    "incoming": ("received", "under_collection", "discounted"),
    "outgoing": ("approved", "issued", "delivered", "presented"),
}
PROBLEM_STATES = {
    "incoming": ("bounced", "legal"),
    "outgoing": ("rejected", "stopped"),
}


class CheckPartnerStatementWizard(models.TransientModel):
    _name = "check.partner.statement.wizard"
    _description = "Partner Check Statement"

    partner_id = fields.Many2one("res.partner", required=True)
    check_type = fields.Selection(
        [("incoming", "Checks Received"), ("outgoing", "Checks Issued")], string="Direction",
        required=True, default="incoming",
    )
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self) - relativedelta(years=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("The start date must be before the end date."))
        return self.env.ref("sa_check_management.action_report_check_partner_statement").report_action(self)

    # ------------------------------------------------------------------
    # Statement content (used by the report template)
    # ------------------------------------------------------------------
    def _base_domain(self):
        self.ensure_one()
        return [
            ("company_id", "=", self.env.company.id),
            ("check_type", "=", self.check_type),
            ("partner_id", "child_of", self.partner_id.commercial_partner_id.id),
        ]

    def _statement_sections(self):
        self.ensure_one()
        Check = self.env["check.check"].sudo()
        open_checks = Check.search(self._base_domain() + [("state", "in", OPEN_STATES[self.check_type])], order="due_date")
        problems = Check.search(self._base_domain() + [("state", "in", PROBLEM_STATES[self.check_type])], order="due_date")
        period = Check.search(self._base_domain() + [
            ("issue_date", ">=", self.date_from), ("issue_date", "<=", self.date_to),
            ("state", "not in", ("draft", "cancelled")),
        ], order="issue_date, id")
        return [
            {"title": _("Open Checks"), "checks": open_checks},
            {"title": _("Bounced and Legal") if self.check_type == "incoming" else _("Rejected and Stopped"),
             "checks": problems},
            {"title": _("All Checks Dated in the Period"), "checks": period},
        ]

    def _totals(self, checks):
        return sum(checks.mapped("company_amount"))
