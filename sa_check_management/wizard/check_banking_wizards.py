from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _validate_not_future(record, date):
    if date > fields.Date.context_today(record):
        raise UserError(_("The date cannot be in the future."))


class CheckDepositWizard(models.TransientModel):
    _name = "check.deposit.wizard"
    _description = "Deposit Checks"

    check_ids = fields.Many2many("check.check", string="Checks", required=True, readonly=True)
    company_id = fields.Many2one("res.company", compute="_compute_company_id")
    journal_id = fields.Many2one(
        "account.journal", string="Bank", required=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    reference = fields.Char(string="Deposit Slip")
    early_check_count = fields.Integer(compute="_compute_early_check_count")

    @api.depends("check_ids")
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.check_ids.company_id[:1] or self.env.company

    @api.depends("check_ids", "date")
    def _compute_early_check_count(self):
        for wizard in self:
            wizard.early_check_count = len(wizard.check_ids.filtered(lambda c: c.due_date > wizard.date))

    def action_confirm(self):
        self.ensure_one()
        if len(self.check_ids.company_id) > 1:
            raise UserError(_("Deposit checks of one company at a time."))
        deposit = self.env["check.deposit"].create({
            "journal_id": self.journal_id.id,
            "date": self.date,
            "reference": self.reference,
            "company_id": self.company_id.id,
            "line_ids": [fields.Command.create({"check_id": check.id}) for check in self.check_ids],
        })
        deposit.action_confirm()
        return {
            "type": "ir.actions.act_window",
            "res_model": "check.deposit",
            "res_id": deposit.id,
            "view_mode": "form",
        }


class CheckCollectionWizard(models.TransientModel):
    _name = "check.collection.wizard"
    _description = "Collect or Clear Checks"

    check_ids = fields.Many2many("check.check", string="Checks", required=True, readonly=True)
    mode = fields.Selection(
        selection=[("collect", "Collect"), ("clear", "Clear")], compute="_compute_mode",
    )
    action_date = fields.Date(string="Bank Date", required=True, default=fields.Date.context_today)
    fee_amount = fields.Monetary(string="Bank Fee", currency_field="fee_currency_id")
    fee_currency_id = fields.Many2one(
        "res.currency", string="Fee Currency", compute="_compute_fee_currency_id", store=True, readonly=False,
    )
    note = fields.Text()

    @api.depends("check_ids")
    def _compute_mode(self):
        for wizard in self:
            wizard.mode = "clear" if wizard.check_ids[:1].check_type == "outgoing" else "collect"

    @api.depends("check_ids")
    def _compute_fee_currency_id(self):
        for wizard in self:
            journal = wizard._fee_journal().sudo()
            wizard.fee_currency_id = journal.currency_id or wizard.check_ids.company_id[:1].currency_id or self.env.company.currency_id

    def _fee_journal(self):
        self.ensure_one()
        check = self.check_ids[:1]
        if check.state == "discounted":
            return check.discount_journal_id
        return check.current_deposit_line_id.journal_id if check.check_type == "incoming" else check.journal_id

    def action_confirm(self):
        self.ensure_one()
        _validate_not_future(self, self.action_date)
        self._validate_selection()
        journal = self._fee_journal()
        discounted = self.check_ids.filtered(lambda check: check.state == "discounted")
        if discounted:
            discounted._apply_discount_collect(self.action_date, self.note)
        if self.mode == "collect":
            (self.check_ids - discounted)._apply_collect(self.action_date, self.note)
        else:
            self.check_ids._apply_clear(self.action_date, self.note)
        if self.fee_amount:
            self.check_ids._post_bank_fee(self.fee_amount, self.action_date, journal, currency=self.fee_currency_id)
        return {"type": "ir.actions.act_window_close"}

    def _validate_selection(self):
        if len(set(self.check_ids.mapped("check_type"))) > 1:
            raise UserError(_("Collect incoming checks and clear outgoing checks separately."))
        if self.fee_amount < 0:
            raise UserError(_("The bank fee cannot be negative."))
        if self.fee_amount and len(self.check_ids) > 1:
            raise UserError(_("Record a bank fee on one check at a time."))


class CheckBounceWizard(models.TransientModel):
    _name = "check.bounce.wizard"
    _description = "Bounced Check"

    check_id = fields.Many2one("check.check", required=True, readonly=True)
    action_date = fields.Date(string="Bounce Date", required=True, default=fields.Date.context_today)
    reason_id = fields.Many2one("check.bounce.reason", string="Reason", required=True)
    reason_requires_note = fields.Boolean(related="reason_id.requires_note")
    note = fields.Text()
    bank_reference = fields.Char(string="Bank Rejection Reference")
    fee_amount = fields.Monetary(string="Bank Fee", currency_field="fee_currency_id")
    fee_currency_id = fields.Many2one(
        "res.currency", string="Fee Currency", compute="_compute_fee_currency_id", store=True, readonly=False,
    )
    fee_policy = fields.Selection(related="check_id.company_id.check_bounce_fee_policy")
    has_bank = fields.Boolean(compute="_compute_has_bank")
    attachment = fields.Binary(string="Evidence")
    attachment_name = fields.Char()

    @api.depends("check_id")
    def _compute_fee_currency_id(self):
        for wizard in self:
            journal = wizard._bank_journal().sudo()
            wizard.fee_currency_id = journal.currency_id or wizard.check_id.company_id.currency_id

    @api.depends("check_id")
    def _compute_has_bank(self):
        for wizard in self:
            wizard.has_bank = bool(wizard._bank_journal())

    def _bank_journal(self):
        self.ensure_one()
        check = self.check_id
        if check.state == "discounted":
            return check.discount_journal_id
        return check.current_deposit_line_id.journal_id if check.check_type == "incoming" else check.journal_id

    def action_confirm(self):
        self.ensure_one()
        _validate_not_future(self, self.action_date)
        self._validate_note()
        if self.fee_amount < 0:
            raise UserError(_("The bank fee cannot be negative."))
        check = self.check_id
        journal = self._bank_journal()
        incoming = check.check_type == "incoming"
        if self.fee_amount and not journal:
            raise UserError(_("There is no bank to charge a fee for this check."))
        if check.state == "endorsed":
            apply = check._apply_endorse_bounce
        elif check.state == "discounted":
            apply = check._apply_discount_bounce
        elif incoming:
            apply = check._apply_bounce
        else:
            apply = check._apply_bank_reject
        apply(self.reason_id, self.action_date, self.note, self.bank_reference)
        if self.fee_amount:
            check._post_bank_fee(
                self.fee_amount, self.action_date, journal,
                charge_partner=incoming and self.fee_policy == "partner",
                label=_("Bounce fee for check %s", check.display_name),
                currency=self.fee_currency_id,
            )
        self._attach_evidence()
        return {"type": "ir.actions.act_window_close"}

    def _validate_note(self):
        if self.reason_requires_note and not (self.note or "").strip():
            raise UserError(_("Describe the bounce reason."))

    def _attach_evidence(self):
        if self.attachment:
            self.env["ir.attachment"].create({
                "name": self.attachment_name or _("Bounce evidence"),
                "datas": self.attachment,
                "res_model": "check.check",
                "res_id": self.check_id.id,
            })
