from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CheckDiscountTerm(models.Model):
    """What a bank advances against a post-dated check, and what it charges."""

    _name = "check.discount.term"
    _description = "Check Discount Terms"
    _order = "journal_id"
    _check_company_auto = True

    _sql_constraints = [
        ("journal_unique", "UNIQUE(journal_id)", "Each bank has a single set of discount terms."),
    ]

    journal_id = fields.Many2one(
        "account.journal", string="Bank", required=True, check_company=True,
        domain="[('type', '=', 'bank')]", ondelete="cascade",
    )
    company_id = fields.Many2one(related="journal_id.company_id", store=True, index=True)
    currency_id = fields.Many2one("res.currency", compute="_compute_currency_id")
    advance_rate = fields.Float(
        string="Advance (%)", default=100.0, digits=(5, 2),
        help="Share of the check amount the bank pays in advance.",
    )
    interest_rate = fields.Float(
        string="Annual Interest (%)", digits=(5, 2),
        help="Charged on the advance for the days until the due date.",
    )
    fixed_fee = fields.Monetary(string="Fixed Fee per Check", currency_field="currency_id")
    active = fields.Boolean(default=True)

    @api.depends("journal_id")
    def _compute_currency_id(self):
        for term in self:
            term.currency_id = term.journal_id.currency_id or term.journal_id.company_id.currency_id

    @api.constrains("advance_rate", "interest_rate", "fixed_fee")
    def _check_values(self):
        for term in self:
            if not 0 < term.advance_rate <= 100:
                raise ValidationError(_("The advance must be more than 0% and at most 100%."))
            if term.interest_rate < 0 or term.fixed_fee < 0:
                raise ValidationError(_("Interest and fees cannot be negative."))

    def _advance_for(self, amount):
        self.ensure_one()
        return self.currency_id.round(amount * self.advance_rate / 100.0)

    def _charges_for(self, advance, days):
        """Interest on the advance for ``days`` (actual/365) plus the fixed fee."""
        self.ensure_one()
        interest = advance * self.interest_rate / 100.0 * max(days, 0) / 365.0
        return self.currency_id.round(interest + self.fixed_fee)
