from odoo import _, api, fields, models
from odoo.exceptions import UserError

REASON_ACTIONS = frozenset({
    "cancel", "return", "reject", "withdraw", "stop", "lose", "void_stale", "unendorse", "release", "invoke",
    "reset_draft",
})
RECIPIENT_ACTIONS = frozenset({"return", "deliver", "release"})
DATED_ACTIONS = frozenset({"cancel", "return", "deliver", "stop", "lose", "release"})
REFERENCE_ACTIONS = frozenset({"stop"})


class CheckActionWizard(models.TransientModel):
    _name = "check.action.wizard"
    _description = "Check Action"

    check_action = fields.Selection(
        selection=[
            ("cancel", "Cancel"),
            ("return", "Return to Partner"),
            ("deliver", "Deliver to Beneficiary"),
            ("reject", "Reject Approval"),
            ("withdraw", "Withdraw from Bank"),
            ("stop", "Stop Payment"),
            ("lose", "Lost Check"),
            ("void_stale", "Void Stale Check"),
            ("unendorse", "Returned by Endorsee"),
            ("release", "Release Guarantee"),
            ("invoke", "Invoke Guarantee"),
            ("reset_draft", "Reset to Draft"),
        ],
        string="Action", required=True, readonly=True,
    )
    check_ids = fields.Many2many("check.check", string="Checks", required=True, readonly=True)
    action_date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    reason = fields.Text()
    recipient = fields.Char(help="Name of the person who physically received the check.")
    reference = fields.Char(string="Bank Reference")
    note = fields.Text()
    attachment = fields.Binary(string="Evidence")
    attachment_name = fields.Char()
    reason_required = fields.Boolean(compute="_compute_requirements")
    recipient_required = fields.Boolean(compute="_compute_requirements")
    date_required = fields.Boolean(compute="_compute_requirements")
    reference_required = fields.Boolean(compute="_compute_requirements")

    @api.depends("check_action")
    def _compute_requirements(self):
        for wizard in self:
            wizard.reason_required = wizard.check_action in REASON_ACTIONS
            wizard.recipient_required = wizard.check_action in RECIPIENT_ACTIONS
            wizard.date_required = wizard.check_action in DATED_ACTIONS
            wizard.reference_required = wizard.check_action in REFERENCE_ACTIONS

    def action_confirm(self):
        self.ensure_one()
        self._validate_inputs()
        guarded = self.check_ids.filtered(lambda check: check._sensitive_rule(self.check_action))
        requests = self._create_requests(guarded)
        if self.check_ids - guarded:
            getattr(self.with_context(sa_check_wizard_checks=(self.check_ids - guarded).ids),
                    f"_confirm_{self.check_action}")()
        self._attach_evidence()
        if requests:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "warning",
                    "message": _("Sent for approval: %s", ", ".join(requests.mapped("name"))),
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return {"type": "ir.actions.act_window_close"}

    def _create_requests(self, checks):
        requests = self.env["check.action.request"]
        for check in checks:
            requests |= check._request_approval(
                self.check_action, (self.reason or "").strip(),
                recipient=(self.recipient or "").strip(), action_date=self.action_date,
            )
        return requests

    def _target_checks(self):
        ids = self.env.context.get("sa_check_wizard_checks")
        return self.check_ids.browse(ids) if ids is not None else self.check_ids

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_inputs(self):
        self._validate_reason()
        self._validate_recipient()
        self._validate_reference()
        self._validate_date()

    def _validate_reason(self):
        if self.reason_required and not (self.reason or "").strip():
            raise UserError(_("Enter a reason for this action."))

    def _validate_recipient(self):
        if self.recipient_required and not (self.recipient or "").strip():
            raise UserError(_("Enter the name of the person who received the check."))

    def _validate_reference(self):
        if self.reference_required and not (self.reference or "").strip():
            raise UserError(_("Enter the bank confirmation reference."))

    def _validate_date(self):
        if self.date_required and self.action_date > fields.Date.context_today(self):
            raise UserError(_("The action date cannot be in the future."))

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def _confirm_cancel(self):
        self._target_checks()._apply_cancel(self.reason.strip(), self.action_date)

    def _confirm_return(self):
        self._target_checks()._apply_return(self.reason.strip(), self.recipient.strip(), self.action_date)

    def _confirm_deliver(self):
        self._target_checks()._apply_deliver(self.recipient.strip(), self.action_date, self.note)

    def _confirm_reject(self):
        self._target_checks()._apply_reject(self.reason.strip())

    def _confirm_withdraw(self):
        self._target_checks()._apply_withdraw(self.reason.strip())

    def _confirm_stop(self):
        self._target_checks()._apply_stop(self.reason.strip(), self.action_date, self.reference.strip())

    def _confirm_lose(self):
        self._target_checks()._apply_lose(self.reason.strip(), self.action_date)

    def _confirm_void_stale(self):
        self._target_checks()._apply_void_stale(self.reason.strip())

    def _confirm_unendorse(self):
        self._target_checks()._apply_unendorse(self.reason.strip())

    def _confirm_release(self):
        self._target_checks()._apply_release(self.reason.strip(), self.recipient.strip(), self.action_date)

    def _confirm_invoke(self):
        self._target_checks()._apply_invoke(self.reason.strip())

    def _confirm_reset_draft(self):
        for check in self._target_checks():
            check._transition("reset_draft", note=self.reason.strip())

    def _attach_evidence(self):
        if not self.attachment:
            return
        self.env["ir.attachment"].create([{
            "name": self.attachment_name or _("Evidence"),
            "datas": self.attachment,
            "res_model": "check.check",
            "res_id": check.id,
        } for check in self.check_ids])
