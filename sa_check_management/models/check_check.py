from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STATE_SELECTION = [
    # Shared
    ("draft", "Draft"),
    # Incoming
    ("received", "Received"),
    ("under_collection", "Under Collection"),
    ("collected", "Collected"),
    ("bounced", "Bounced"),
    ("legal", "Legal Action"),
    ("settled", "Settled"),
    ("endorsed", "Endorsed"),
    ("replaced", "Replaced"),
    ("returned", "Returned"),
    ("lost", "Lost"),
    ("discounted", "Discounted"),
    # Outgoing
    ("pending_approval", "Pending Approval"),
    ("approved", "Approved"),
    ("issued", "Issued"),
    ("delivered", "Delivered"),
    ("presented", "Presented"),
    ("cleared", "Cleared"),
    ("rejected", "Rejected"),
    ("stopped", "Stopped"),
    # Shared
    ("cancelled", "Cancelled"),
]

INCOMING_STATES = frozenset({
    "draft", "received", "under_collection", "collected", "bounced", "legal",
    "settled", "endorsed", "replaced", "returned", "lost", "discounted", "cancelled",
})
OUTGOING_STATES = frozenset({
    "draft", "pending_approval", "approved", "issued", "delivered", "presented",
    "cleared", "rejected", "stopped", "replaced", "settled", "returned", "lost", "cancelled",
})
# Closed from our side; "endorsed" may still come back through an endorsement bounce.
TERMINAL_STATES = frozenset({
    "collected", "settled", "replaced", "returned", "lost", "endorsed",
    "cleared", "stopped", "cancelled",
})

# Identity/financial fields frozen once a check leaves Draft.
LOCKED_FIELDS = frozenset({
    "check_number", "check_type", "purpose", "partner_id", "amount",
    "currency_id", "issue_date", "due_date", "bank_id",
    "drawer_account_number", "journal_id", "company_id",
    "leaf_id", "current_location_id",
})

SEQUENCE_CODES = {
    "incoming": "sa.check.incoming",
    "outgoing": "sa.check.outgoing",
}

# Context keys for controlled internal operations.
CTX_STATE_TRANSITION = "sa_check_state_transition"
CTX_ALLOW_LOCKED_EDIT = "sa_check_allow_locked_edit"


def _identity_key(value, strip_zeros=False):
    key = "".join(char for char in (value or "") if char.isalnum()).upper()
    return (key.lstrip("0") or "0") if strip_zeros and key else key


class CheckCheck(models.Model):
    _name = "check.check"
    _description = "Check"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "due_date desc, id desc"
    _check_company_auto = True
    _rec_names_search = ["name", "check_number", "partner_id.name", "reference"]

    _sql_constraints = [
        ("amount_positive", "CHECK(amount > 0)",
         "The check amount must be greater than zero."),
    ]

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name = fields.Char(
        string="Reference", required=True, readonly=True, copy=False,
        default="/", index="trigram", tracking=True,
    )
    check_number = fields.Char(
        string="Check Number", required=True, copy=False, index=True, tracking=True,
        help="Physical number printed on the check. Stored as text to keep leading zeros.",
    )
    check_type = fields.Selection(
        selection=[("incoming", "Incoming"), ("outgoing", "Outgoing")],
        string="Direction", required=True, readonly=True, index=True, tracking=True,
        default=lambda self: self.env.context.get("default_check_type"),
    )
    purpose = fields.Selection(
        selection=[
            ("payment", "Payment"),
            ("guarantee", "Guarantee"),
            ("security", "Security"),
            ("advance", "Advance"),
        ],
        required=True, default="payment", tracking=True,
    )
    state = fields.Selection(
        selection=STATE_SELECTION, required=True, readonly=True, copy=False,
        default="draft", index=True, tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company,
    )
    company_partner_id = fields.Many2one(related="company_id.partner_id", string="Company Partner")
    responsible_user_id = fields.Many2one(
        "res.users", string="Responsible", default=lambda self: self.env.user,
        tracking=True,
    )

    # ------------------------------------------------------------------
    # Counterparty
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        "res.partner", string="Partner", required=True, index=True,
        check_company=True, tracking=True,
    )
    drawer_is_partner = fields.Boolean(
        string="Drawn by Partner", default=True,
        help="Uncheck when the check is drawn on a third party's account.",
    )
    drawer_name = fields.Char(string="Drawer Name", tracking=True)
    drawer_account_number = fields.Char(string="Drawer Account Number", tracking=True)
    # Normalised copies used to detect duplicates whatever the typing (spaces, dashes, leading zeros).
    check_number_key = fields.Char(compute="_compute_identity_keys", store=True, index=True)
    drawer_account_key = fields.Char(compute="_compute_identity_keys", store=True, index=True)

    # ------------------------------------------------------------------
    # Money
    # ------------------------------------------------------------------
    amount = fields.Monetary(currency_field="currency_id", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", required=True, tracking=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_currency_id = fields.Many2one(related="company_id.currency_id", string="Company Currency")
    manual_rate_allowed = fields.Boolean(related="company_id.check_allow_manual_rate")
    valuation_rate = fields.Float(
        string="Approved Valuation Rate", digits=(12, 6), tracking=True, copy=False,
        help="Company currency per one unit of the check currency, approved by a Check Manager. "
             "Leave empty to value the check automatically.",
    )
    company_amount = fields.Monetary(
        string="Amount (Company Currency)", currency_field="company_currency_id",
        compute="_compute_company_amount", store=True,
    )

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------
    issue_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    due_date = fields.Date(required=True, index=True, tracking=True)
    received_date = fields.Date(readonly=True, copy=False)
    issued_date = fields.Date(readonly=True, copy=False)
    collected_date = fields.Date(readonly=True, copy=False)
    cleared_date = fields.Date(readonly=True, copy=False)
    cancelled_date = fields.Date(readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Bank
    # ------------------------------------------------------------------
    journal_id = fields.Many2one(
        "account.journal", string="Bank Journal", check_company=True,
        domain="[('type', '=', 'bank')]", tracking=True,
    )
    bank_id = fields.Many2one(
        "res.bank", string="Bank", compute="_compute_bank_id", store=True,
        readonly=False, tracking=True,
        help="Incoming: bank printed on the check. Outgoing: bank of the issuing journal.",
    )
    bank_account_id = fields.Many2one(
        "res.partner.bank", string="Bank Account", compute="_compute_bank_account_id",
        store=True, readonly=False, check_company=True,
    )

    # ------------------------------------------------------------------
    # Controls and other
    # ------------------------------------------------------------------
    duplicate_approved = fields.Boolean(
        string="Duplicate Number Approved", copy=False, tracking=True,
        groups="sa_check_management.group_check_manager",
        help="Set by a manager to allow a check number that already exists in the same scope.",
    )
    reference = fields.Char(string="External Reference", tracking=True)
    notes = fields.Html()
    event_ids = fields.One2many("check.event", "check_id", string="History", readonly=True)
    event_count = fields.Integer(compute="_compute_event_count")

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("amount", "currency_id", "company_id", "company_id.check_rate_policy",
                 "company_id.check_allow_manual_rate", "valuation_rate",
                 "issue_date", "due_date", "received_date", "issued_date", "collected_date", "cleared_date")
    def _compute_company_amount(self):
        for check in self:
            check.company_amount = check._amount_in_company_currency()

    def _amount_in_company_currency(self):
        self.ensure_one()
        if not self.currency_id or not self.company_id:
            return 0.0
        if self._uses_manual_rate():
            return self.company_currency_id.round(self.amount * self.valuation_rate)
        return self.currency_id._convert(
            self.amount, self.company_currency_id, self.company_id, self._valuation_date(),
        )

    def _uses_manual_rate(self):
        self.ensure_one()
        return bool(self.company_id.check_allow_manual_rate and self.valuation_rate
                    and self.currency_id != self.company_currency_id)

    def _valuation_date(self):
        """Rate date used to value the check in company currency, per the company policy.

        Entries are always posted at the real transaction date; this only drives reporting.
        """
        self.ensure_one()
        policy = self.company_id.check_rate_policy
        moved = self.received_date or self.issued_date
        if policy == "due":
            return self.due_date or self.issue_date
        if policy == "collection":
            # Until the bank settles, the due date is the best estimate of the collection date.
            return self.collected_date or self.cleared_date or self.due_date or self.issue_date
        return moved or self.issue_date or fields.Date.context_today(self)

    @api.depends("journal_id", "check_type")
    def _compute_bank_id(self):
        for check in self:
            if check.check_type == "outgoing" and check.journal_id:
                check.bank_id = check.journal_id.bank_id
            else:
                check.bank_id = check.bank_id

    @api.depends("journal_id", "check_type")
    def _compute_bank_account_id(self):
        for check in self:
            if check.check_type == "outgoing" and check.journal_id:
                check.bank_account_id = check.journal_id.bank_account_id
            else:
                check.bank_account_id = check.bank_account_id

    @api.depends("check_number", "drawer_account_number")
    def _compute_identity_keys(self):
        for check in self:
            check.check_number_key = _identity_key(check.check_number, strip_zeros=True)
            check.drawer_account_key = _identity_key(check.drawer_account_number)

    @api.depends("event_ids")
    def _compute_event_count(self):
        for check in self:
            check.event_count = len(check.event_ids)

    @api.depends("name", "check_number")
    def _compute_display_name(self):
        for check in self:
            if check.check_number:
                check.display_name = f"{check.name} ({check.check_number})"
            else:
                check.display_name = check.name

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("issue_date", "due_date")
    def _check_due_after_issue(self):
        for check in self:
            if check.due_date and check.issue_date and check.due_date < check.issue_date:
                raise ValidationError(_(
                    "Check %(check)s: the due date cannot be earlier than the issue date.",
                    check=check.display_name,
                ))

    @api.constrains("state", "check_type")
    def _check_state_matches_direction(self):
        for check in self:
            if check.state not in check._allowed_states():
                raise ValidationError(_(
                    "State %(state)s is not valid for a %(direction)s check.",
                    state=check.state, direction=check.check_type,
                ))

    @api.constrains("drawer_is_partner", "drawer_name", "check_type")
    def _check_drawer_name(self):
        for check in self:
            if check.check_type == "incoming" and not check.drawer_is_partner and not check.drawer_name:
                raise ValidationError(_(
                    "Check %(check)s: enter the drawer name when the check is not drawn by the partner.",
                    check=check.display_name,
                ))

    @api.constrains("valuation_rate")
    def _check_valuation_rate(self):
        for check in self:
            if check.valuation_rate < 0:
                raise ValidationError(_("The valuation rate cannot be negative."))

    @api.constrains("check_type", "drawer_account_number")
    def _check_drawer_account_required(self):
        for check in self:
            if check.check_type == "incoming" and not (check.drawer_account_number or "").strip():
                raise ValidationError(_(
                    "Check %(check)s: enter the drawer account number; it is needed to detect duplicate checks.",
                    check=check.display_name,
                ))

    @api.constrains("bank_account_id", "check_type", "company_id")
    def _check_outgoing_bank_account_owner(self):
        for check in self:
            account = check.bank_account_id
            if check.check_type == "outgoing" and account and account.partner_id != check.company_id.partner_id:
                raise ValidationError(_(
                    "Check %(check)s: an outgoing check must use a bank account of %(company)s.",
                    check=check.display_name, company=check.company_id.name,
                ))

    @api.constrains("check_number_key", "check_type", "company_id", "bank_id",
                    "drawer_account_key", "journal_id", "state")
    def _check_unique_number(self):
        for check in self.sudo():
            if check.duplicate_approved or not check._has_uniqueness_scope():
                continue
            if check.with_context(active_test=False).search_count(check._duplicate_domain(), limit=1):
                raise ValidationError(_(
                    "Check number %(number)s already exists in the same scope. "
                    "Ask a Check Manager to approve the duplicate if it is legitimate.",
                    number=check.check_number,
                ))

    def _has_uniqueness_scope(self):
        self.ensure_one()
        if self.check_type == "outgoing":
            return bool(self.journal_id)
        return True

    def _duplicate_domain(self):
        self.ensure_one()
        domain = [
            ("id", "!=", self.id),
            ("company_id", "=", self.company_id.id),
            ("check_type", "=", self.check_type),
            ("check_number_key", "=", self.check_number_key),
            ("state", "!=", "cancelled"),
        ]
        if self.check_type == "incoming":
            domain += [
                ("bank_id", "=", self.bank_id.id),
                ("drawer_account_key", "=", self.drawer_account_key),
            ]
        else:
            domain.append(("journal_id", "=", self.journal_id.id))
        return domain

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_identity_vals(vals)
            if vals.get("name", "/") == "/":
                vals["name"] = self._next_reference(vals)
        checks = super().create(vals_list)
        checks._log_event("created")
        return checks

    def write(self, vals):
        self._guard_state_write(vals)
        self._guard_type_change(vals)
        self._guard_locked_fields(vals)
        self._guard_archive(vals)
        self._guard_valuation_rate(vals)
        self._normalize_identity_vals(vals)
        return super().write(vals)

    def _guard_valuation_rate(self, vals):
        if "valuation_rate" not in vals or self.env.su:
            return
        if not self.env.user.has_group("sa_check_management.group_check_manager"):
            raise UserError(_("Only a Check Manager can approve a valuation rate."))
        if vals["valuation_rate"] and self.filtered(lambda check: not check.company_id.check_allow_manual_rate):
            raise UserError(_("Manual valuation rates are not enabled for this company."))

    def copy(self, default=None):
        raise UserError(_("Checks cannot be duplicated. Create a new check for each physical check."))

    @api.ondelete(at_uninstall=False)
    def _unlink_only_clean_drafts(self):
        for check in self:
            if check.state != "draft":
                raise UserError(_(
                    "Check %(check)s is not in Draft. Cancel it instead of deleting it.",
                    check=check.display_name,
                ))
            if check.event_ids.filtered(lambda event: event.event_type != "created"):
                raise UserError(_(
                    "Check %(check)s has recorded history and cannot be deleted.",
                    check=check.display_name,
                ))

    # ------------------------------------------------------------------
    # Write guards (one rule each)
    # ------------------------------------------------------------------
    def _guard_state_write(self, vals):
        if "state" in vals and not self.env.context.get(CTX_STATE_TRANSITION):
            raise UserError(_("The check state can only change through its lifecycle actions."))

    def _guard_type_change(self, vals):
        if "check_type" in vals and any(check.check_type != vals["check_type"] for check in self):
            raise UserError(_("The direction of a check cannot be changed after creation."))

    def _guard_locked_fields(self, vals):
        if self.env.context.get(CTX_ALLOW_LOCKED_EDIT):
            return
        locked = LOCKED_FIELDS.intersection(vals)
        if not locked:
            return
        if self.filtered(lambda check: check.state != "draft"):
            labels = ", ".join(sorted(self._fields[name].string for name in locked))
            raise UserError(_(
                "These fields cannot be changed after the check leaves Draft: %(fields)s.",
                fields=labels,
            ))

    def _guard_archive(self, vals):
        if vals.get("active", True):
            return
        open_checks = self.filtered(lambda check: check.state not in TERMINAL_STATES | {"draft"})
        if open_checks:
            raise UserError(_(
                "Only draft or closed checks can be archived. Open checks: %(checks)s.",
                checks=", ".join(open_checks.mapped("display_name")),
            ))

    @api.model
    def _normalize_identity_vals(self, vals):
        for field_name in ("check_number", "drawer_account_number"):
            if isinstance(vals.get(field_name), str):
                vals[field_name] = vals[field_name].strip()

    # ------------------------------------------------------------------
    # Sequence
    # ------------------------------------------------------------------
    @api.model
    def _next_reference(self, vals):
        check_type = vals.get("check_type") or self.env.context.get("default_check_type")
        if check_type not in SEQUENCE_CODES:
            raise UserError(_("Open checks from the Incoming or Outgoing menu so the direction is set."))
        company_id = vals.get("company_id") or self.env.company.id
        reference = self.env["ir.sequence"].sudo().with_company(company_id).next_by_code(
            SEQUENCE_CODES[check_type]
        )
        if not reference:
            raise UserError(_("The check sequence %(code)s is missing.", code=SEQUENCE_CODES[check_type]))
        return reference

    # ------------------------------------------------------------------
    # State and history helpers (used by lifecycle actions)
    # ------------------------------------------------------------------
    def _allowed_states(self):
        self.ensure_one()
        return INCOMING_STATES if self.check_type == "incoming" else OUTGOING_STATES

    def _set_state(self, new_state, event_type="state_change", note=False, source=False):
        for check in self:
            if new_state not in check._allowed_states():
                raise UserError(_(
                    "State %(state)s is not valid for a %(direction)s check.",
                    state=new_state, direction=check.check_type,
                ))
            old_state = check.state
            check.with_context(**{CTX_STATE_TRANSITION: True}).write({"state": new_state})
            check._log_event(event_type, old_state=old_state, new_state=new_state, note=note, source=source)

    def _log_event(self, event_type, old_state=False, new_state=False, note=False, source=False):
        values = [
            check._prepare_event_vals(event_type, old_state, new_state, note, source)
            for check in self
        ]
        return self.env["check.event"].sudo().create(values)

    def _prepare_event_vals(self, event_type, old_state, new_state, note, source):
        self.ensure_one()
        return {
            "check_id": self.id,
            "event_type": event_type,
            "user_id": self.env.user.id,
            "old_state": old_state or False,
            "new_state": new_state or self.state,
            "note": note or False,
            "res_model": source._name if source else False,
            "res_id": source.id if source else False,
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_events(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("sa_check_management.action_check_event")
        action["domain"] = [("check_id", "=", self.id)]
        action["context"] = {"create": False}
        return action
