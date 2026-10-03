from psycopg2.errors import LockNotAvailable

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

from .check_check import CTX_STATE_TRANSITION

GROUP_USER = "sa_check_management.group_check_user"
GROUP_MANAGER = "sa_check_management.group_check_manager"
GROUP_APPROVER = "sa_check_management.group_check_approver"

# action -> (allowed source states, target state), per direction.
# Banking, exception, endorsement and guarantee actions are added in later phases.
TRANSITIONS = {
    "incoming": {
        "receive": (frozenset({"draft"}), "received"),
        "return": (frozenset({"received", "bounced"}), "returned"),
        "cancel": (frozenset({"draft", "received"}), "cancelled"),
        "reset_draft": (frozenset({"received"}), "draft"),
    },
    "outgoing": {
        "submit": (frozenset({"draft"}), "pending_approval"),
        "approve": (frozenset({"pending_approval"}), "approved"),
        "reject": (frozenset({"pending_approval"}), "draft"),
        "issue": (frozenset({"draft", "approved"}), "issued"),
        "deliver": (frozenset({"issued"}), "delivered"),
        "cancel": (frozenset({"draft", "pending_approval", "approved", "issued"}), "cancelled"),
        "reset_draft": (frozenset({"approved"}), "draft"),
    },
}

ACTION_GROUPS = {
    "receive": GROUP_USER,
    "return": GROUP_USER,
    "submit": GROUP_USER,
    "issue": GROUP_USER,
    "deliver": GROUP_USER,
    "cancel": GROUP_USER,
    "approve": GROUP_APPROVER,
    "reject": GROUP_APPROVER,
    "reset_draft": GROUP_MANAGER,
}

ACTION_EVENTS = {
    "receive": "received",
    "return": "returned",
    "submit": "approval",
    "approve": "approval",
    "reject": "approval",
    "issue": "issued",
    "deliver": "delivered",
    "cancel": "cancelled",
    "reset_draft": "state_change",
}

WIZARD_TITLES = {
    "cancel": "Cancel Check",
    "return": "Return Check to Partner",
    "deliver": "Deliver Check to Beneficiary",
    "reject": "Reject Check Approval",
    "withdraw": "Withdraw Check from Bank",
    "stop": "Stop Payment",
    "lose": "Lost Check",
    "void_stale": "Void Stale Check",
    "unendorse": "Check Returned by Endorsee",
    "release": "Release Guarantee Check",
    "invoke": "Invoke Guarantee Check",
    "reset_draft": "Reset Check to Draft",
}


class CheckCheck(models.Model):
    _inherit = "check.check"

    approval_required = fields.Boolean(related="company_id.check_outgoing_approval_required")

    returned_date = fields.Date(readonly=True, copy=False)
    return_reason = fields.Text(readonly=True, copy=False)
    return_recipient = fields.Char(string="Returned To", readonly=True, copy=False)
    delivered_date = fields.Date(readonly=True, copy=False)
    delivery_recipient = fields.Char(string="Delivered To", readonly=True, copy=False)
    cancel_reason = fields.Text(readonly=True, copy=False)
    submitted_by_id = fields.Many2one("res.users", string="Submitted By", readonly=True, copy=False)
    approved_by_id = fields.Many2one("res.users", string="Approved By", readonly=True, copy=False)
    approved_date = fields.Date(readonly=True, copy=False)
    rejection_reason = fields.Text(readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_receive(self):
        self._transition("receive")
        return True

    def action_submit(self):
        self._transition("submit", extra_vals={"submitted_by_id": self.env.user.id})
        return True

    def action_approve(self):
        self._transition("approve", extra_vals={
            "approved_by_id": self.env.user.id,
            "approved_date": fields.Date.context_today(self),
        })
        return True

    def action_issue(self):
        self._transition("issue")
        return True

    def action_reset_to_draft(self):
        self._transition("reset_draft")
        return True

    def action_open_cancel_wizard(self):
        return self._open_action_wizard("cancel")

    def action_open_return_wizard(self):
        return self._open_action_wizard("return")

    def action_open_deliver_wizard(self):
        return self._open_action_wizard("deliver")

    def action_open_reset_wizard(self):
        return self._open_action_wizard("reset_draft")

    def action_open_reject_wizard(self):
        return self._open_action_wizard("reject")

    def _open_action_wizard(self, action):
        return {
            "type": "ir.actions.act_window",
            "name": _(WIZARD_TITLES[action]),
            "res_model": "check.action.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_check_action": action,
                "default_check_ids": [(6, 0, self.ids)],
            },
        }

    # ------------------------------------------------------------------
    # Wizard-backed actions
    # ------------------------------------------------------------------
    def _apply_cancel(self, reason, action_date):
        self._transition("cancel", note=reason, extra_vals={
            "cancel_reason": reason,
            "cancelled_date": action_date,
        })

    def _apply_return(self, reason, recipient, action_date):
        note = _("%(reason)s\nReturned to: %(recipient)s", reason=reason, recipient=recipient)
        self._transition("return", note=note, extra_vals={
            "return_reason": reason,
            "return_recipient": recipient,
            "returned_date": action_date,
        })

    def _apply_deliver(self, recipient, action_date, note=False):
        event_note = _("Delivered to: %(recipient)s", recipient=recipient)
        if note:
            event_note = f"{event_note}\n{note}"
        self._transition("deliver", note=event_note, extra_vals={
            "delivery_recipient": recipient,
            "delivered_date": action_date,
        })

    def _apply_reject(self, reason):
        self._transition("reject", note=reason, extra_vals={
            "rejection_reason": reason,
            "approved_by_id": False,
            "approved_date": False,
        })

    # ------------------------------------------------------------------
    # Transition engine
    # ------------------------------------------------------------------
    def _transition(self, action, note=False, extra_vals=None):
        if not self:
            return
        self._lock_for_transition()
        self._check_action_access(action)
        for check in self:
            target = check._target_state(action)
            check._validate_transition(action)
            check._write_transition(action, target, note, extra_vals)

    def _write_transition(self, action, target, note, extra_vals):
        self.ensure_one()
        old_state = self.state
        vals = {**self._action_default_vals(action), **(extra_vals or {}), "state": target}
        self.with_context(**{CTX_STATE_TRANSITION: True}).write(vals)
        self._log_event(ACTION_EVENTS[action], old_state=old_state, new_state=target, note=note)
        self._after_transition(action)

    def _after_transition(self, action):
        """Hook for side effects (accounting, custody...) that must succeed with the transition."""
        self.ensure_one()

    def _lock_for_transition(self):
        try:
            with self.env.cr.savepoint():
                self._sql_lock_rows()
        except LockNotAvailable:
            raise UserError(_(
                "Another user is processing one of these checks right now. Try again in a moment."
            )) from None
        self.invalidate_recordset(["state"])

    def _sql_lock_rows(self):
        """Row-lock the checks; fails at once (NOWAIT) if another transaction holds them."""
        self.env.cr.execute("SELECT id FROM check_check WHERE id IN %s FOR UPDATE NOWAIT", [tuple(self.ids)])

    def _check_action_access(self, action):
        if self.env.su:
            return
        if not self.env.user.has_group(ACTION_GROUPS[action]):
            raise AccessError(_("You are not allowed to perform this check action."))
        if action == "cancel":
            self._check_cancel_access()

    def _check_cancel_access(self):
        if self.filtered(lambda check: check.state != "draft") and not self.env.user.has_group(GROUP_MANAGER):
            raise AccessError(_("Only a Check Manager can cancel a check after it leaves Draft."))

    def _target_state(self, action):
        self.ensure_one()
        transitions = TRANSITIONS[self.check_type]
        if action not in transitions:
            raise UserError(_(
                "This action is not available for %(direction)s checks.",
                direction=self.check_type,
            ))
        sources, target = transitions[action]
        if self.state not in sources:
            raise UserError(_(
                "Check %(check)s is %(state)s; this action is not allowed from that state.",
                check=self.display_name, state=self._state_label(),
            ))
        return target

    def _state_label(self):
        self.ensure_one()
        return dict(self._fields["state"]._description_selection(self.env)).get(self.state, self.state)

    def _action_default_vals(self, action):
        today = fields.Date.context_today(self)
        defaults = {
            "receive": {"received_date": today},
            "issue": {"issued_date": today},
            "cancel": {"cancelled_date": today},
            "return": {"returned_date": today},
            "deliver": {"delivered_date": today},
            "reset_draft": {
                "received_date": False,
                "issued_date": False,
                "submitted_by_id": False,
                "approved_by_id": False,
                "approved_date": False,
            },
        }
        return defaults.get(action, {})

    # ------------------------------------------------------------------
    # Per-action validations (one rule each)
    # ------------------------------------------------------------------
    def _validate_transition(self, action):
        validator = {
            "receive": self._validate_receive,
            "submit": self._validate_submit,
            "approve": self._validate_approve,
            "issue": self._validate_issue,
            "reset_draft": self._validate_reset_draft,
        }.get(action)
        if validator:
            validator()

    def _validate_receive(self):
        self.ensure_one()
        if not self.bank_id:
            raise UserError(_("Check %(check)s: set the bank before receiving it.", check=self.display_name))

    def _validate_submit(self):
        self.ensure_one()
        if not self.approval_required:
            raise UserError(_("Outgoing checks of %(company)s do not need approval; issue it directly.",
                              company=self.company_id.name))

    def _validate_approve(self):
        self.ensure_one()
        if self.env.su or not self.company_id.check_approval_segregation:
            return
        if self.env.user in (self.create_uid | self.submitted_by_id):
            raise UserError(_("You cannot approve a check you created or submitted."))

    def _validate_issue(self):
        self.ensure_one()
        if not self.journal_id:
            raise UserError(_("Check %(check)s: set the bank journal before issuing it.", check=self.display_name))
        journal_currency = self.journal_id.currency_id
        if journal_currency and journal_currency != self.currency_id:
            raise UserError(_(
                "Check %(check)s is in %(check_currency)s but journal %(journal)s only accepts %(journal_currency)s.",
                check=self.display_name, check_currency=self.currency_id.name,
                journal=self.journal_id.display_name, journal_currency=journal_currency.name,
            ))
        if self.state == "draft" and self.approval_required:
            raise UserError(_("Check %(check)s needs approval before it can be issued.", check=self.display_name))

    def _validate_reset_draft(self):
        self.ensure_one()
        if self._has_accounting_entries():
            raise UserError(_(
                "Check %(check)s has accounting entries; reverse them before resetting to Draft.",
                check=self.display_name,
            ))

    def _has_accounting_entries(self):
        """Hook: overridden once accounting is implemented."""
        self.ensure_one()
        return False
