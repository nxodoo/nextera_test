from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .check_banking import CTX_INTERNAL_ACCOUNTING, GROUP_TREASURY
from .check_check import CTX_ALLOW_LOCKED_EDIT
from .check_lifecycle import ACTION_EVENTS, ACTION_GROUPS, GROUP_MANAGER, TRANSITIONS

COLLATERAL_PURPOSES = frozenset({"guarantee", "security"})

GUARANTEE_REFERENCE_MODELS = (
    "sale.order",
    "purchase.order",
    "project.project",
    "account.analytic.account",
    "account.move",
    "hr.employee",
    "res.partner",
)

TRANSITIONS["incoming"].update({
    "endorse": (frozenset({"received"}), "endorsed"),
    "endorse_bounce": (frozenset({"endorsed"}), "bounced"),
    "unendorse": (frozenset({"endorsed"}), "received"),
    "release": (frozenset({"received"}), "returned"),
    "invoke": (frozenset({"received"}), "received"),
})
TRANSITIONS["outgoing"].update({
    "release": (frozenset({"issued", "delivered"}), "returned"),
    "invoke": (frozenset({"delivered"}), "delivered"),
})
ACTION_GROUPS.update({
    "endorse": GROUP_TREASURY,
    "endorse_bounce": GROUP_TREASURY,
    "unendorse": GROUP_MANAGER,
    "release": GROUP_MANAGER,
    "invoke": GROUP_MANAGER,
})
ACTION_EVENTS.update({
    "endorse": "endorsed",
    "endorse_bounce": "bounced",
    "unendorse": "unendorsed",
    "release": "released",
    "invoke": "invoked",
})


class CheckEndorsementLine(models.Model):
    _name = "check.endorsement.line"
    _description = "Check Endorsement Line"
    _order = "check_id, id"

    check_id = fields.Many2one("check.check", required=True, index=True, ondelete="cascade", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Endorsee", required=True, readonly=True)
    move_line_id = fields.Many2one("account.move.line", string="Journal Item", readonly=True, ondelete="restrict")
    document_name = fields.Char(related="move_line_id.move_id.name", store=True, string="Document")
    amount = fields.Monetary(currency_field="currency_id", required=True, readonly=True)
    currency_id = fields.Many2one(related="check_id.currency_id", store=True)
    company_id = fields.Many2one(related="check_id.company_id", store=True, index=True)
    state = fields.Selection(
        selection=[("active", "Active"), ("reversed", "Reversed")],
        required=True, default="active", readonly=True,
    )


class CheckCheck(models.Model):
    _inherit = "check.check"

    endorsed_partner_id = fields.Many2one("res.partner", string="Endorsed To", readonly=True, copy=False)
    endorsed_date = fields.Date(readonly=True, copy=False)
    endorsement_note = fields.Text(readonly=True, copy=False)
    endorsement_line_ids = fields.One2many("check.endorsement.line", "check_id", string="Endorsement", readonly=True)
    guarantee_expiry_date = fields.Date(string="Guarantee Expiry", tracking=True)
    guarantee_description = fields.Char(string="Guarantee For", help="Contract, tender or obligation it secures.")
    guarantee_reference = fields.Reference(
        selection="_selection_guarantee_reference", string="Guarantee Document",
    )
    is_guarantee_expired = fields.Boolean(
        compute="_compute_is_guarantee_expired", search="_search_is_guarantee_expired",
    )

    @api.model
    def _selection_guarantee_reference(self):
        models_in_registry = [name for name in GUARANTEE_REFERENCE_MODELS if name in self.env]
        records = self.env["ir.model"].sudo().search([("model", "in", models_in_registry)])
        return [(record.model, record.name) for record in records]

    @api.depends("purpose", "guarantee_expiry_date", "state")
    def _compute_is_guarantee_expired(self):
        today = fields.Date.context_today(self)
        for check in self:
            check.is_guarantee_expired = bool(
                check.purpose in COLLATERAL_PURPOSES
                and check.guarantee_expiry_date
                and check.guarantee_expiry_date < today
                and check.state not in ("returned", "cancelled")
            )

    def _search_is_guarantee_expired(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Unsupported search on expired guarantees."))
        domain = [
            ("purpose", "in", list(COLLATERAL_PURPOSES)),
            ("guarantee_expiry_date", "<", fields.Date.context_today(self)),
            ("state", "not in", ("returned", "cancelled")),
        ]
        positive = (operator == "=") == value
        return domain if positive else ["!", "&", "&"] + domain

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_open_endorsement_wizard(self):
        self.ensure_one()
        return self._open_exception_wizard("check.endorsement.wizard", _("Endorse Check"))

    def action_open_endorse_bounce_wizard(self):
        self.ensure_one()
        return self._open_banking_wizard("check.bounce.wizard", _("Endorsed Check Bounced"))

    def action_open_unendorse_wizard(self):
        return self._open_action_wizard("unendorse")

    def action_open_release_wizard(self):
        return self._open_action_wizard("release")

    def action_open_invoke_wizard(self):
        return self._open_action_wizard("invoke")

    # ------------------------------------------------------------------
    # Wizard-backed actions
    # ------------------------------------------------------------------
    def _apply_endorse(self, partner, date, line_vals, note=False):
        """Endorse to ``partner``; ``line_vals`` are ``(move_line, amount)`` pairs on its bills."""
        self.ensure_one()
        self.env["check.endorsement.line"].sudo().create([{
            "check_id": self.id,
            "partner_id": partner.id,
            "move_line_id": line.id,
            "amount": amount,
        } for line, amount in line_vals])
        event_note = "\n".join(filter(None, [_("Endorsed to %s", partner.display_name), note]))
        self._transition("endorse", note=event_note, extra_vals={
            "endorsed_partner_id": partner.id,
            "endorsed_date": date,
            "endorsement_note": note or False,
        })

    def _apply_endorse_bounce(self, reason, date, note=False, reference=False):
        for check in self:
            event_note = "\n".join(filter(None, [
                _("Returned bounced by %s", check.endorsed_partner_id.display_name),
                reason.name, note, reference and _("Bank reference: %s", reference),
            ]))
            check._transition("endorse_bounce", note=event_note, extra_vals={
                "bounce_count": check.bounce_count + 1,
                "last_bounce_date": date,
                "last_bounce_reason_id": reason.id,
                "last_bounce_reference": reference or False,
                "last_bounce_note": note or False,
            })

    def _apply_unendorse(self, reason):
        self._transition("unendorse", note=reason, extra_vals={
            "endorsed_partner_id": False,
            "endorsed_date": False,
            "endorsement_note": False,
        })

    def _apply_release(self, reason, recipient, date):
        note = _("%(reason)s\nReleased to: %(recipient)s", reason=reason, recipient=recipient)
        self._transition("release", note=note, extra_vals={
            "return_reason": reason,
            "return_recipient": recipient,
            "returned_date": date,
        })

    def _apply_invoke(self, reason):
        self.with_context(**{CTX_ALLOW_LOCKED_EDIT: True})._transition("invoke", note=reason, extra_vals={
            "purpose": "payment",
        })

    # ------------------------------------------------------------------
    # Transition integration
    # ------------------------------------------------------------------
    def _validate_transition(self, action):
        super()._validate_transition(action)
        validator = {
            "endorse": self._validate_endorsable,
            "release": self._validate_collateral,
            "invoke": self._validate_collateral,
            "return": self._validate_not_collateral,
            "clear": self._validate_not_collateral,
        }.get(action)
        if validator:
            validator()

    def _validate_endorsable(self):
        self.ensure_one()
        if self.purpose in COLLATERAL_PURPOSES:
            raise UserError(_("Guarantee and security checks cannot be endorsed."))
        if not self._creates_entries():
            raise UserError(_("Check %(check)s does not create accounting entries and cannot be endorsed.",
                              check=self.display_name))

    def _validate_collateral(self):
        self.ensure_one()
        if self.purpose not in COLLATERAL_PURPOSES:
            raise UserError(_("Only guarantee and security checks can be released or invoked."))

    def _validate_not_collateral(self):
        self.ensure_one()
        if self.purpose in COLLATERAL_PURPOSES:
            raise UserError(_(
                "Check %(check)s is a guarantee: release it to give it back, or invoke it before it is cashed.",
                check=self.display_name,
            ))

    # Handlers below run through the generic ``_after_<action>`` dispatch (check_banking),
    # already inside the internal-accounting context.
    def _after_endorse(self):
        if self.accounting_status == "none":
            # Settlement at collection: handing the check over settles the customer side now.
            self._post_check_accounting(at_collection=True)
        self._validate_endorsement_lines_open()
        self._create_endorsement_entry(self.endorsed_partner_id, self.endorsed_date)

    def _after_endorse_bounce(self):
        self._reverse_check_accounting(entry_types=("deposit", "endorsement"))
        self.endorsement_line_ids.filtered(lambda line: line.state == "active").sudo().state = "reversed"

    def _after_unendorse(self):
        self._reverse_check_accounting(include_payments=False, entry_types=("endorsement",))
        self.endorsement_line_ids.filtered(lambda line: line.state == "active").sudo().state = "reversed"

    def _after_invoke(self):
        self._post_check_accounting()

    # ------------------------------------------------------------------
    # Endorsement accounting
    # ------------------------------------------------------------------
    def _active_endorsement_lines(self):
        self.ensure_one()
        return self.sudo().endorsement_line_ids.filtered(lambda line: line.state == "active")

    def _validate_endorsement_lines_open(self):
        self.ensure_one()
        for line in self._active_endorsement_lines():
            item = line.move_line_id
            open_amount = 0.0 if item.reconciled else abs(item.amount_residual_currency)
            if self.currency_id.compare_amounts(line.amount, open_amount) > 0:
                raise UserError(_(
                    "%(document)s now has only %(open)s open.",
                    document=item.move_id.display_name, open=self.currency_id.format(open_amount),
                ))

    def _create_endorsement_entry(self, partner, date):
        """Cr checks receivable (the check leaves us) / Dr endorsee payable, one line per bill."""
        self.ensure_one()
        holding = self._open_holding_lines()
        if not holding:
            raise UserError(_("Check %(check)s has no open balance to endorse.", check=self.display_name))
        company = self.company_id._sa_check_accounting_setup()
        payable = partner.with_company(company).property_account_payable_id
        endorsement_lines = self._active_endorsement_lines()
        total = sum(holding.mapped("amount_residual_currency"))
        targets = [(line, line.amount) for line in endorsement_lines]
        remainder = total - sum(endorsement_lines.mapped("amount"))
        if self.currency_id.compare_amounts(remainder, 0.0) < 0:
            raise UserError(_("The endorsed bills exceed the check amount."))
        if not self.currency_id.is_zero(remainder):
            targets.append((None, remainder))
        name = _("Check %(check)s endorsed to %(partner)s", check=self.display_name, partner=partner.display_name)
        target_vals = []
        for _line, amount in targets:
            balance = self.currency_id._convert(amount, company.currency_id, company, date)
            target_vals.append({
                "account_id": payable.id, "partner_id": partner.id, "name": name,
                "currency_id": self.currency_id.id, "amount_currency": amount, "balance": balance,
            })
        closing_vals = {
            "account_id": holding.account_id[:1].id, "partner_id": self.partner_id.id, "name": name,
            "currency_id": self.currency_id.id, "amount_currency": -total,
            "balance": -sum(vals["balance"] for vals in target_vals),
        }
        move = self._create_check_entry("endorsement", company.check_portfolio_journal_id, date,
                                        [closing_vals] + target_vals)
        move_lines = move.line_ids.sorted("id")
        (move_lines[0] | holding).reconcile()
        for (line, _amount), target_line in zip(targets, move_lines[1:]):
            if line:
                (target_line | line.move_line_id).reconcile()
        self._log_event("accounting", note=_("Posted: %s", move.name), source=move)
        return move
