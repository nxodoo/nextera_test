from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CheckReplacementWizard(models.TransientModel):
    _name = "check.replacement.wizard"
    _description = "Replace Check"

    check_id = fields.Many2one("check.check", string="Old Check", required=True, readonly=True)
    check_type = fields.Selection(related="check_id.check_type")
    currency_id = fields.Many2one(related="check_id.currency_id")
    company_id = fields.Many2one(related="check_id.company_id")
    old_amount = fields.Monetary(related="check_id.amount", string="Old Amount")
    check_number = fields.Char(string="New Check Number", required=True)
    amount = fields.Monetary(currency_field="currency_id", required=True)
    issue_date = fields.Date(required=True, default=fields.Date.context_today)
    due_date = fields.Date(required=True)
    bank_id = fields.Many2one("res.bank", string="Bank")
    drawer_is_partner = fields.Boolean(string="Drawn by Partner", default=True)
    drawer_name = fields.Char()
    drawer_account_number = fields.Char()
    journal_id = fields.Many2one(
        "account.journal", string="Bank Journal",
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
    )
    transfer_allocations = fields.Boolean(
        string="Move Invoice Allocations", default=True,
        help="Allocate the replacement to the invoices or bills the old check covered, up to its amount.",
    )
    receive_now = fields.Boolean(string="Receive Replacement Now", default=True)
    note = fields.Text()

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        old = self.env["check.check"].browse(values.get("check_id") or self.env.context.get("default_check_id"))
        if old:
            values.setdefault("amount", old.amount)
            values.setdefault("due_date", old.due_date)
            values.setdefault("bank_id", old.bank_id.id)
            values.setdefault("drawer_is_partner", old.drawer_is_partner)
            values.setdefault("drawer_name", old.drawer_name)
            values.setdefault("drawer_account_number", old.drawer_account_number)
            values.setdefault("journal_id", old.journal_id.id)
        return values

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("The replacement amount must be greater than zero."))
        replacement = self.check_id._apply_replace(
            self._replacement_vals(),
            transfer_allocations=self.transfer_allocations,
            receive_now=self.receive_now,
            note=self.note,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "check.check",
            "res_id": replacement.id,
            "view_mode": "form",
        }

    def _replacement_vals(self):
        self.ensure_one()
        vals = {
            "check_number": self.check_number,
            "amount": self.amount,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "bank_id": self.bank_id.id,
        }
        if self.check_type == "incoming":
            vals.update({
                "drawer_is_partner": self.drawer_is_partner,
                "drawer_name": self.drawer_name,
                "drawer_account_number": self.drawer_account_number,
            })
        else:
            vals["journal_id"] = self.journal_id.id
        return vals


class CheckSettleWizard(models.TransientModel):
    _name = "check.settle.wizard"
    _description = "Check Settled by Other Payment"

    check_id = fields.Many2one("check.check", required=True, readonly=True)
    partner_id = fields.Many2one(related="check_id.partner_id")
    company_id = fields.Many2one(related="check_id.company_id")
    action_date = fields.Date(string="Settlement Date", required=True, default=fields.Date.context_today)
    note = fields.Text(string="How was it settled?", required=True)
    payment_ids = fields.Many2many(
        "account.payment", string="Related Payments",
        domain="[('partner_id.commercial_partner_id', '=', partner_id), ('company_id', '=', company_id),"
               " ('state', 'in', ('in_process', 'paid'))]",
    )

    def action_confirm(self):
        self.ensure_one()
        if not (self.note or "").strip():
            raise UserError(_("Describe how the check was settled."))
        if self.action_date > fields.Date.context_today(self):
            raise UserError(_("The settlement date cannot be in the future."))
        self.check_id._apply_settle(self.note.strip(), self.action_date, self.payment_ids)
        return {"type": "ir.actions.act_window_close"}


class CheckLegalWizard(models.TransientModel):
    _name = "check.legal.wizard"
    _description = "Check Legal Action"

    check_id = fields.Many2one("check.check", required=True, readonly=True)
    action_date = fields.Date(string="Filing Date", required=True, default=fields.Date.context_today)
    case_number = fields.Char(required=True)
    lawyer_id = fields.Many2one("res.partner", string="Lawyer")
    court = fields.Char()
    note = fields.Text()

    def action_confirm(self):
        self.ensure_one()
        if not (self.case_number or "").strip():
            raise UserError(_("Enter the case number."))
        if self.action_date > fields.Date.context_today(self):
            raise UserError(_("The filing date cannot be in the future."))
        self.check_id._apply_legal(self.action_date, self.case_number.strip(), self.lawyer_id, self.court, self.note)
        return {"type": "ir.actions.act_window_close"}


class CheckDiscountWizard(models.TransientModel):
    _name = "check.discount.wizard"
    _description = "Discount Check at Bank"

    check_id = fields.Many2one("check.check", required=True, readonly=True)
    currency_id = fields.Many2one(related="check_id.currency_id")
    company_id = fields.Many2one(related="check_id.company_id")
    amount = fields.Monetary(related="check_id.amount", string="Check Amount")
    due_date = fields.Date(related="check_id.due_date")
    term_id = fields.Many2one(
        "check.discount.term", string="Bank", required=True,
        domain="[('company_id', '=', company_id)]",
    )
    journal_id = fields.Many2one(related="term_id.journal_id", string="Bank Journal")
    action_date = fields.Date(string="Discount Date", required=True, default=fields.Date.context_today)
    days = fields.Integer(string="Days to Maturity", compute="_compute_days")
    advance = fields.Monetary(
        string="Bank Advance", currency_field="currency_id", compute="_compute_advance", store=True, readonly=False,
    )
    fee = fields.Monetary(
        string="Discount Charges", currency_field="currency_id", compute="_compute_fee", store=True,
        readonly=False, help="Interest and fees the bank keeps from the advance.",
    )
    net_amount = fields.Monetary(string="Received from Bank", currency_field="currency_id", compute="_compute_net_amount")
    note = fields.Text()

    @api.depends("action_date", "due_date")
    def _compute_days(self):
        for wizard in self:
            wizard.days = (wizard.due_date - wizard.action_date).days if wizard.due_date and wizard.action_date else 0

    # Separate computes: setting one value by hand must not freeze the other.
    @api.depends("term_id", "amount")
    def _compute_advance(self):
        for wizard in self:
            wizard.advance = wizard.term_id._advance_for(wizard.amount) if wizard.term_id else wizard.amount

    @api.depends("term_id", "advance", "days")
    def _compute_fee(self):
        for wizard in self:
            wizard.fee = wizard.term_id._charges_for(wizard.advance, wizard.days) if wizard.term_id else 0.0

    @api.depends("advance", "fee")
    def _compute_net_amount(self):
        for wizard in self:
            wizard.net_amount = wizard.advance - wizard.fee

    def action_confirm(self):
        self.ensure_one()
        self._validate_inputs()
        self.check_id._apply_discount(self.journal_id, self.action_date, self.advance, self.fee, self.note)
        return {"type": "ir.actions.act_window_close"}

    def _validate_inputs(self):
        if self.action_date > fields.Date.context_today(self):
            raise UserError(_("The discount date cannot be in the future."))
        if self.action_date >= self.due_date:
            raise UserError(_("A check can only be discounted before its due date; deposit it instead."))
        if self.advance <= 0 or self.currency_id.compare_amounts(self.advance, self.amount) > 0:
            raise UserError(_("The bank advance must be more than zero and at most the check amount."))
        if self.fee < 0 or self.currency_id.compare_amounts(self.fee, self.advance) >= 0:
            raise UserError(_("The discount charges must be between zero and the bank advance."))
        if self.term_id.currency_id != self.currency_id:
            raise UserError(_("The bank account currency must match the check currency."))
