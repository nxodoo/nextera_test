from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.osv import expression


SEVERITY_PRIORITY_MAP = {
    "low": "1",
    "medium": "2",
    "high": "3",
}
PRIORITY_SEVERITY_MAP = {value: key for key, value in SEVERITY_PRIORITY_MAP.items()}
ASSIGNMENT_ACTIVITY_SUMMARY = "Ticket Assignment"
SOLVED_STAGE_KEYWORDS = (
    "solve",
    "solved",
    "done",
    "resolve",
    "resolved",
    "close",
    "closed",
    "تم الحل",
    "محلول",
    "مغلق",
)
NEW_STAGE_KEYWORDS = ("new", "draft", "open", "جديد", "مسودة", "مفتوح")
IN_PROGRESS_STAGE_KEYWORDS = (
    "progress",
    "in progress",
    "working",
    "work in progress",
    "ongoing",
    "pending",
    "processing",
    "قيد التنفيذ",
    "قيد المعالجة",
    "جاري العمل",
)
BLOCKED_STAGE_KEYWORDS = (
    "cancel",
    "cancelled",
    "canceled",
    "reject",
    "rejected",
    "blocked",
    "block",
    "ملغي",
    "إلغاء",
    "رفض",
    "مرفوض",
    "متعطل",
    "محظور",
)
ASSIGNMENT_ACTIVITY_CACHE_FIELDS = [
    "activity_ids",
    "activity_state",
    "activity_user_id",
    "activity_type_id",
    "activity_type_icon",
    "activity_date_deadline",
    "my_activity_date_deadline",
    "activity_summary",
    "activity_exception_decoration",
    "activity_exception_icon",
]


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    ticket_type_id = fields.Many2one(
        "nx.helpdesk.ticket.type",
        string="Ticket Type",
        tracking=True,
        domain=[("active", "=", True)],
    )
    severity = fields.Selection(
        selection=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
        ],
        string="Severity",
        compute="_compute_severity",
        store=True,
        readonly=True,
        tracking=True,
    )
    secondary_user_id = fields.Many2one(
        "res.users",
        string="Secondary Assigned Person",
        domain=[("share", "=", False)],
        tracking=True,
    )
    ticket_created_at = fields.Date(
        string="Created At",
        default=fields.Date.context_today,
        readonly=False,
    )
    ticket_solved_at = fields.Date(
        string="Solved At",
    )
    partner_commercial_id = fields.Many2one(
        "res.partner",
        related="partner_id.commercial_partner_id",
        readonly=True,
    )
    warranty_contract_id = fields.Many2one(
        "warranty.contract",
        string="Warranty Contract",
        domain="[('partner_id', '=', partner_commercial_id), '|', ('helpdesk_team_ids', '=', False), ('helpdesk_team_ids', 'in', team_id)]",
    )
    consume_warranty = fields.Boolean(
        string="Consume Warranty",
        default=True,
    )
    warranty_used_minutes = fields.Integer(
        string="Warranty Used Minutes",
        default=0,
        help="Consumed warranty minutes for this ticket.",
    )
    warranty_ticket_consumed = fields.Boolean(
        string="Warranty Ticket Consumed",
        default=False,
        copy=False,
        readonly=True,
        help="Marked when this ticket consumes one ticket from ticket-based warranties.",
    )
    warranty_remaining_tickets = fields.Integer(
        related="warranty_contract_id.remaining_tickets",
        string="Remaining Tickets",
        readonly=True,
    )
    total_timesheet_hours = fields.Float(
        string="Total Time Spent (Hours)",
        compute="_compute_total_timesheet_hours",
        readonly=True,
    )
    show_total_timesheet_hours = fields.Boolean(
        string="Show Total Timesheet Hours",
        compute="_compute_show_total_timesheet_hours",
        readonly=True,
    )
    portal_expected_resolution_time = fields.Char(
        string="Expected Closing Time",
        compute="_compute_portal_expected_resolution_time",
        readonly=True,
    )
    expected_close_date = fields.Datetime(
        string="Expected Closing Time",
        compute="_compute_expected_close_date",
        readonly=True,
    )
    final_feedback = fields.Text(
        string="Final Feedback",
        tracking=True,
        copy=False,
    )
    portal_attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Attachments",
        compute="_compute_portal_attachment_ids",
        readonly=True,
    )
    portal_attachment_preview_html = fields.Html(
        string="Attachment Preview",
        compute="_compute_portal_attachment_preview_html",
        sanitize=False,
        readonly=True,
    )
    can_edit_stage = fields.Boolean(
        string="Can Edit Stage",
        compute="_compute_can_edit_stage",
        readonly=True,
    )
    is_new_stage = fields.Boolean(
        string="Is New Stage",
        compute="_compute_stage_category_flags",
        readonly=True,
    )
    is_in_progress_stage = fields.Boolean(
        string="Is In Progress Stage",
        compute="_compute_stage_category_flags",
        readonly=True,
    )
    is_solved_stage = fields.Boolean(
        string="Is Solved Stage",
        compute="_compute_stage_category_flags",
        readonly=True,
    )
    is_cancelled_stage = fields.Boolean(
        string="Is Cancelled Stage",
        compute="_compute_stage_category_flags",
        readonly=True,
    )

    @api.depends("user_id")
    def _compute_can_edit_stage(self):
        """Allow stage changes only for the primary assignee or helpdesk managers."""
        current_user = self.env.user
        is_manager = current_user.has_group("helpdesk.group_helpdesk_manager")
        for ticket in self:
            ticket.can_edit_stage = bool(
                is_manager or (ticket.user_id and ticket.user_id == current_user)
            )

    @api.depends("stage_id.name")
    def _compute_stage_category_flags(self):
        """Classify the current stage for compact header button visibility."""
        for ticket in self:
            ticket.is_new_stage = ticket._is_new_stage(ticket.stage_id)
            ticket.is_in_progress_stage = ticket._is_in_progress_stage(ticket.stage_id)
            ticket.is_solved_stage = ticket._is_solved_stage(ticket.stage_id)
            ticket.is_cancelled_stage = ticket._is_blocked_stage(ticket.stage_id)

    def _get_stage_name_tokens(self, stage):
        """Return a normalized stage name for keyword matching."""
        return (stage.name or "").strip().lower() if stage else ""

    def _is_new_stage(self, stage):
        """Return whether the stage represents a new/open state."""
        return any(keyword in self._get_stage_name_tokens(stage) for keyword in NEW_STAGE_KEYWORDS)

    def _is_in_progress_stage(self, stage):
        """Return whether the stage represents a work-in-progress state."""
        return any(keyword in self._get_stage_name_tokens(stage) for keyword in IN_PROGRESS_STAGE_KEYWORDS)

    def _is_blocked_stage(self, stage):
        """Return whether the stage represents a cancelled or blocked outcome."""
        return any(keyword in self._get_stage_name_tokens(stage) for keyword in BLOCKED_STAGE_KEYWORDS)

    def _is_solved_stage(self, stage):
        """Return whether the stage represents a solved or closed outcome."""
        return any(keyword in self._get_stage_name_tokens(stage) for keyword in SOLVED_STAGE_KEYWORDS)

    def _is_feedback_stage(self, stage):
        """Return whether the stage transition should collect final feedback."""
        return bool(stage) and (self._is_solved_stage(stage) or self._is_blocked_stage(stage))

    def _get_team_feedback_stage(self, outcome):
        """Return the matching team stage for the requested closing outcome."""
        self.ensure_one()
        matcher = self._is_solved_stage if outcome == "solved" else self._is_blocked_stage
        team_stages = self.team_id.stage_ids.sorted("sequence") or self.env["helpdesk.stage"]
        return team_stages.filtered(matcher)[:1]

    def _get_team_stage_by_keywords(self, keywords):
        """Return the first team stage matching one of the provided keywords."""
        self.ensure_one()
        team_stages = self.team_id.stage_ids.sorted("sequence") or self.env["helpdesk.stage"]
        return team_stages.filtered(
            lambda stage: any(keyword in self._get_stage_name_tokens(stage) for keyword in keywords)
        )[:1]

    def _set_stage_by_keywords(self, keywords, error_message):
        """Move the ticket to the first matching team stage."""
        self.ensure_one()
        target_stage = self._get_team_stage_by_keywords(keywords)
        if not target_stage:
            raise ValidationError(error_message)
        self.write({"stage_id": target_stage.id})
        return True

    def _open_close_feedback_wizard(self, outcome):
        """Open the final feedback wizard for solved or cancelled transitions."""
        self.ensure_one()
        target_stage = self._get_team_feedback_stage(outcome)
        if not target_stage:
            raise ValidationError("No matching closing stage is configured for this helpdesk team.")
        wizard = self.env["helpdesk.ticket.close.feedback.wizard"].create({
            "ticket_id": self.id,
            "target_stage_id": target_stage.id,
            "final_feedback": self.final_feedback or "",
        })
        return {
            "type": "ir.actions.act_window",
            "name": "Final Feedback",
            "res_model": "helpdesk.ticket.close.feedback.wizard",
            "view_mode": "form",
            "target": "new",
            "res_id": wizard.id,
        }

    def action_open_solved_feedback_wizard(self):
        """Open the solved feedback wizard."""
        return self._open_close_feedback_wizard("solved")

    def action_open_cancelled_feedback_wizard(self):
        """Open the cancelled feedback wizard."""
        return self._open_close_feedback_wizard("cancelled")

    def action_set_new_stage(self):
        """Move the ticket back to the configured new stage."""
        self.ensure_one()
        self._set_stage_by_keywords(
            NEW_STAGE_KEYWORDS,
            "No matching New stage is configured for this helpdesk team.",
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_set_in_progress_stage(self):
        """Move the ticket to the configured in-progress stage."""
        self.ensure_one()
        self._set_stage_by_keywords(
            IN_PROGRESS_STAGE_KEYWORDS,
            "No matching In Progress stage is configured for this helpdesk team.",
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def _compute_portal_attachment_ids(self):
        """Expose files linked directly to the ticket for easier backend review."""
        attachments = self.env["ir.attachment"].search([
            ("res_model", "=", "helpdesk.ticket"),
            ("res_id", "in", self.ids),
        ])
        attachments_by_ticket = {}
        for attachment in attachments:
            attachments_by_ticket.setdefault(attachment.res_id, self.env["ir.attachment"])
            attachments_by_ticket[attachment.res_id] |= attachment

        for ticket in self:
            ticket.portal_attachment_ids = attachments_by_ticket.get(ticket.id, self.env["ir.attachment"])

    def _compute_portal_attachment_preview_html(self):
        """Render ticket attachments as previews instead of a metadata table."""
        empty_html = Markup("<div class='text-muted'>No attachments.</div>")
        for ticket in self:
            if not ticket.portal_attachment_ids:
                ticket.portal_attachment_preview_html = empty_html
                continue

            fragments = []
            for attachment in ticket.portal_attachment_ids.sorted(key=lambda att: (att.create_date or "", att.id)):
                download_url = f"/odoo/web/content/{attachment.id}?download=true"
                preview_url = f"/odoo/web/image/ir.attachment/{attachment.id}/datas"
                name = escape(attachment.name or "Attachment")
                mimetype = attachment.mimetype or ""
                if mimetype.startswith("image/"):
                    fragments.append(
                        f"""
                        <div class="nx-ticket-attachment-preview-card">
                            <a href="{preview_url}" target="_blank" class="nx-ticket-attachment-preview-link">
                                <img src="{preview_url}" alt="{name}" class="nx-ticket-attachment-preview-image"/>
                            </a>
                            <div class="nx-ticket-attachment-preview-name">{name}</div>
                        </div>
                        """
                    )
                else:
                    fragments.append(
                        f"""
                        <a href="{download_url}" target="_blank" class="nx-ticket-attachment-file-card">
                            <span class="fa fa-paperclip"/>
                            <span>{name}</span>
                        </a>
                        """
                    )
            ticket.portal_attachment_preview_html = Markup(
                "<div class='nx-ticket-attachment-preview-grid'>%s</div>" % "".join(fragments)
            )

    @api.onchange("partner_id", "team_id")
    def _onchange_partner_id_set_latest_warranty_contract(self):
        domain = [("id", "=", False)]
        for ticket in self:
            if not ticket.partner_id:
                ticket.warranty_contract_id = False
                continue

            domain = [
                ("partner_id", "=", ticket.partner_id.commercial_partner_id.id),
                ("state", "in", ["draft", "active", "need_to_be_extended"]),
                "|",
                ("helpdesk_team_ids", "=", False),
                ("helpdesk_team_ids", "in", ticket.team_id.id if ticket.team_id else False),
            ]
            ticket.warranty_contract_id = ticket._get_latest_active_warranty_contract()
        return {
            "domain": {
                "warranty_contract_id": domain,
            }
        }

    @api.onchange("warranty_contract_id")
    def _onchange_warranty_contract_id_set_team(self):
        for ticket in self.filtered("warranty_contract_id"):
            contract_teams = ticket.warranty_contract_id.helpdesk_team_ids
            if len(contract_teams) == 1:
                ticket.team_id = contract_teams
            elif contract_teams and ticket.team_id not in contract_teams:
                ticket.team_id = contract_teams[:1]

    @api.constrains("warranty_contract_id", "team_id")
    def _check_warranty_contract_team_match(self):
        for ticket in self.filtered("warranty_contract_id"):
            contract_teams = ticket.warranty_contract_id.helpdesk_team_ids
            if contract_teams and ticket.team_id and ticket.team_id not in contract_teams:
                raise ValidationError(
                    "The selected warranty contract is linked to another helpdesk team."
                )

    @api.depends("ticket_type_id", "ticket_type_id.priority", "priority")
    def _compute_severity(self):
        for ticket in self:
            ticket.severity = ticket._get_ticket_severity()

    def _get_ticket_severity(self):
        self.ensure_one()
        if ticket_type := self.ticket_type_id:
            if ticket_type.priority:
                return PRIORITY_SEVERITY_MAP.get(ticket_type.priority)
            return ticket_type.severity
        if self.priority:
            return PRIORITY_SEVERITY_MAP.get(self.priority)
        return False

    @api.onchange("ticket_type_id")
    def _onchange_ticket_type_id_set_priority(self):
        for ticket in self.filtered("ticket_type_id"):
            ticket.priority = ticket.ticket_type_id.priority or SEVERITY_PRIORITY_MAP.get(
                ticket.ticket_type_id.severity,
                ticket.priority,
            )

    @api.model
    def _kanban_state_from_stage_id(self, stage_id):
        """Return the matching kanban state for a helpdesk stage."""
        stage = self.env["helpdesk.stage"].browse(stage_id)
        if stage and stage.exists():
            stage_name = (stage.name or "").strip().lower()
            if any(keyword in stage_name for keyword in BLOCKED_STAGE_KEYWORDS):
                return "blocked"
            return "done" if stage.fold else "normal"
        return False

    @api.depends("timesheet_ids.unit_amount")
    def _compute_total_timesheet_hours(self):
        for ticket in self:
            ticket.total_timesheet_hours = sum(ticket.timesheet_ids.mapped("unit_amount"))

    @api.depends("stage_id.name", "close_date")
    def _compute_show_total_timesheet_hours(self):
        for ticket in self:
            ticket.show_total_timesheet_hours = ticket._is_total_time_visible_on_ticket()

    def _is_total_time_visible_on_ticket(self):
        self.ensure_one()
        stage_name = (self.stage_id.name or "").strip().lower()
        is_cancelled = any(keyword in stage_name for keyword in BLOCKED_STAGE_KEYWORDS)
        is_solved = any(keyword in stage_name for keyword in SOLVED_STAGE_KEYWORDS)
        return is_cancelled or is_solved

    @api.depends("expected_close_date")
    def _compute_portal_expected_resolution_time(self):
        for ticket in self:
            ticket.portal_expected_resolution_time = ticket._format_expected_close_date(
                ticket.expected_close_date
            )

    @api.depends(
        "create_date",
        "ticket_type_id",
        "ticket_type_id.sla_policy_id",
        "ticket_type_id.sla_policy_id.time",
        "priority",
        "team_id",
        "stage_id",
        "partner_id",
        "sla_ids",
        "sla_ids.time",
    )
    def _compute_expected_close_date(self):
        for ticket in self:
            ticket.expected_close_date = ticket._get_expected_close_date()

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals = []
        for vals in vals_list:
            new_vals = dict(vals)
            if new_vals.get("ticket_type_id"):
                ticket_type = self.env["nx.helpdesk.ticket.type"].browse(new_vals["ticket_type_id"])
                if ticket_type.exists():
                    new_vals["priority"] = ticket_type.priority or SEVERITY_PRIORITY_MAP.get(
                        ticket_type.severity,
                        new_vals.get("priority", "0"),
                    )
            if not new_vals.get("ticket_created_at"):
                new_vals["ticket_created_at"] = fields.Date.context_today(self)
            if new_vals.get("partner_id") and not new_vals.get("warranty_contract_id"):
                contract = self._get_latest_active_warranty_contract_for_partner(
                    new_vals["partner_id"],
                    team_id=new_vals.get("team_id"),
                )
                if contract:
                    new_vals["warranty_contract_id"] = contract.id
                    if len(contract.helpdesk_team_ids) == 1 and not new_vals.get("team_id"):
                        new_vals["team_id"] = contract.helpdesk_team_ids.id
            if new_vals.get("stage_id") and not new_vals.get("kanban_state"):
                mapped_state = self._kanban_state_from_stage_id(new_vals["stage_id"])
                if mapped_state:
                    new_vals["kanban_state"] = mapped_state
            prepared_vals.append(new_vals)

        tickets = super().create(prepared_vals)
        # Keep kanban state aligned with folded stages when stage was defaulted by Odoo.
        to_sync = tickets.filtered(lambda t: t.stage_id and t.kanban_state != ("done" if t.stage_id.fold else "normal"))
        for ticket in to_sync:
            ticket.kanban_state = "done" if ticket.stage_id.fold else "normal"
        tickets._sync_assignment_activities()

        if not self.env.context.get("skip_warranty_sync"):
            tickets._sync_warranty_minutes_on_close()
        return tickets

    def write(self, vals):
        new_vals = dict(vals)
        if "stage_id" in new_vals and not self.env.user.has_group("helpdesk.group_helpdesk_manager"):
            unauthorized_tickets = self.filtered(lambda ticket: ticket.user_id != self.env.user)
            if unauthorized_tickets:
                raise AccessError(
                    "Only the primary assignee or a helpdesk administrator can change the ticket stage."
                )
        if new_vals.get("stage_id") and not self.env.context.get("skip_close_feedback_wizard"):
            target_stage = self.env["helpdesk.stage"].browse(new_vals["stage_id"])
            if self._is_feedback_stage(target_stage) and not new_vals.get("final_feedback"):
                raise ValidationError(
                    "Use the Solved or Cancelled feedback action to close this ticket with final feedback."
                )
        if new_vals.get("ticket_type_id"):
            ticket_type = self.env["nx.helpdesk.ticket.type"].browse(new_vals["ticket_type_id"])
            if ticket_type.exists():
                new_vals["priority"] = ticket_type.priority or SEVERITY_PRIORITY_MAP.get(
                    ticket_type.severity,
                    new_vals.get("priority", "0"),
                )
        if new_vals.get("stage_id") and not new_vals.get("kanban_state"):
            mapped_state = self._kanban_state_from_stage_id(new_vals["stage_id"])
            if mapped_state:
                new_vals["kanban_state"] = mapped_state
        if "ticket_solved_at" not in new_vals:
            today = fields.Date.context_today(self)
            for ticket in self:
                target_stage = ticket.stage_id
                if new_vals.get("stage_id"):
                    target_stage = self.env["helpdesk.stage"].browse(new_vals["stage_id"])
                will_be_closed = bool(new_vals.get("close_date")) or bool(target_stage and target_stage.fold)
                if will_be_closed and not ticket.ticket_solved_at:
                    new_vals["ticket_solved_at"] = today
                    break
                if not will_be_closed and ticket.ticket_solved_at:
                    new_vals["ticket_solved_at"] = False
                    break
        res = super().write(new_vals)
        if any(key in new_vals for key in ("user_id", "secondary_user_id", "stage_id", "close_date", "ticket_type_id")):
            self._sync_assignment_activities()
        if self.env.context.get("skip_warranty_sync"):
            return res
        if any(key in new_vals for key in ("close_date", "stage_id", "warranty_contract_id", "warranty_used_minutes", "consume_warranty")):
            self._sync_warranty_minutes_on_close()
        return res

    def _will_write_close_ticket(self, vals):
        """Return whether the incoming values will move any ticket to a closed state."""
        for ticket in self:
            target_stage = ticket.stage_id
            if vals.get("stage_id"):
                target_stage = self.env["helpdesk.stage"].browse(vals["stage_id"])
            will_be_closed = bool(vals.get("close_date")) or bool(target_stage and target_stage.fold)
            if will_be_closed:
                return True
        return False

    @api.model
    def _sla_find_false_domain(self):
        return [("partner_ids", "=", False)]

    def _sla_find_extra_domain(self):
        self.ensure_one()
        return [
            "|",
            ("partner_ids", "parent_of", self.partner_id.ids),
            ("partner_ids", "child_of", self.partner_id.ids),
        ]

    def _get_matching_sla_policies(self):
        """Return SLA policies matching the ticket without relying on tags.

        Expected resolution in this module should follow the configured
        priority/severity flow. Tag-based SLA filtering makes the result depend
        on internal categorization rather than the selected ticket type.
        """
        self.ensure_one()
        if not (self.team_id and self.team_id.use_sla and self.stage_id):
            return self.env["helpdesk.sla"]

        partner_domain = self._sla_find_false_domain()
        if self.partner_id:
            partner_domain = expression.OR([
                self._sla_find_extra_domain(),
                self._sla_find_false_domain(),
            ])
        domain = expression.AND([
            [
                ("team_id", "=", self.team_id.id),
                ("priority", "=", self.priority or "0"),
                ("stage_id.sequence", ">=", self.stage_id.sequence),
                ("active", "=", True),
            ],
            partner_domain,
        ])
        return self.env["helpdesk.sla"].search(domain, order="time asc")

    def _get_expected_resolution_hours(self):
        """Return the SLA duration in working hours used for the expected close date.

        The ticket should primarily follow the selected issue type SLA when one
        is configured. If no direct ticket-type policy applies, fall back to the
        shortest matching team SLA.
        """
        self.ensure_one()
        preferred_policy = self.ticket_type_id.sla_policy_id
        if preferred_policy and preferred_policy.active:
            if not self.team_id or preferred_policy.team_id == self.team_id:
                return preferred_policy.time or 0.0

        matched_slas = self._get_applicable_sla_policies()
        return matched_slas[:1].time if matched_slas else 0.0

    @api.model
    def _format_expected_close_date(self, expected_close_date):
        """Format the computed expected closing datetime for portal display."""
        if not expected_close_date:
            return False
        localized_datetime = fields.Datetime.context_timestamp(self, expected_close_date)
        return localized_datetime.strftime("%m/%d/%Y %H:%M")

    def _get_expected_close_date(self):
        """Return the target closing datetime derived from the ticket SLA."""
        self.ensure_one()
        create_dt = self.create_date or fields.Datetime.now()
        expected_hours = self._get_expected_resolution_hours()
        if not expected_hours:
            return False
        return fields.Datetime.add(create_dt, hours=expected_hours)

    def _get_applicable_sla_policies(self):
        """Return the SLA policies that should drive this ticket's deadline."""
        self.ensure_one()
        preferred_policy = self.ticket_type_id.sla_policy_id
        matched_slas = self.sla_ids.sorted("time") or self._get_matching_sla_policies()
        if (
            preferred_policy
            and preferred_policy.active
            and preferred_policy.team_id == self.team_id
            and preferred_policy.priority == (self.priority or "0")
        ):
            return (preferred_policy | matched_slas).sorted("time")
        return matched_slas.sorted("time")

    def _get_assignment_activity_type(self):
        """Return the shared activity type used for ticket assignment reminders."""
        return self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)

    def _prepare_assignment_activity_note(self, role):
        """Build the activity note shown to assigned users."""
        self.ensure_one()
        role_label = "primary assignee" if role == "primary" else "secondary assignee"
        return (
            f"You have been assigned to helpdesk ticket #{self.ticket_ref or self.id} "
            f"as the {role_label}."
        )

    def _invalidate_assignment_activity_cache(self):
        """Refresh cached activity fields after assignment activities change."""
        self.invalidate_recordset(ASSIGNMENT_ACTIVITY_CACHE_FIELDS)

    def _sync_assignment_activities(self):
        """Keep assignment activities aligned with the ticket assignees."""
        activity_type = self._get_assignment_activity_type()
        if not activity_type:
            return

        activity_model = self.env["mail.activity"].sudo()
        existing_activities = activity_model.search([
            ("res_model", "=", self._name),
            ("res_id", "in", self.ids),
            ("activity_type_id", "=", activity_type.id),
            ("summary", "=", ASSIGNMENT_ACTIVITY_SUMMARY),
        ])

        activities_changed = False
        for ticket in self:
            ticket_activities = existing_activities.filtered(lambda activity: activity.res_id == ticket.id)
            desired_users = {}
            if not ticket._is_total_time_visible_on_ticket():
                if ticket.user_id:
                    desired_users[ticket.user_id.id] = "primary"
                if ticket.secondary_user_id and ticket.secondary_user_id != ticket.user_id:
                    desired_users[ticket.secondary_user_id.id] = "secondary"

            assignment_deadline = (ticket.expected_close_date or fields.Datetime.now()).date()
            missing_users = [
                user_id for user_id in desired_users
                if user_id not in ticket_activities.mapped("user_id").ids
            ]
            obsolete_activities = ticket_activities.filtered(
                lambda activity: activity.user_id.id not in desired_users
            )

            # Reuse obsolete assignment activities during reassignment so the form
            # does not try to read an activity that was just deleted in the same request.
            for activity, user_id in zip(obsolete_activities, missing_users):
                activity.write({
                    "user_id": user_id,
                    "summary": ASSIGNMENT_ACTIVITY_SUMMARY,
                    "note": ticket._prepare_assignment_activity_note(desired_users[user_id]),
                    "date_deadline": assignment_deadline,
                })
                activities_changed = True

            reused_count = min(len(obsolete_activities), len(missing_users))
            remaining_missing_users = missing_users[reused_count:]
            remaining_obsolete_activities = obsolete_activities[reused_count:]

            for user_id in remaining_missing_users:
                ticket.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=user_id,
                    summary=ASSIGNMENT_ACTIVITY_SUMMARY,
                    note=ticket._prepare_assignment_activity_note(desired_users[user_id]),
                    date_deadline=assignment_deadline,
                )
                activities_changed = True

            if remaining_obsolete_activities:
                remaining_obsolete_activities.unlink()
                activities_changed = True

        if activities_changed:
            # web_save reads the ticket again in the same request; without invalidation,
            # Odoo may still hold deleted activity ids in cache and try to read them.
            self._invalidate_assignment_activity_cache()

    def _get_latest_active_warranty_contract(self):
        self.ensure_one()
        if not self.partner_id:
            return self.env["warranty.contract"]
        return self._get_latest_active_warranty_contract_for_partner(
            self.partner_id.id,
            team_id=self.team_id.id,
        )

    @api.model
    def _get_latest_active_warranty_contract_for_partner(self, partner_id, team_id=False):
        """Return the best active contract for the partner and optional team."""
        partner = self.env["res.partner"].browse(partner_id)
        commercial_partner = partner.commercial_partner_id
        WarrantyContract = self.env["warranty.contract"]
        base_domain = [
            ("partner_id", "=", commercial_partner.id),
            ("state", "=", "active"),
        ]
        order = "start_date desc, create_date desc, id desc"
        if team_id:
            contract = WarrantyContract.search(
                base_domain + [("helpdesk_team_ids", "in", team_id)],
                order=order,
                limit=1,
            )
            if contract:
                return contract
            return WarrantyContract.search(
                base_domain + [("helpdesk_team_ids", "=", False)],
                order=order,
                limit=1,
            )
        return WarrantyContract.search(base_domain, order=order, limit=1)

    def _consume_warranty_minutes(self, minutes):
        if minutes <= 0:
            return
        for ticket in self.filtered(lambda t: t.warranty_contract_id and t.consume_warranty):
            ticket.warranty_contract_id._ensure_can_consume(minutes=minutes)
            ticket.with_context(skip_warranty_sync=True).write({
                "warranty_used_minutes": (ticket.warranty_used_minutes or 0) + minutes,
            })
            ticket.warranty_contract_id._apply_lifecycle_state()

    def _sync_warranty_minutes_on_close(self):
        for ticket in self.filtered(lambda t: t.warranty_contract_id and t.consume_warranty):
            is_closed = bool(ticket.close_date or ticket.stage_id.fold)
            if not is_closed:
                continue

            ticket_delta = 1 if (
                ticket.warranty_contract_id.warranty_template_id.duration_type == "tickets_based"
                and not ticket.warranty_ticket_consumed
            ) else 0
            minutes_delta = 0
            if not ticket.warranty_used_minutes and "worked_hours" in ticket._fields:
                minutes_delta = int(round((ticket.worked_hours or 0.0) * 60))

            if minutes_delta > 0 or ticket_delta > 0:
                ticket.warranty_contract_id._ensure_can_consume(
                    minutes=minutes_delta,
                    ticket_delta=ticket_delta,
                )
                vals = {}
                if minutes_delta > 0:
                    vals["warranty_used_minutes"] = minutes_delta
                if ticket_delta > 0:
                    vals["warranty_ticket_consumed"] = True
                ticket.with_context(skip_warranty_sync=True).write(vals)
            ticket.warranty_contract_id._apply_lifecycle_state()

    def _recompute_warranty_used_minutes_from_timesheets(self):
        AnalyticLine = self.env["account.analytic.line"].sudo()
        if "helpdesk_ticket_id" not in AnalyticLine._fields:
            return

        totals_by_ticket = {}
        if self.ids:
            lines = AnalyticLine.search([
                ("helpdesk_ticket_id", "in", self.ids),
            ])
            for line in lines:
                if not line.helpdesk_ticket_id:
                    continue
                totals_by_ticket.setdefault(line.helpdesk_ticket_id.id, 0)
                totals_by_ticket[line.helpdesk_ticket_id.id] += int(round(max(line.unit_amount or 0.0, 0.0) * 60))

        for ticket in self:
            target_minutes = 0
            if ticket.consume_warranty and ticket.warranty_contract_id:
                target_minutes = totals_by_ticket.get(ticket.id, 0)

            current_minutes = ticket.warranty_used_minutes or 0
            if target_minutes > current_minutes and ticket.warranty_contract_id and ticket.consume_warranty:
                ticket.warranty_contract_id._ensure_can_consume(minutes=target_minutes - current_minutes)

            if current_minutes != target_minutes:
                ticket.with_context(skip_warranty_sync=True).write({
                    "warranty_used_minutes": target_minutes,
                })

            if ticket.warranty_contract_id:
                ticket.warranty_contract_id._apply_lifecycle_state()
