from odoo import api, fields, models

# Settled the invoice at receipt (posted) but the money is not in the bank yet.
OPEN_SETTLED_STATES = ("received", "under_collection", "discounted")
BOUNCED_STATES = ("bounced", "legal")
COLLATERAL = ("guarantee", "security")


class ResPartner(models.Model):
    _inherit = "res.partner"

    sa_check_open_amount = fields.Monetary(
        string="Open Customer Checks", currency_field="currency_id", compute="_compute_sa_check_figures",
        groups="sa_check_management.group_check_user",
    )
    sa_check_open_count = fields.Integer(compute="_compute_sa_check_figures", groups="sa_check_management.group_check_user")
    sa_check_bounced_count = fields.Integer(compute="_compute_sa_check_figures", groups="sa_check_management.group_check_user")

    @api.depends_context("company")
    def _compute_sa_check_figures(self):
        company = self.env.company
        for partner in self:
            commercial = partner.commercial_partner_id
            partner.sa_check_open_amount = commercial._sa_check_open_settled_amount(company)
            partner.sa_check_open_count = len(commercial._sa_check_open_checks(company))
            partner.sa_check_bounced_count = commercial._sa_check_bounced(company)[0]

    def _sa_check_domain(self, company):
        self.ensure_one()
        return [
            ("company_id", "=", company.id),
            ("check_type", "=", "incoming"),
            ("partner_id", "child_of", self.commercial_partner_id.id),
            ("purpose", "not in", COLLATERAL),
        ]

    def _sa_check_open_checks(self, company):
        self.ensure_one()
        return self.env["check.check"].sudo().search(self._sa_check_domain(company) + [
            ("state", "in", OPEN_SETTLED_STATES),
        ])

    def _sa_check_open_settled_amount(self, company):
        """Uncollected checks that already reduced the receivable: still a credit risk."""
        self.ensure_one()
        checks = self._sa_check_open_checks(company).filtered(lambda check: check.accounting_status == "posted")
        return sum(checks.mapped("company_amount"))

    def _sa_check_bounced(self, company):
        """(count, company-currency amount) of bounced checks still unresolved, legal cases included."""
        self.ensure_one()
        checks = self.env["check.check"].sudo().search(self._sa_check_domain(company) + [
            ("state", "in", BOUNCED_STATES),
        ])
        return len(checks), sum(checks.mapped("company_amount"))
