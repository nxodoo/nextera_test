from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

CTX_DEPOSIT_SYSTEM_WRITE = "sa_check_deposit_system_write"
GROUP_MANAGER = "sa_check_management.group_check_manager"
OPEN_DEPOSIT_STATES = ("draft", "confirmed")


class CheckDeposit(models.Model):
    _name = "check.deposit"
    _description = "Check Deposit"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default="/")
    journal_id = fields.Many2one(
        "account.journal", string="Bank", required=True, check_company=True,
        domain="[('type', '=', 'bank')]", tracking=True,
    )
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    reference = fields.Char(string="Deposit Slip", tracking=True)
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        required=True, default="draft", readonly=True, copy=False, tracking=True,
    )
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", compute="_compute_currency_id", store=True)
    line_ids = fields.One2many("check.deposit.line", "deposit_id", string="Checks")
    check_count = fields.Integer(compute="_compute_totals", store=True)
    total_amount = fields.Monetary(currency_field="currency_id", compute="_compute_totals", store=True)
    notes = fields.Html()

    @api.depends("journal_id", "company_id")
    def _compute_currency_id(self):
        for deposit in self:
            deposit.currency_id = deposit.journal_id.currency_id or deposit.company_id.currency_id

    @api.depends("line_ids.amount", "line_ids.state")
    def _compute_totals(self):
        for deposit in self:
            lines = deposit.line_ids.filtered(lambda line: line.state != "cancelled")
            deposit.check_count = len(lines)
            deposit.total_amount = sum(lines.mapped("amount"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = self.env["ir.sequence"].sudo().with_company(company_id).next_by_code(
                    "sa.check.deposit"
                ) or "/"
        return super().create(vals_list)

    def write(self, vals):
        if {"journal_id", "date", "company_id"}.intersection(vals) and self.filtered(lambda d: d.state != "draft"):
            raise UserError(_("The bank and date of a confirmed deposit cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda deposit: deposit.state != "draft"):
            raise UserError(_("Only draft deposits can be deleted; cancel confirmed deposits instead."))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_confirm(self):
        for deposit in self:
            deposit._validate_confirmable()
            deposit._set_state("confirmed")
            for line in deposit.line_ids:
                line._number_attempt()
                action = "deposit" if line.check_id.state == "received" else "redeposit"
                line.check_id._transition(action, note=_("Deposit %s", deposit.name))
        return True

    def action_cancel(self):
        for deposit in self:
            if deposit.state == "draft":
                deposit.line_ids._set_line_state("cancelled")
            else:
                deposit._cancel_confirmed()
            deposit._set_state("cancelled")
        return True

    def _cancel_confirmed(self):
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group(GROUP_MANAGER):
            raise AccessError(_("Only a Check Manager can cancel a confirmed deposit."))
        if self.line_ids.filtered(lambda line: line.state == "collected"):
            raise UserError(_("Deposit %s has collected checks and cannot be cancelled.", self.name))
        for line in self.line_ids.filtered(lambda line: line.state == "pending"):
            line.check_id._apply_withdraw(_("Deposit %s cancelled", self.name))

    def _validate_confirmable(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Deposit %s is already confirmed.", self.name))
        if not self.line_ids:
            raise UserError(_("Add at least one check to deposit %s.", self.name))
        if self.date > fields.Date.context_today(self):
            raise UserError(_("The deposit date cannot be in the future."))

    def _set_state(self, state):
        self.ensure_one()
        super(CheckDeposit, self).write({"state": state})

    def _update_done_state(self):
        for deposit in self.filtered(lambda d: d.state == "confirmed"):
            if not deposit.line_ids.filtered(lambda line: line.state == "pending"):
                deposit._set_state("done")


class CheckDepositLine(models.Model):
    _name = "check.deposit.line"
    _description = "Check Deposit Line"
    _order = "deposit_id, id"
    _check_company_auto = True

    deposit_id = fields.Many2one("check.deposit", required=True, index=True, ondelete="cascade")
    check_id = fields.Many2one(
        "check.check", required=True, index=True, ondelete="restrict", check_company=True,
        domain="[('check_type', '=', 'incoming'), ('state', 'in', ('received', 'bounced')),"
               " ('purpose', 'not in', ('guarantee', 'security'))]",
    )
    partner_id = fields.Many2one(related="check_id.partner_id")
    check_number = fields.Char(related="check_id.check_number")
    bank_id = fields.Many2one(related="check_id.bank_id", string="Drawer Bank")
    due_date = fields.Date(related="check_id.due_date")
    amount = fields.Monetary(related="check_id.amount", store=True)
    currency_id = fields.Many2one(related="check_id.currency_id", store=True)
    attempt = fields.Integer(default=1, readonly=True)
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("collected", "Collected"),
            ("bounced", "Bounced"),
            ("withdrawn", "Withdrawn"),
            ("cancelled", "Cancelled"),
        ],
        required=True, default="pending", readonly=True,
    )
    result_date = fields.Date(readonly=True)
    journal_id = fields.Many2one(related="deposit_id.journal_id", string="Deposit Bank")
    deposit_date = fields.Date(related="deposit_id.date")
    deposit_state = fields.Selection(related="deposit_id.state", store=True, string="Deposit Status")
    company_id = fields.Many2one(related="deposit_id.company_id", store=True, index=True)
    is_early = fields.Boolean(compute="_compute_is_early", help="Deposited before the check due date.")

    @api.depends("due_date", "deposit_id.date")
    def _compute_is_early(self):
        for line in self:
            line.is_early = bool(line.due_date and line.deposit_id.date and line.deposit_id.date < line.due_date)

    # ------------------------------------------------------------------
    # Constraints (one rule each)
    # ------------------------------------------------------------------
    @api.constrains("check_id", "deposit_id", "state")
    def _check_single_open_deposit(self):
        for line in self.filtered(lambda l: l.state == "pending"):
            duplicate = self.search_count([
                ("id", "!=", line.id),
                ("check_id", "=", line.check_id.id),
                ("state", "=", "pending"),
                ("deposit_state", "in", OPEN_DEPOSIT_STATES),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Check %(check)s is already in another open deposit.", check=line.check_id.display_name,
                ))

    @api.constrains("check_id", "deposit_id")
    def _check_eligible_check(self):
        for line in self.filtered(lambda l: l.deposit_id.state == "draft"):
            check = line.check_id
            if check.check_type != "incoming" or check.state not in ("received", "bounced"):
                raise ValidationError(_(
                    "Only received or bounced incoming checks can be deposited (%(check)s).",
                    check=check.display_name,
                ))
            if check.purpose in ("guarantee", "security"):
                raise ValidationError(_("Guarantee and security checks cannot be deposited for collection."))
            if check.currency_id != line.deposit_id.currency_id:
                raise ValidationError(_(
                    "Check %(check)s is in %(check_currency)s but the bank account is in %(bank_currency)s.",
                    check=check.display_name, check_currency=check.currency_id.name,
                    bank_currency=line.deposit_id.currency_id.name,
                ))

    # ------------------------------------------------------------------
    # Editability
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._guard_deposit_editable()
        return lines

    def write(self, vals):
        self._guard_deposit_editable()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft_deposit(self):
        self._guard_deposit_editable()

    def _guard_deposit_editable(self):
        if self.env.context.get(CTX_DEPOSIT_SYSTEM_WRITE):
            return
        if self.deposit_id.filtered(lambda deposit: deposit.state != "draft"):
            raise UserError(_("Checks can only be added or removed while the deposit is in Draft."))

    def _set_line_state(self, state, date=False):
        self.with_context(**{CTX_DEPOSIT_SYSTEM_WRITE: True}).write({"state": state, "result_date": date})
        self.deposit_id._update_done_state()

    def _number_attempt(self):
        self.ensure_one()
        previous = self.check_id.deposit_line_ids.filtered(
            lambda line: line != self and line.state in ("collected", "bounced")
        )
        self.with_context(**{CTX_DEPOSIT_SYSTEM_WRITE: True}).write({"attempt": len(previous) + 1})

    # ------------------------------------------------------------------
    # Line buttons
    # ------------------------------------------------------------------
    def action_collect(self):
        self.ensure_one()
        return self.check_id.action_open_collection_wizard()

    def action_bounce(self):
        self.ensure_one()
        return self.check_id.action_open_bounce_wizard()
