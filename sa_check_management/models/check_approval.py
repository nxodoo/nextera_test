from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .check_lifecycle import ACTION_GROUPS, GROUP_USER

# Stage eligibility is enforced per approval line; the transitions only need check access.
ACTION_GROUPS.update({"approve": GROUP_USER, "reject": GROUP_USER})

FALLBACK_APPROVER_GROUP = "sa_check_management.group_check_approver"


class CheckApprovalRule(models.Model):
    _name = "check.approval.rule"
    _description = "Check Approval Stage"
    _order = "company_id, sequence, min_amount, id"
    _check_company_auto = True

    name = fields.Char(string="Stage", required=True, translate=True)
    sequence = fields.Integer(default=10, help="Stages are approved in this order.")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    check_type = fields.Selection(
        selection=[("outgoing", "Outgoing")], string="Direction", required=True, default="outgoing",
    )
    purpose = fields.Selection(
        selection=[
            ("payment", "Payment"),
            ("guarantee", "Guarantee"),
            ("security", "Security"),
            ("advance", "Advance"),
        ],
        help="Leave empty to apply to every purpose.",
    )
    min_amount = fields.Monetary(
        string="From Amount", currency_field="currency_id",
        help="The stage applies to checks of at least this amount (company currency).",
    )
    max_amount = fields.Monetary(
        string="Up To Amount", currency_field="currency_id",
        help="Leave zero for no upper limit.",
    )
    group_id = fields.Many2one("res.groups", string="Approvers", required=True)
    active = fields.Boolean(default=True)

    @api.constrains("min_amount", "max_amount")
    def _check_amounts(self):
        for rule in self:
            if rule.min_amount < 0 or (rule.max_amount and rule.max_amount <= rule.min_amount):
                raise ValidationError(_("Stage %s: the amount range is not valid.", rule.name))

    def _applies_to(self, check):
        self.ensure_one()
        amount = check.company_amount
        return (
            self.company_id == check.company_id
            and self.check_type == check.check_type
            and (not self.purpose or self.purpose == check.purpose)
            and check.company_currency_id.compare_amounts(amount, self.min_amount) >= 0
            and (not self.max_amount or check.company_currency_id.compare_amounts(amount, self.max_amount) < 0)
        )


class CheckApprovalLine(models.Model):
    _name = "check.approval.line"
    _description = "Check Approval"
    _order = "check_id, sequence, id"

    check_id = fields.Many2one("check.check", required=True, index=True, ondelete="cascade", readonly=True)
    rule_id = fields.Many2one("check.approval.rule", string="Stage Rule", readonly=True, ondelete="set null")
    name = fields.Char(string="Stage", required=True, readonly=True)
    sequence = fields.Integer(readonly=True)
    round = fields.Integer(string="Submission", default=1, readonly=True,
                           help="Each submission for approval starts a new round.")
    group_id = fields.Many2one("res.groups", string="Approvers", required=True, readonly=True)
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        required=True, default="pending", readonly=True,
    )
    approver_id = fields.Many2one("res.users", string="Decided By", readonly=True)
    decision_date = fields.Datetime(readonly=True)
    comment = fields.Text(readonly=True)
    company_id = fields.Many2one(related="check_id.company_id", store=True, index=True)


class CheckCheck(models.Model):
    _inherit = "check.check"

    approval_line_ids = fields.One2many("check.approval.line", "check_id", string="Approvals", readonly=True)
    current_approval_line_id = fields.Many2one(
        "check.approval.line", compute="_compute_current_approval_line_id",
    )
    approval_stage = fields.Char(string="Waiting For", compute="_compute_current_approval_line_id")

    @api.depends("approval_line_ids.state", "approval_line_ids.sequence", "approval_line_ids.name")
    def _compute_current_approval_line_id(self):
        for check in self:
            line = check._pending_approval_lines()[:1]
            check.current_approval_line_id = line
            check.approval_stage = line.name

    def _pending_approval_lines(self):
        self.ensure_one()
        return self.sudo().approval_line_ids.filtered(lambda line: line.state == "pending").sorted(
            lambda line: (line.sequence, line.id)
        )

    # ------------------------------------------------------------------
    # Approve / reject one stage at a time
    # ------------------------------------------------------------------
    def action_approve(self):
        for check in self:
            check._approve_current_stage()
        return True

    def _approve_current_stage(self):
        self.ensure_one()
        self._lock_for_transition()
        if self.state != "pending_approval":
            raise UserError(_("Check %(check)s is not waiting for approval.", check=self.display_name))
        line = self.current_approval_line_id
        self._check_stage_approver(line)
        line.sudo().write({"state": "approved", "approver_id": self.env.user.id, "decision_date": fields.Datetime.now()})
        note = _("%(stage)s approved by %(user)s", stage=line.name, user=self.env.user.name)
        if self._pending_approval_lines():
            self._log_event("approval", note=note, source=line)
            return
        self._transition("approve", note=note, extra_vals={
            "approved_by_id": self.env.user.id,
            "approved_date": fields.Date.context_today(self),
        })

    def _apply_reject(self, reason):
        for check in self:
            line = check.current_approval_line_id
            check._check_stage_approver(line, rejecting=True)
            line.sudo().write({
                "state": "rejected", "approver_id": self.env.user.id,
                "decision_date": fields.Datetime.now(), "comment": reason,
            })
            check._cancel_pending_approval_lines()
        return super()._apply_reject(reason)

    def _check_stage_approver(self, line, rejecting=False):
        self.ensure_one()
        if not line:
            raise UserError(_("Check %(check)s has no pending approval stage.", check=self.display_name))
        if self.env.su:
            return
        user = self.env.user
        if line.group_id not in user.groups_id:
            raise AccessError(_("You are not an approver for stage %(stage)s.", stage=line.name))
        if rejecting or not self.company_id.check_approval_segregation:
            return
        if user in (self.create_uid | self.submitted_by_id):
            raise UserError(_("You cannot approve a check you created or submitted."))
        if user in self._current_round_lines().filtered(lambda l: l.state == "approved").approver_id:
            raise UserError(_("You already approved an earlier stage of this check."))

    def _current_round_lines(self):
        self.ensure_one()
        lines = self.sudo().approval_line_ids
        current = max(lines.mapped("round"), default=0)
        return lines.filtered(lambda line: line.round == current)

    # ------------------------------------------------------------------
    # Lifecycle integration
    # ------------------------------------------------------------------
    def _after_transition(self, action):
        super()._after_transition(action)
        if action == "submit":
            self._create_approval_lines()
        elif action in ("cancel", "reset_draft"):
            self._cancel_pending_approval_lines()

    def _create_approval_lines(self):
        self.ensure_one()
        rules = self.env["check.approval.rule"].sudo().search([("company_id", "=", self.company_id.id)])
        stages = rules.filtered(lambda rule: rule._applies_to(self))
        next_round = max(self.sudo().approval_line_ids.mapped("round"), default=0) + 1
        if stages:
            vals_list = [{
                "check_id": self.id, "rule_id": rule.id, "name": rule.name,
                "sequence": rule.sequence, "group_id": rule.group_id.id, "round": next_round,
            } for rule in stages]
        else:
            vals_list = [{
                "check_id": self.id, "name": _("Finance Approval"), "sequence": 10,
                "group_id": self.env.ref(FALLBACK_APPROVER_GROUP).id, "round": next_round,
            }]
        self.env["check.approval.line"].sudo().create(vals_list)

    def _cancel_pending_approval_lines(self):
        self.ensure_one()
        self._pending_approval_lines().sudo().write({"state": "cancelled"})
