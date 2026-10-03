from datetime import timedelta

from odoo import api, fields, models, tools

# Legal cases and discounted checks are reported on their own, never mixed into these figures.
UNRESOLVED_INCOMING = ("received", "under_collection", "bounced")
UNRESOLVED_OUTGOING = ("approved", "issued", "delivered", "presented", "rejected")
COLLATERAL = ("guarantee", "security")


class CheckMaturityReport(models.Model):
    """Unresolved checks by due date: expected cash flow and aging, always live."""

    _name = "check.maturity.report"
    _description = "Check Maturity and Cash Flow"
    _auto = False
    _order = "due_date"
    _depends = {
        "check.check": ["check_type", "purpose", "partner_id", "bank_id", "company_id", "due_date",
                        "company_amount", "state", "active"],
        "res.company": ["currency_id", "check_horizon_short_days", "check_horizon_mid_days", "check_horizon_long_days"],
    }

    check_id = fields.Many2one("check.check", readonly=True)
    check_type = fields.Selection([("incoming", "Incoming"), ("outgoing", "Outgoing")], string="Direction", readonly=True)
    category = fields.Selection([("payment", "Payment"), ("collateral", "Guarantee / Security")], readonly=True)
    purpose = fields.Selection([
        ("payment", "Payment"), ("guarantee", "Guarantee"), ("security", "Security"), ("advance", "Advance"),
    ], readonly=True)
    state = fields.Selection(related="check_id.state", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    bank_id = fields.Many2one("res.bank", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Company Currency", readonly=True)
    due_date = fields.Date(readonly=True)
    bucket = fields.Selection([
        ("1_overdue", "Overdue"),
        ("2_today", "Due Today"),
        ("3_soon", "Due Soon"),
        ("4_short", "Short Term"),
        ("5_medium", "Medium Term"),
        ("6_later", "Later"),
    ], string="Maturity", readonly=True,
        help="Day ranges come from the company settings (by default 3, 7 and 30 days).")
    amount_in = fields.Monetary(string="Expected In", currency_field="currency_id", readonly=True)
    amount_out = fields.Monetary(string="Expected Out", currency_field="currency_id", readonly=True)
    amount_net = fields.Monetary(string="Expected Net", currency_field="currency_id", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT c.id AS id,
                       c.id AS check_id,
                       c.check_type,
                       CASE WHEN c.purpose IN %s THEN 'collateral' ELSE 'payment' END AS category,
                       c.purpose,
                       c.partner_id,
                       c.bank_id,
                       c.company_id,
                       comp.currency_id,
                       c.due_date,
                       CASE WHEN c.due_date < CURRENT_DATE THEN '1_overdue'
                            WHEN c.due_date = CURRENT_DATE THEN '2_today'
                            WHEN c.due_date <= CURRENT_DATE + COALESCE(comp.check_horizon_short_days, 3) THEN '3_soon'
                            WHEN c.due_date <= CURRENT_DATE + COALESCE(comp.check_horizon_mid_days, 7) THEN '4_short'
                            WHEN c.due_date <= CURRENT_DATE + COALESCE(comp.check_horizon_long_days, 30) THEN '5_medium'
                            ELSE '6_later' END AS bucket,
                       CASE WHEN c.check_type = 'incoming' THEN c.company_amount ELSE 0 END AS amount_in,
                       CASE WHEN c.check_type = 'outgoing' THEN c.company_amount ELSE 0 END AS amount_out,
                       CASE WHEN c.check_type = 'incoming' THEN c.company_amount ELSE -c.company_amount END AS amount_net
                  FROM check_check c
                  JOIN res_company comp ON comp.id = c.company_id
                 WHERE c.active
                   AND ((c.check_type = 'incoming' AND c.state IN %s)
                     OR (c.check_type = 'outgoing' AND c.state IN %s))
            )
        """, (COLLATERAL, UNRESOLVED_INCOMING, UNRESOLVED_OUTGOING))


class CheckCheck(models.Model):
    _inherit = "check.check"

    @api.model
    def get_dashboard_data(self):
        """KPIs for the treasury dashboard, in the current company's currency."""
        company = self.env.company
        today = fields.Date.context_today(self)
        base = [("company_id", "=", company.id)]
        payment = base + [("purpose", "not in", COLLATERAL)]
        incoming_open = payment + [("check_type", "=", "incoming"), ("state", "in", UNRESOLVED_INCOMING)]
        outgoing_open = payment + [("check_type", "=", "outgoing"), ("state", "in", UNRESOLVED_OUTGOING)]

        def kpi(domain):
            groups = self._read_group(domain, aggregates=["company_amount:sum", "__count"])
            amount, count = groups[0] if groups else (0.0, 0)
            return {"amount": amount or 0.0, "count": count, "domain": domain}

        def due(domain, days):
            return domain + [("due_date", ">=", today), ("due_date", "<=", today + timedelta(days=days))]

        mid, long_ = company.check_horizon_mid_days, company.check_horizon_long_days

        return {
            "currency": {"id": company.currency_id.id, "symbol": company.currency_id.symbol,
                         "position": company.currency_id.position, "digits": company.currency_id.decimal_places},
            "collection_rate": self._dashboard_collection_rate(company, today),
            "incoming_outstanding": kpi(incoming_open),
            "outgoing_outstanding": kpi(outgoing_open),
            "incoming_due_today": kpi(incoming_open + [("due_date", "=", today)]),
            "outgoing_due_today": kpi(outgoing_open + [("due_date", "=", today)]),
            "horizons": {"short": company.check_horizon_short_days, "mid": mid, "long": long_},
            "incoming_due_week": kpi(due(incoming_open, mid)),
            "outgoing_due_week": kpi(due(outgoing_open, mid)),
            "incoming_due_month": kpi(due(incoming_open, long_)),
            "outgoing_due_month": kpi(due(outgoing_open, long_)),
            "under_collection": kpi(base + [("state", "=", "under_collection")]),
            "bounced": kpi(base + [("state", "in", ("bounced", "rejected"))]),
            "legal_cases": self._dashboard_list(
                base + [("state", "=", "legal")], order="legal_date asc",
                row=lambda check: {
                    "id": check.id, "title": check.legal_case_number or check.name,
                    "subtitle": check.partner_id.display_name, "detail": check.legal_lawyer_id.display_name or "",
                    "days": check.legal_days, "amount": check.company_amount,
                },
            ),
            "discounted": self._dashboard_list(
                base + [("state", "=", "discounted")], order="due_date asc",
                row=lambda check: {
                    "id": check.id, "title": check.check_number, "subtitle": check.partner_id.display_name,
                    "detail": check.discount_journal_id.sudo().display_name or "",
                    "days": (check.due_date - today).days, "amount": check.company_amount,
                },
            ),
            "matured_not_deposited": kpi(payment + [
                ("check_type", "=", "incoming"), ("state", "=", "received"), ("due_date", "<", today),
            ]),
            "unallocated": {
                "amount": sum(self.search(payment + [("state", "not in", ("draft", "cancelled"))]).mapped(
                    lambda check: check.currency_id._convert(
                        check.unallocated_amount, company.currency_id, company, today)
                )),
            },
            "guarantees_held": kpi(base + [
                ("purpose", "in", COLLATERAL), ("check_type", "=", "incoming"), ("state", "=", "received"),
            ]),
            "awaiting_approval": kpi(base + [("state", "=", "pending_approval")]),
            "cash_flow": self._dashboard_cash_flow(company, today),
        }

    @api.model
    def _dashboard_list(self, domain, order, row, limit=5):
        """A KPI plus its first ``limit`` records, for the dashboard side panels."""
        groups = self._read_group(domain, aggregates=["company_amount:sum", "__count"])
        amount, count = groups[0] if groups else (0.0, 0)
        return {
            "amount": amount or 0.0,
            "count": count,
            "domain": domain,
            "rows": [row(check) for check in self.search(domain, order=order, limit=limit)],
        }

    @api.model
    def _dashboard_collection_rate(self, company, today, days=90):
        """Share of bank results in the last ``days`` that were collections rather than bounces."""
        lines = self.env["check.deposit.line"].search([
            ("company_id", "=", company.id),
            ("state", "in", ("collected", "bounced")),
            ("result_date", ">=", today - timedelta(days=days)),
        ])
        collected = len(lines.filtered(lambda line: line.state == "collected"))
        bounced = len(lines) - collected
        percent = round(100.0 * collected / len(lines)) if lines else 0
        return {"percent": percent, "collected": collected, "bounced": bounced, "days": days}

    @api.model
    def _dashboard_cash_flow(self, company, today, months=6):
        self.env["check.check"].flush_model()  # the report is a SQL view on check_check
        groups = self.env["check.maturity.report"]._read_group(
            [("company_id", "=", company.id), ("category", "=", "payment")],
            groupby=["due_date:month"], aggregates=["amount_in:sum", "amount_out:sum"],
        )
        start = today.replace(day=1)
        rows = []
        for month, amount_in, amount_out in groups:
            rows.append({
                "month": fields.Date.to_string(month),
                "incoming": amount_in or 0.0,
                "outgoing": amount_out or 0.0,
                "net": (amount_in or 0.0) - (amount_out or 0.0),
            })
        overdue = [row for row in rows if row["month"] < fields.Date.to_string(start)]
        upcoming = [row for row in rows if row["month"] >= fields.Date.to_string(start)][:months]
        if overdue:
            upcoming.insert(0, {
                "month": "overdue",
                "incoming": sum(row["incoming"] for row in overdue),
                "outgoing": sum(row["outgoing"] for row in overdue),
                "net": sum(row["net"] for row in overdue),
            })
        return upcoming
