from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .check_banking import CTX_INTERNAL_ACCOUNTING, GROUP_TREASURY
from .check_lifecycle import ACTION_EVENTS, ACTION_GROUPS, GROUP_MANAGER, TRANSITIONS

STALE_SOURCE_STATES = frozenset({"issued", "delivered", "presented"})

TRANSITIONS["incoming"].update({
    "replace": (frozenset({"received", "bounced", "legal"}), "replaced"),
    "settle": (frozenset({"bounced", "legal"}), "settled"),
    "legal": (frozenset({"bounced"}), "legal"),
    "lose": (frozenset({"received"}), "lost"),
    "return": (frozenset({"received", "bounced", "legal"}), "returned"),
})
TRANSITIONS["outgoing"].update({
    "lose": (frozenset({"issued", "delivered"}), "lost"),
    "stop": (STALE_SOURCE_STATES, "stopped"),
    "bank_reject": (STALE_SOURCE_STATES, "rejected"),
    "replace": (frozenset({"rejected"}), "replaced"),
    "settle": (frozenset({"rejected"}), "settled"),
    "void_stale": (STALE_SOURCE_STATES, "cancelled"),
})
ACTION_GROUPS.update({
    "replace": GROUP_TREASURY,
    "settle": GROUP_TREASURY,
    "legal": GROUP_TREASURY,
    "stop": GROUP_TREASURY,
    "bank_reject": GROUP_TREASURY,
    "lose": GROUP_MANAGER,
    "void_stale": GROUP_MANAGER,
})
ACTION_EVENTS.update({
    "replace": "replaced",
    "settle": "settled",
    "legal": "legal",
    "lose": "lost",
    "stop": "stopped",
    "bank_reject": "rejected",
    "void_stale": "cancelled",
})

# Actions whose accounting must be reversed so the partner owes again.
REVERSING_EXCEPTIONS = frozenset({"replace", "lose", "stop", "bank_reject", "void_stale"})

# Fields of a replacement copied from the old check unless the user changes them.
REPLACEMENT_COPIED_FIELDS = ("partner_id", "currency_id", "purpose", "company_id", "responsible_user_id")


class CheckCheck(models.Model):
    _inherit = "check.check"

    replaces_check_id = fields.Many2one(
        "check.check", string="Replaces", readonly=True, copy=False, index="btree_not_null",
    )
    replaced_by_check_id = fields.Many2one(
        "check.check", string="Replaced By", readonly=True, copy=False, index="btree_not_null",
    )
    settled_date = fields.Date(readonly=True, copy=False)
    settle_note = fields.Text(string="Settlement Details", readonly=True, copy=False)
    settled_payment_ids = fields.Many2many(
        "account.payment", "check_check_settled_payment_rel", "check_id", "payment_id",
        string="Settled By Payments", readonly=True, copy=False,
    )
    legal_date = fields.Date(string="Legal Action Date", readonly=True, copy=False)
    legal_lawyer_id = fields.Many2one("res.partner", string="Lawyer", readonly=True, copy=False)
    legal_case_number = fields.Char(string="Case Number", readonly=True, copy=False)
    legal_court = fields.Char(string="Court", readonly=True, copy=False)
    legal_note = fields.Text(readonly=True, copy=False)
    legal_days = fields.Integer(string="Days in Litigation", compute="_compute_legal_days")
    lost_date = fields.Date(readonly=True, copy=False)
    lost_reason = fields.Text(readonly=True, copy=False)
    stopped_date = fields.Date(readonly=True, copy=False)
    stop_reason = fields.Text(readonly=True, copy=False)
    stop_reference = fields.Char(string="Stop Payment Bank Reference", readonly=True, copy=False)
    is_stale = fields.Boolean(
        compute="_compute_is_stale", search="_search_is_stale",
        help="Outgoing check not cleared within the company's validity period.",
    )

    @api.depends("legal_date", "state")
    def _compute_legal_days(self):
        today = fields.Date.context_today(self)
        for check in self:
            check.legal_days = (today - check.legal_date).days if check.legal_date and check.state == "legal" else 0

    # ------------------------------------------------------------------
    # Stale outgoing checks (computed, never a lifecycle state)
    # ------------------------------------------------------------------
    @api.depends("check_type", "state", "issue_date", "company_id.check_stale_months")
    def _compute_is_stale(self):
        for check in self:
            check.is_stale = (
                check.check_type == "outgoing"
                and check.state in STALE_SOURCE_STATES
                and check.issue_date
                and check.issue_date < check._stale_limit_date()
            )

    def _stale_limit_date(self):
        self.ensure_one()
        return fields.Date.context_today(self) - relativedelta(months=self.company_id.check_stale_months)

    def _search_is_stale(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Unsupported search on stale checks."))
        stale_ids = []
        candidates = self.search([("check_type", "=", "outgoing"), ("state", "in", list(STALE_SOURCE_STATES))])
        for check in candidates:
            if check.issue_date < check._stale_limit_date():
                stale_ids.append(check.id)
        positive = (operator == "=") == value
        return [("id", "in" if positive else "not in", stale_ids)]

    # ------------------------------------------------------------------
    # Replacement chain integrity
    # ------------------------------------------------------------------
    @api.constrains("replaces_check_id", "replaced_by_check_id")
    def _check_replacement_chain(self):
        for check in self:
            if check in (check.replaces_check_id | check.replaced_by_check_id):
                raise ValidationError(_("A check cannot replace itself."))
            seen = check
            current = check.replaces_check_id
            while current:
                if current in seen:
                    raise ValidationError(_("Check replacements cannot form a loop."))
                seen |= current
                current = current.replaces_check_id

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_open_replacement_wizard(self):
        self.ensure_one()
        return self._open_exception_wizard("check.replacement.wizard", _("Replace Check"))

    def action_open_settle_wizard(self):
        self.ensure_one()
        return self._open_exception_wizard("check.settle.wizard", _("Settled by Other Payment"))

    def action_open_legal_wizard(self):
        self.ensure_one()
        return self._open_exception_wizard("check.legal.wizard", _("Legal Action"))

    def action_open_bank_reject_wizard(self):
        self.ensure_one()
        return self._open_banking_wizard("check.bounce.wizard", _("Check Rejected by Bank"))

    def action_open_stop_wizard(self):
        return self._open_action_wizard("stop")

    def action_open_lost_wizard(self):
        return self._open_action_wizard("lose")

    def action_open_void_stale_wizard(self):
        return self._open_action_wizard("void_stale")

    def _open_exception_wizard(self, model, title):
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": model,
            "view_mode": "form",
            "target": "new",
            "context": {"default_check_id": self.id},
        }

    # ------------------------------------------------------------------
    # Wizard-backed actions
    # ------------------------------------------------------------------
    def _apply_settle(self, note, date, payments=None):
        self.ensure_one()
        self._transition("settle", note=note, extra_vals={
            "settled_date": date,
            "settle_note": note,
            "settled_payment_ids": [fields.Command.set((payments or self.env["account.payment"]).ids)],
        })

    def _apply_legal(self, date, case_number, lawyer=None, court=False, note=False):
        self.ensure_one()
        event_note = "\n".join(filter(None, [_("Case %s", case_number), court, note]))
        self._transition("legal", note=event_note, extra_vals={
            "legal_date": date,
            "legal_case_number": case_number,
            "legal_lawyer_id": lawyer.id if lawyer else False,
            "legal_court": court or False,
            "legal_note": note or False,
        })

    def _apply_lose(self, reason, date):
        self._transition("lose", note=reason, extra_vals={"lost_date": date, "lost_reason": reason})

    def _apply_stop(self, reason, date, reference):
        note = _("%(reason)s\nBank reference: %(reference)s", reason=reason, reference=reference)
        self._transition("stop", note=note, extra_vals={
            "stopped_date": date,
            "stop_reason": reason,
            "stop_reference": reference,
        })

    def _apply_void_stale(self, reason):
        self._transition("void_stale", note=reason, extra_vals={
            "cancel_reason": reason,
            "cancelled_date": fields.Date.context_today(self),
        })

    def _apply_bank_reject(self, reason, date, note=False, reference=False):
        for check in self:
            event_note = "\n".join(filter(None, [reason.name, note, reference and _("Bank reference: %s", reference)]))
            check._transition("bank_reject", note=event_note, extra_vals={
                "bounce_count": check.bounce_count + 1,
                "last_bounce_date": date,
                "last_bounce_reason_id": reason.id,
                "last_bounce_reference": reference or False,
                "last_bounce_note": note or False,
            })

    def _apply_replace(self, new_vals, transfer_allocations=True, receive_now=False, note=False):
        """Close this check as replaced and create the replacement; returns the new check."""
        self.ensure_one()
        transition_note = "\n".join(filter(None, [
            _("Replaced by check number %s", new_vals.get("check_number")), note,
        ]))
        self._transition("replace", note=transition_note)
        replacement = self._create_replacement(new_vals)
        self.write({"replaced_by_check_id": replacement.id})
        if transfer_allocations:
            self._transfer_allocations_to(replacement)
        replacement._log_event("replaced", note=_("Replaces %s", self.display_name), source=self)
        if receive_now and replacement.check_type == "incoming":
            replacement.action_receive()
        return replacement

    def _create_replacement(self, new_vals):
        self.ensure_one()
        vals = {name: self[name].id if self._fields[name].type == "many2one" else self[name]
                for name in REPLACEMENT_COPIED_FIELDS}
        vals.update(new_vals)
        vals["replaces_check_id"] = self.id
        return self.env["check.check"].with_context(default_check_type=self.check_type).create(vals)

    def _transfer_allocations_to(self, replacement):
        """Re-allocate the old check's still-open documents to the replacement, up to its amount."""
        self.ensure_one()
        remaining = replacement.amount
        reserved = replacement._reserved_amounts(self.sudo().allocation_ids.move_line_id)
        vals_list = []
        for allocation in self.sudo().allocation_ids.sorted(lambda a: (a.date_maturity or fields.Date.today(), a.id)):
            line = allocation.move_line_id
            if line.reconciled or replacement.currency_id.is_zero(remaining):
                continue
            share = min(allocation.amount, replacement._item_available(line, reserved), remaining)
            if share > 0:
                vals_list.append({"check_id": replacement.id, "move_line_id": line.id, "amount": share})
                remaining -= share
        if vals_list:
            self.env["check.allocation"].sudo().create(vals_list)

    # ------------------------------------------------------------------
    # Transition integration
    # ------------------------------------------------------------------
    def _validate_transition(self, action):
        super()._validate_transition(action)
        if action == "void_stale" and not self.is_stale:
            raise UserError(_("Check %(check)s is not stale yet.", check=self.display_name))

    def _after_transition(self, action):
        super()._after_transition(action)
        if action in REVERSING_EXCEPTIONS:
            internal = self.with_context(**{CTX_INTERNAL_ACCOUNTING: True})
            internal._reverse_check_accounting(entry_types=("deposit",))
