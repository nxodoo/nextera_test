from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

GROUP_MANAGER = "sa_check_management.group_check_manager"
GROUP_TREASURY = "sa_check_management.group_check_treasury"

SENSITIVE_ACTIONS = [
    ("cancel", "Cancel (after Draft)"),
    ("reset_draft", "Reset to Draft"),
    ("withdraw", "Withdraw from Bank"),
    ("lose", "Lost Check"),
    ("void_stale", "Void Stale Check"),
    ("release", "Release Guarantee"),
    ("invoke", "Invoke Guarantee"),
    ("unendorse", "Returned by Endorsee"),
]
SENSITIVE_KEYS = frozenset(key for key, _label in SENSITIVE_ACTIONS)


class CheckActionRule(models.Model):
    _name = "check.action.rule"
    _description = "Sensitive Check Action Rule"
    _order = "company_id, action"

    _sql_constraints = [
        ("action_unique", "UNIQUE(company_id, action)", "Each sensitive action has one rule per company."),
    ]

    action = fields.Selection(SENSITIVE_ACTIONS, required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    approver_group_id = fields.Many2one(
        "res.groups", string="Approvers", required=True,
        default=lambda self: self.env.ref(GROUP_MANAGER, raise_if_not_found=False),
    )
    active = fields.Boolean(default=True)


class CheckActionRequest(models.Model):
    _name = "check.action.request"
    _description = "Check Action Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default="/")
    check_id = fields.Many2one("check.check", required=True, readonly=True, index=True, ondelete="cascade")
    partner_id = fields.Many2one(related="check_id.partner_id")
    amount = fields.Monetary(related="check_id.amount")
    currency_id = fields.Many2one(related="check_id.currency_id")
    check_state = fields.Selection(related="check_id.state", string="Check Status")
    action = fields.Selection(SENSITIVE_ACTIONS, required=True, readonly=True)
    reason = fields.Text(required=True, readonly=True)
    recipient = fields.Char(readonly=True)
    action_date = fields.Date(readonly=True)
    state = fields.Selection(
        selection=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")],
        required=True, default="pending", readonly=True, tracking=True,
    )
    requested_by_id = fields.Many2one("res.users", required=True, readonly=True, default=lambda self: self.env.user)
    approver_group_id = fields.Many2one("res.groups", string="Approvers", required=True, readonly=True)
    decided_by_id = fields.Many2one("res.users", readonly=True)
    decision_date = fields.Datetime(readonly=True)
    decision_note = fields.Text()
    company_id = fields.Many2one(related="check_id.company_id", store=True, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("sa.check.action.request") or "/"
        requests = super().create(vals_list)
        requests._notify_approvers()
        return requests

    @api.constrains("check_id", "action", "state")
    def _check_single_pending(self):
        for request in self.filtered(lambda r: r.state == "pending"):
            if self.search_count([("id", "!=", request.id), ("check_id", "=", request.check_id.id),
                                  ("action", "=", request.action), ("state", "=", "pending")], limit=1):
                raise ValidationError(_("This action is already waiting for approval on check %s.",
                                        request.check_id.display_name))

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------
    def action_approve(self):
        for request in self:
            request._check_can_decide()
            request._execute()
            request._decide("approved")
        return True

    def action_reject(self):
        for request in self:
            request._check_can_decide()
            if not (request.decision_note or "").strip():
                raise UserError(_("Explain why the request is rejected."))
            request._decide("rejected")
            request.check_id._log_event("approval", note=_("%(request)s rejected: %(note)s",
                                                             request=request.name, note=request.decision_note))
        return True

    def action_cancel(self):
        for request in self:
            if request.state != "pending":
                raise UserError(_("Request %s is already decided.", request.name))
            if request.requested_by_id != self.env.user and not self.env.user.has_group(GROUP_MANAGER):
                raise AccessError(_("Only the requester or a Check Manager can withdraw this request."))
            request._decide("cancelled")
        return True

    def _check_can_decide(self):
        self.ensure_one()
        if self.state != "pending":
            raise UserError(_("Request %s is already decided.", self.name))
        if self.env.su:
            return
        user = self.env.user
        if self.approver_group_id not in user.groups_id:
            raise AccessError(_("You are not an approver for this request."))
        if user == self.requested_by_id:
            raise UserError(_("You cannot approve or reject your own request."))

    def _decide(self, state):
        self.ensure_one()
        self.sudo().write({"state": state, "decided_by_id": self.env.user.id, "decision_date": fields.Datetime.now()})
        self.activity_ids.sudo().action_feedback(feedback=_("Request %s", state))

    def _execute(self):
        """Run the approved action as the system: the approval is the authorisation."""
        self.ensure_one()
        check = self.check_id.sudo().with_context(sa_check_request_note=_(
            "%(request)s requested by %(requester)s, approved by %(approver)s",
            request=self.name, requester=self.requested_by_id.name, approver=self.env.user.name,
        ))
        reason = f"{self.reason}\n({self.name})"
        date = self.action_date or fields.Date.context_today(self)
        dispatch = {
            "cancel": lambda: check._apply_cancel(reason, date),
            "reset_draft": lambda: check._transition("reset_draft", note=reason),
            "withdraw": lambda: check._apply_withdraw(reason),
            "lose": lambda: check._apply_lose(reason, date),
            "void_stale": lambda: check._apply_void_stale(reason),
            "release": lambda: check._apply_release(reason, self.recipient or "", date),
            "invoke": lambda: check._apply_invoke(reason),
            "unendorse": lambda: check._apply_unendorse(reason),
        }
        dispatch[self.action]()

    def _notify_approvers(self):
        for request in self:
            users = request.approver_group_id.users.filtered(
                lambda u: u.active and not u.share and u != request.requested_by_id
                and request.company_id in u.company_ids
            )
            for user in users:
                request.sudo().activity_schedule(
                    "mail.mail_activity_data_todo", user_id=user.id,
                    summary=_("Approve: %(action)s on %(check)s",
                              action=dict(SENSITIVE_ACTIONS)[request.action], check=request.check_id.display_name),
                )


class CheckCheck(models.Model):
    _inherit = "check.check"

    action_request_ids = fields.One2many("check.action.request", "check_id", string="Approval Requests", readonly=True)
    pending_request_count = fields.Integer(compute="_compute_pending_request_count")

    @api.depends("action_request_ids.state")
    def _compute_pending_request_count(self):
        for check in self:
            check.pending_request_count = len(check.action_request_ids.filtered(lambda r: r.state == "pending"))

    def _sensitive_rule(self, action):
        """Active approval rule for ``action`` on this check, if any."""
        self.ensure_one()
        if action not in SENSITIVE_KEYS or (action == "cancel" and self.state == "draft"):
            return self.env["check.action.rule"]
        return self.env["check.action.rule"].sudo().search([
            ("company_id", "=", self.company_id.id), ("action", "=", action),
        ], limit=1)

    def _request_approval(self, action, reason, recipient=False, action_date=False):
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group(GROUP_TREASURY):
            raise AccessError(_("Only Treasury Officers can request sensitive check actions."))
        self._target_state(action)  # fail now if the action is not possible from this state
        rule = self._sensitive_rule(action)
        return self.env["check.action.request"].sudo().create({
            "check_id": self.id, "action": action, "reason": reason, "recipient": recipient or False,
            "action_date": action_date or False, "approver_group_id": rule.approver_group_id.id,
            "requested_by_id": self.env.user.id,
        })

    def _check_action_access(self, action):
        super()._check_action_access(action)
        if self.env.su:
            return
        guarded = self.filtered(lambda check: check._sensitive_rule(action))
        if guarded:
            raise UserError(_(
                "This action needs approval on %(checks)s; submit it from the action dialog to create a request.",
                checks=", ".join(guarded.mapped("display_name")),
            ))

    def _log_event(self, event_type, old_state=False, new_state=False, note=False, source=False):
        request_note = self.env.context.get("sa_check_request_note")
        if request_note and event_type not in ("accounting",):
            note = "\n".join(filter(None, [note, request_note]))
        return super()._log_event(event_type, old_state=old_state, new_state=new_state, note=note, source=source)

    def action_view_requests(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("sa_check_management.action_check_action_request")
        action["domain"] = [("check_id", "=", self.id)]
        return action
