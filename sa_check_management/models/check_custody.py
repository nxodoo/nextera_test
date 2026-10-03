from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .check_check import CTX_ALLOW_LOCKED_EDIT

GROUP_TREASURY = "sa_check_management.group_check_treasury"
GROUP_MANAGER = "sa_check_management.group_check_manager"

# States in which the paper check is physically with us and can move between holders.
CUSTODY_STATES = ("received", "bounced", "legal")
# Actions after which the paper leaves our custody.
CUSTODY_EXIT_ACTIONS = frozenset({
    "collect", "discount_collect", "endorse", "return", "release", "replace", "settle", "lose", "cancel",
})
# Actions that hand the check to the bank of the deposit.
BANK_ACTIONS = frozenset({"deposit", "redeposit"})


class CheckHandover(models.Model):
    _name = "check.handover"
    _description = "Check Handover"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default="/")
    check_ids = fields.Many2many(
        "check.check", "check_handover_check_rel", "handover_id", "check_id", string="Checks",
        required=True, check_company=True,
        domain="[('check_type', '=', 'incoming'), ('state', 'in', ('received', 'bounced', 'legal'))]",
    )
    from_location_id = fields.Many2one("check.location", string="From", required=True, check_company=True, tracking=True)
    to_location_id = fields.Many2one("check.location", string="To", required=True, check_company=True, tracking=True)
    receiver_id = fields.Many2one(related="to_location_id.user_id", string="Receiver")
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("pending", "Awaiting Receiver"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        required=True, default="draft", readonly=True, copy=False, tracking=True,
    )
    sender_id = fields.Many2one("res.users", string="Handed Over By", default=lambda self: self.env.user, readonly=True)
    accepted_by_id = fields.Many2one("res.users", string="Accepted By", readonly=True, copy=False)
    accepted_date = fields.Datetime(readonly=True, copy=False)
    rejection_reason = fields.Text()
    note = fields.Text()
    check_count = fields.Integer(compute="_compute_check_count")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.depends("check_ids")
    def _compute_check_count(self):
        for handover in self:
            handover.check_count = len(handover.check_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = self.env["ir.sequence"].sudo().with_company(company_id).next_by_code(
                    "sa.check.handover"
                ) or "/"
        return super().create(vals_list)

    def write(self, vals):
        if {"check_ids", "from_location_id", "to_location_id"}.intersection(vals) and self.filtered(
            lambda handover: handover.state != "draft"
        ):
            raise UserError(_("A handover can only be changed while it is in Draft."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda handover: handover.state != "draft"):
            raise UserError(_("Only draft handovers can be deleted."))

    @api.constrains("from_location_id", "to_location_id")
    def _check_locations_differ(self):
        for handover in self:
            if handover.from_location_id == handover.to_location_id:
                raise ValidationError(_("The check must move to a different holder."))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_send(self):
        for handover in self:
            handover._validate_sendable()
            if handover.company_id.check_handover_confirmation:
                handover._set_state("pending")
            else:
                handover._complete()
        return True

    def action_accept(self):
        for handover in self:
            if handover.state != "pending":
                raise UserError(_("Handover %s is not awaiting acceptance.", handover.name))
            handover._check_can_receive()
            handover._complete()
        return True

    def action_reject(self):
        for handover in self:
            if handover.state != "pending":
                raise UserError(_("Handover %s is not awaiting acceptance.", handover.name))
            handover._check_can_receive()
            if not (handover.rejection_reason or "").strip():
                raise UserError(_("Enter why the checks are not accepted."))
            handover._set_state("cancelled")
        return True

    def action_cancel(self):
        for handover in self:
            if handover.state not in ("draft", "pending"):
                raise UserError(_("Handover %s is already closed.", handover.name))
            handover._set_state("cancelled")
        return True

    # ------------------------------------------------------------------
    # Rules (one each)
    # ------------------------------------------------------------------
    def _validate_sendable(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Handover %s was already sent.", self.name))
        if not self.check_ids:
            raise UserError(_("Add at least one check to the handover."))
        not_in_custody = self.check_ids.filtered(lambda check: check.state not in CUSTODY_STATES)
        if not_in_custody:
            raise UserError(_("These checks are not in our custody: %s", ", ".join(not_in_custody.mapped("display_name"))))
        elsewhere = self.check_ids.filtered(lambda check: check.current_location_id != self.from_location_id)
        if elsewhere:
            raise UserError(_(
                "These checks are not held at %(location)s: %(checks)s",
                location=self.from_location_id.display_name, checks=", ".join(elsewhere.mapped("display_name")),
            ))
        busy = self.search_count([
            ("id", "!=", self.id), ("state", "=", "pending"), ("check_ids", "in", self.check_ids.ids),
        ], limit=1)
        if busy:
            raise UserError(_("Some of these checks are already in a handover awaiting acceptance."))

    def _check_can_receive(self):
        self.ensure_one()
        user = self.env.user
        if self.env.su or user.has_group(GROUP_MANAGER):
            return
        receiver = self.to_location_id.user_id
        allowed = user == receiver if receiver else user.has_group(GROUP_TREASURY)
        if not allowed:
            raise AccessError(_("Only %(holder)s can accept this handover.",
                                holder=receiver.name or _("a Treasury Officer")))

    def _complete(self):
        self.ensure_one()
        note = _("From %(origin)s to %(target)s (%(handover)s)",
                 origin=self.from_location_id.display_name, target=self.to_location_id.display_name, handover=self.name)
        self.check_ids._move_custody(self.to_location_id, note, source=self)
        super(CheckHandover, self).write({
            "state": "done",
            "accepted_by_id": self.env.user.id,
            "accepted_date": fields.Datetime.now(),
        })

    def _set_state(self, state):
        self.ensure_one()
        super(CheckHandover, self).write({"state": state})


class CheckLocation(models.Model):
    _inherit = "check.location"

    @api.model
    def _bank_location(self, journal):
        """Custody location representing a bank journal; created on first deposit."""
        location = self.sudo().search([
            ("location_type", "=", "bank"), ("journal_id", "=", journal.id),
        ], limit=1)
        if not location:
            location = self.sudo().create({
                "name": journal.sudo().name,
                "location_type": "bank",
                "journal_id": journal.id,
                "company_id": journal.sudo().company_id.id,
            })
        return location


class CheckCheck(models.Model):
    _inherit = "check.check"

    current_location_id = fields.Many2one(
        "check.location", string="Held At", check_company=True, tracking=True,
        default=lambda self: self.env.company.check_default_location_id,
        help="Where the paper check is now. After receipt it only changes through handovers and bank actions.",
    )
    current_holder_id = fields.Many2one(related="current_location_id.user_id", string="Holder")
    handover_ids = fields.Many2many(
        "check.handover", "check_handover_check_rel", "check_id", "handover_id", string="Handovers", readonly=True,
    )

    def _move_custody(self, location, note, source=False):
        for check in self:
            old = check.current_location_id
            check.with_context(**{CTX_ALLOW_LOCKED_EDIT: True}).sudo().write({"current_location_id": location.id})
            if old != location:
                check._log_event("handover", note=note, source=source)

    def _after_transition(self, action):
        super()._after_transition(action)
        if action in BANK_ACTIONS:
            journal = self.current_deposit_line_id.journal_id
            self._move_custody(self.env["check.location"]._bank_location(journal),
                               _("Deposited at %s", journal.sudo().display_name))
        elif action == "discount":
            journal = self.discount_journal_id
            self._move_custody(self.env["check.location"]._bank_location(journal),
                               _("Discounted at %s", journal.sudo().display_name))
        elif action in CUSTODY_EXIT_ACTIONS and self.check_type == "incoming" and self.current_location_id:
            self.with_context(**{CTX_ALLOW_LOCKED_EDIT: True}).sudo().write({"current_location_id": False})
