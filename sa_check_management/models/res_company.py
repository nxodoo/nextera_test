from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PORTFOLIO_JOURNAL_CODES = ("CHKP", "CHKP2", "CHKP3", "CHKP4", "CHKP5")


class ResCompany(models.Model):
    _inherit = "res.company"

    # Approval (Phase 2)
    check_outgoing_approval_required = fields.Boolean(
        string="Outgoing Check Approval", default=True,
        help="Outgoing checks must be approved before they can be issued.",
    )
    check_approval_segregation = fields.Boolean(
        string="Check Approval Segregation", default=True,
        help="Users cannot approve outgoing checks they created or submitted.",
    )

    # Accounting (Phase 3)
    check_settlement_policy = fields.Selection(
        selection=[
            ("receipt", "At receipt / issue"),
            ("collection", "At collection / clearing"),
        ],
        string="Check Settlement", required=True, default="receipt",
        help="When a check settles the invoices or bills it is allocated to.",
    )
    check_receivable_account_id = fields.Many2one(
        "account.account", string="Checks Receivable Account",
        help="Holds incoming checks (PDC) between receipt and collection.",
    )
    check_payable_account_id = fields.Many2one(
        "account.account", string="Checks Payable Account",
        help="Holds outgoing checks between issue and bank clearing.",
    )
    check_portfolio_journal_id = fields.Many2one(
        "account.journal", string="Checks Portfolio Journal",
        help="Journal recording incoming checks until they are deposited at a bank.",
    )
    check_advance_creates_entries = fields.Boolean(
        string="Advance Checks Create Entries", default=True,
    )

    check_rate_policy = fields.Selection(
        selection=[
            ("receipt", "Receipt / issue date"),
            ("due", "Due date"),
            ("collection", "Collection / clearing date"),
        ],
        string="Check Valuation Rate", required=True, default="receipt",
        help="Exchange rate date used to value foreign-currency checks in reports and the dashboard. "
             "Accounting entries always use the rate of their own date.",
    )
    check_horizon_short_days = fields.Integer(string="Due Soon (Days)", default=3)
    check_horizon_mid_days = fields.Integer(string="Short Term (Days)", default=7)
    check_horizon_long_days = fields.Integer(string="Medium Term (Days)", default=30)
    check_allow_manual_rate = fields.Boolean(
        string="Allow Manual Valuation Rate",
        help="Let Check Managers enter an approved rate on a foreign-currency check; "
             "without it the automatic valuation policy applies.",
    )
    check_discount_enabled = fields.Boolean(
        string="Check Discounting",
        help="Allow discounting post-dated checks at banks that have discount terms.",
    )

    # Banking (Phase 4)
    check_bounce_fee_policy = fields.Selection(
        selection=[
            ("expense", "Company expense"),
            ("partner", "Charge to partner"),
        ],
        string="Bounce Fees", required=True, default="expense",
    )
    check_fee_account_id = fields.Many2one(
        "account.account", string="Check Bank Charges Account",
        help="Expense account for bank fees on check collection and bounces.",
    )
    check_deposit_entry = fields.Boolean(
        string="Post Deposit Entry",
        help="Move deposited checks from Checks Receivable to Checks Under Collection.",
    )
    check_under_collection_account_id = fields.Many2one(
        "account.account", string="Checks Under Collection Account",
    )
    check_handover_confirmation = fields.Boolean(
        string="Receiver Confirms Handovers", default=True,
        help="Custody moves only when the receiver accepts the handover.",
    )
    check_default_location_id = fields.Many2one(
        "check.location", string="Default Check Location",
        help="Where newly received checks are held until handed over.",
    )
    check_reminder_due_days = fields.Integer(string="Remind Before Due (Days)", default=3)
    check_reminder_guarantee_days = fields.Integer(string="Remind Before Guarantee Expiry (Days)", default=30)
    check_reminder_approval_days = fields.Integer(string="Approval Waiting Alert (Days)", default=2)
    check_reminder_deposit_days = fields.Integer(string="Deposit Result Alert (Days)", default=5)
    check_discount_liability_account_id = fields.Many2one(
        "account.account", string="Discounted Checks Liability Account",
        help="What the company owes the bank for checks discounted before maturity.",
    )
    check_discount_cost_account_id = fields.Many2one(
        "account.account", string="Check Discount Charges Account",
    )
    check_escalation_days = fields.Integer(
        string="Escalate After (Days)", default=3,
        help="Unresolved items are escalated to Check Managers this many days after their first reminder.",
    )
    check_stale_months = fields.Integer(
        string="Outgoing Check Validity (Months)", default=6,
        help="Outgoing checks not cleared after this many months from their date are flagged as stale.",
    )
    check_max_redeposits = fields.Integer(
        string="Maximum Re-deposits", default=3,
        help="Re-deposits allowed per check before a Check Manager must do it.",
    )

    @api.constrains("check_horizon_short_days", "check_horizon_mid_days", "check_horizon_long_days")
    def _check_horizons(self):
        for company in self:
            if not 0 < company.check_horizon_short_days < company.check_horizon_mid_days < company.check_horizon_long_days:
                raise ValidationError(_("Maturity horizons must be positive and increasing, e.g. 3, 7 and 30 days."))

    # ------------------------------------------------------------------
    # Setup (idempotent; safe to call before every posting)
    # ------------------------------------------------------------------
    def _sa_check_accounting_setup(self):
        self.ensure_one()
        company = self.sudo()
        if not company.check_receivable_account_id:
            company.check_receivable_account_id = company._sa_check_create_account(
                _("Checks Receivable (PDC)"), "asset_receivable", "asset_current",
            )
        if not company.check_payable_account_id:
            company.check_payable_account_id = company._sa_check_create_account(
                _("Checks Payable (PDC)"), "liability_payable", "liability_current",
            )
        if not company.check_portfolio_journal_id:
            company.check_portfolio_journal_id = company._sa_check_create_portfolio_journal()
        company._sa_check_incoming_method_line()
        return company

    def _sa_check_fee_account(self):
        self.ensure_one()
        if not self.check_fee_account_id:
            self.sudo().check_fee_account_id = self._sa_check_create_account(
                _("Check Bank Charges"), "expense", "expense", reconcile=False,
            )
        return self.check_fee_account_id

    def _sa_check_under_collection_account(self):
        self.ensure_one()
        if not self.check_under_collection_account_id:
            self.sudo().check_under_collection_account_id = self._sa_check_create_account(
                _("Checks Under Collection"), "asset_receivable", "asset_current",
            )
        return self.check_under_collection_account_id

    def _sa_check_discount_liability_account(self):
        self.ensure_one()
        if not self.check_discount_liability_account_id:
            self.sudo().check_discount_liability_account_id = self._sa_check_create_account(
                _("Discounted Checks Liability"), "liability_payable", "liability_current",
            )
        return self.check_discount_liability_account_id

    def _sa_check_discount_cost_account(self):
        self.ensure_one()
        if not self.check_discount_cost_account_id:
            self.sudo().check_discount_cost_account_id = self._sa_check_create_account(
                _("Check Discount Charges"), "expense", "expense", reconcile=False,
            )
        return self.check_discount_cost_account_id

    def _sa_check_bank_account(self, journal, payment_type):
        """Account the bank movement of a check hits: outstanding account if any, else the bank account."""
        self.ensure_one()
        journal = journal.sudo()
        lines = journal.inbound_payment_method_line_ids if payment_type == "inbound" else journal.outbound_payment_method_line_ids
        manual = lines.filtered(lambda line: line.payment_method_id.code == "manual")[:1]
        if manual.payment_account_id:
            return manual.payment_account_id
        xmlid = "account_journal_payment_debit_account_id" if payment_type == "inbound" else "account_journal_payment_credit_account_id"
        chart = self.env["account.chart.template"].with_context(allowed_company_ids=self.root_id.ids)
        return chart.ref(xmlid, raise_if_not_found=False) or journal.default_account_id

    def _sa_check_create_account(self, name, reference_type, account_type, reconcile=True):
        self.ensure_one()
        Account = self.env["account.account"].sudo().with_company(self)
        reference = Account.search([
            *Account._check_company_domain(self),
            ("account_type", "=", reference_type),
        ], limit=1)
        if not reference:
            raise UserError(_(
                "Install a chart of accounts for %(company)s before using check accounting.",
                company=self.name,
            ))
        return Account.create({
            "name": name,
            "code": Account._search_new_account_code(reference.code),
            "account_type": account_type,
            "reconcile": reconcile,
        })

    def _sa_check_create_portfolio_journal(self):
        self.ensure_one()
        Journal = self.env["account.journal"].sudo().with_company(self)
        code = next(
            (code for code in PORTFOLIO_JOURNAL_CODES
             if not Journal.search_count([("company_id", "=", self.id), ("code", "=", code)], limit=1)),
            None,
        )
        if not code:
            raise UserError(_("Could not find a free code for the Checks Portfolio journal."))
        return Journal.create({
            "name": _("Checks Portfolio"),
            "type": "cash",
            "code": code,
            "company_id": self.id,
        })

    def _sa_check_incoming_method_line(self):
        self.ensure_one()
        method = self.env.ref("sa_check_management.payment_method_check_in")
        return self._sa_check_method_line(
            self.check_portfolio_journal_id, method, self.check_receivable_account_id,
        )

    def _sa_check_outgoing_method_line(self, journal):
        self.ensure_one()
        method = self.env.ref("sa_check_management.payment_method_check_out")
        return self._sa_check_method_line(journal, method, self.check_payable_account_id)

    def _sa_check_bank_method_line(self, journal, payment_type):
        """Check method line posting straight to the bank side (settlement at collection/clearing)."""
        self.ensure_one()
        xmlid = "payment_method_check_in" if payment_type == "inbound" else "payment_method_check_out"
        method = self.env.ref(f"sa_check_management.{xmlid}")
        account = self._sa_check_bank_account(journal, payment_type)
        return self._sa_check_method_line(journal, method, account, name=_("Check (Bank)"))

    def _sa_check_method_line(self, journal, method, account, name=None):
        journal = journal.sudo()
        lines = (
            journal.inbound_payment_method_line_ids if method.payment_type == "inbound"
            else journal.outbound_payment_method_line_ids
        ).filtered(lambda method_line: method_line.payment_method_id == method)
        line = lines.filtered(lambda method_line: method_line.payment_account_id == account)[:1]
        if line:
            return line
        blank = lines.filtered(lambda method_line: not method_line.payment_account_id)[:1]
        if blank:
            blank.sudo().payment_account_id = account
            return blank
        return self.env["account.payment.method.line"].sudo().create({
            "name": name or method.name,
            "payment_method_id": method.id,
            "journal_id": journal.id,
            "payment_account_id": account.id,
        })
