from dateutil.relativedelta import relativedelta
from math import ceil

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyContract(models.Model):
    _name = "warranty.contract"
    _description = "Warranty Contract"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False, index=True)

    partner_id = fields.Many2one("res.partner", required=True, tracking=True)
    helpdesk_team_ids = fields.Many2many(
        "helpdesk.team",
        string="Helpdesk Teams",
        tracking=True,
        help="Restrict this warranty contract to specific helpdesk teams.",
    )
    sale_order_id = fields.Many2one("sale.order", readonly=True, copy=False)
    sale_order_line_id = fields.Many2one("sale.order.line", readonly=True, copy=False)
    product_id = fields.Many2one("product.product", required=True, readonly=True)
    warranty_template_id = fields.Many2one("warranty.template", required=True, tracking=True)
    product_warranty_template_ids = fields.Many2many(
        related="product_id.warranty_template_ids",
        string="Warranty Templates",
        readonly=False,
    )
    duration_type = fields.Selection(
        related="warranty_template_id.duration_type",
        store=True,
        readonly=True,
    )
    warranty_certain_period = fields.Boolean(
        related="product_id.warranty_certain_period",
        readonly=True,
    )

    start_date = fields.Date(required=True, tracking=True, default=fields.Date.context_today)
    end_date = fields.Date(tracking=True)

    total_allocated_minutes = fields.Integer(
        compute="_compute_total_allocated_minutes",
        store=True,
    )
    used_minutes = fields.Integer(
        compute="_compute_usage",
        store=True,
    )
    remaining_minutes = fields.Integer(
        compute="_compute_remaining_minutes",
        store=True,
    )
    total_tickets = fields.Integer(
        compute="_compute_total_tickets",
        store=True,
    )
    used_tickets = fields.Integer(
        compute="_compute_usage",
        store=True,
    )
    remaining_tickets = fields.Integer(
        compute="_compute_remaining_tickets",
        store=True,
    )

    ticket_ids = fields.One2many("helpdesk.ticket", "warranty_contract_id", string="Helpdesk Tickets")
    ticket_count = fields.Integer(
        compute="_compute_ticket_count",
        string="Helpdesk Tickets",
    )
    history_message_ids = fields.Many2many(
        "mail.message",
        compute="_compute_history_message_ids",
        string="History",
        readonly=True,
    )
    history_tracking_value_ids = fields.Many2many(
        "mail.tracking.value",
        compute="_compute_history_tracking_value_ids",
        string="History Details",
        readonly=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("need_to_be_extended", "Need To Be Extended"),
            ("not_extended", "Not Extended"),
            ("expired", "Expired"),
        ],
        default="draft",
        tracking=True,
        index=True,
        copy=False,
    )

    @api.model
    def _count_service_days(self, start_date, end_date, service_days_per_week):
        if not start_date or not end_date or end_date <= start_date:
            return 0
        if service_days_per_week <= 0:
            return 0

        service_days_per_week = min(service_days_per_week, 7)
        days = 0
        cursor = start_date
        while cursor < end_date:
            if cursor.weekday() < service_days_per_week:
                days += 1
            cursor += relativedelta(days=1)
        return days

    @api.depends(
        "warranty_template_id.duration_type",
        "warranty_template_id.service_hours_per_day",
        "warranty_template_id.service_days_per_week",
        "warranty_template_id.duration_months",
        "start_date",
        "end_date",
    )
    def _compute_total_allocated_minutes(self):
        for rec in self:
            minutes = 0
            template = rec.warranty_template_id
            if not template or not rec.start_date:
                rec.total_allocated_minutes = 0
                continue

            if template.duration_type == "months":
                months = max(template.duration_months, 0)
                period_end = (rec.end_date or (rec.start_date + relativedelta(months=months))) if months else rec.end_date
                if period_end:
                    service_days = self._count_service_days(
                        rec.start_date,
                        period_end,
                        template.service_days_per_week,
                    )
                    minutes = int(round(service_days * max(template.service_hours_per_day, 0.0) * 60))

            elif template.duration_type == "fixed_dates" and rec.end_date:
                service_days = self._count_service_days(
                    rec.start_date,
                    rec.end_date,
                    template.service_days_per_week,
                )
                minutes = int(round(service_days * max(template.service_hours_per_day, 0.0) * 60))

            rec.total_allocated_minutes = max(minutes, 0)

    @api.depends(
        "warranty_template_id.duration_type",
        "warranty_template_id.total_tickets",
        "sale_order_line_id.product_uom_qty",
    )
    def _compute_total_tickets(self):
        for rec in self:
            template = rec.warranty_template_id
            if not template:
                rec.total_tickets = 0
                continue

            # For SO-linked ticket-based contracts, use sold quantity as ticket quota.
            if template.duration_type == "tickets_based" and rec.sale_order_line_id:
                qty = max(rec.sale_order_line_id.product_uom_qty or 0.0, 0.0)
                rec.total_tickets = int(ceil(qty))
            else:
                rec.total_tickets = max(template.total_tickets or 0, 0)

    @api.depends(
        "ticket_ids.warranty_used_minutes",
        "ticket_ids.warranty_ticket_consumed",
    )
    def _compute_usage(self):
        for rec in self:
            rec.used_minutes = int(sum(rec.ticket_ids.mapped("warranty_used_minutes")))
            rec.used_tickets = len(rec.ticket_ids.filtered("warranty_ticket_consumed"))

    @api.depends("total_allocated_minutes", "used_minutes")
    def _compute_remaining_minutes(self):
        for rec in self:
            rec.remaining_minutes = max((rec.total_allocated_minutes or 0) - (rec.used_minutes or 0), 0)

    @api.depends("total_tickets", "used_tickets")
    def _compute_remaining_tickets(self):
        for rec in self:
            rec.remaining_tickets = max((rec.total_tickets or 0) - (rec.used_tickets or 0), 0)

    @api.depends("ticket_ids")
    def _compute_ticket_count(self):
        for rec in self:
            rec.ticket_count = len(rec.ticket_ids)

    @api.depends("message_ids", "message_ids.tracking_value_ids")
    def _compute_history_message_ids(self):
        for rec in self:
            tracked_messages = rec.message_ids.filtered("tracking_value_ids")
            rec.history_message_ids = tracked_messages.sorted(
                key=lambda message: (message.date or fields.Datetime.now(), message.id),
                reverse=True,
            )

    @api.depends("history_message_ids", "history_message_ids.tracking_value_ids")
    def _compute_history_tracking_value_ids(self):
        for rec in self:
            tracking_values = rec.history_message_ids.mapped("tracking_value_ids")
            rec.history_tracking_value_ids = tracking_values.sorted(
                key=lambda tracking: (
                    tracking.mail_message_id.date or fields.Datetime.now(),
                    tracking.mail_message_id.id,
                    tracking.id,
                ),
                reverse=True,
            )

    @api.constrains("start_date", "end_date")
    def _check_dates(self):
        for rec in self:
            if rec.warranty_certain_period and (not rec.start_date or not rec.end_date):
                raise ValidationError(_("Start Date and End Date are required when Certain Period is enabled."))
            if rec.end_date and rec.start_date and rec.end_date < rec.start_date:
                raise ValidationError(_("End date cannot be before start date."))

    @api.constrains("used_minutes", "used_tickets")
    def _check_usage_non_negative(self):
        for rec in self:
            if rec.used_minutes < 0:
                raise ValidationError(_("Used minutes must be >= 0."))
            if rec.used_tickets < 0:
                raise ValidationError(_("Used tickets must be >= 0."))

    def _compute_next_state(self):
        today = fields.Date.context_today(self)
        next_states = {}
        for rec in self:
            next_states[rec.id] = rec._get_next_state_for_state(rec.state, today=today)
        return next_states

    def _get_next_state_for_state(self, current_state, today=None):
        """Return the lifecycle state the contract should move to from a given current state."""
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        next_state = current_state

        if self.end_date and self.end_date < today:
            next_state = "expired"
        elif current_state == "not_extended":
            next_state = "not_extended"
        elif self.total_allocated_minutes and self.remaining_minutes <= 0:
            next_state = "need_to_be_extended"
        elif self.total_tickets and self.used_tickets >= self.total_tickets:
            next_state = "need_to_be_extended"
        elif self.total_allocated_minutes and (self.used_minutes / self.total_allocated_minutes) > 0.90:
            next_state = "need_to_be_extended"
        elif self.total_tickets and (self.used_tickets / self.total_tickets) > 0.90:
            next_state = "need_to_be_extended"
        elif current_state == "draft" and self.start_date and self.start_date <= today:
            next_state = "active"
        elif current_state == "expired" and (not self.end_date or self.end_date >= today):
            next_state = "active"

        return next_state

    def _apply_lifecycle_state(self):
        state_map = self._compute_next_state()
        for rec in self:
            next_state = state_map.get(rec.id)
            if next_state and next_state != rec.state:
                rec.state = next_state

    @api.model
    def cron_update_warranty_states(self):
        contracts = self.search([
            ("state", "not in", ["expired"]),
        ])
        contracts._apply_lifecycle_state()

    def _ensure_can_consume(self, minutes=0, ticket_delta=0):
        self.ensure_one()
        self._apply_lifecycle_state()
        today = fields.Date.context_today(self)

        if self.state != "active":
            raise ValidationError(_("Warranty '%(name)s' is not active.") % {"name": self.display_name})
        if self.end_date and self.end_date < today:
            raise ValidationError(_("Warranty '%(name)s' is expired.") % {"name": self.display_name})
        if minutes > 0 and self.total_allocated_minutes and (self.used_minutes + minutes) > self.total_allocated_minutes:
            raise ValidationError(_("Cannot consume more minutes: warranty '%(name)s' has no remaining minutes.") % {"name": self.display_name})
        if ticket_delta > 0 and self.total_tickets and (self.used_tickets + ticket_delta) > self.total_tickets:
            raise ValidationError(_("Cannot consume more tickets: warranty '%(name)s' ticket quota is reached.") % {"name": self.display_name})

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("warranty.contract") or "New"
            vals.setdefault("state", "draft")
            template = self.env["warranty.template"].browse(vals.get("warranty_template_id"))
            start_date = vals.get("start_date")
            if template and template.duration_type == "months" and template.duration_months > 0 and start_date and not vals.get("end_date"):
                vals["end_date"] = fields.Date.to_date(start_date) + relativedelta(months=template.duration_months)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if any(key in vals for key in ("start_date", "end_date")) and not self.env.context.get("skip_sale_line_sync"):
            self._sync_sale_order_line_dates()
        if self.env.context.get("skip_auto_lifecycle_state"):
            return res
        if any(
            key in vals
            for key in (
                "start_date",
                "end_date",
                "warranty_template_id",
                "total_allocated_minutes",
                "used_minutes",
                "used_tickets",
                "total_tickets",
                "state",
            )
        ):
            self._apply_lifecycle_state()
        return res

    def _sync_sale_order_line_dates(self):
        """Mirror manual contract date changes back to the originating SO line."""
        for rec in self.filtered("sale_order_line_id"):
            rec.sale_order_line_id.with_context(skip_warranty_contract_sync=True).write({
                "warranty_start_date": rec.start_date,
                "warranty_end_date": rec.end_date,
            })

    def action_set_active(self):
        return self._action_set_state_with_override_check("active")

    def action_set_not_extended(self):
        return self._action_set_state_with_override_check("not_extended")

    def action_set_draft(self):
        return self._action_set_state_with_override_check("draft")

    def action_set_need_to_be_extended(self):
        return self._action_set_state_with_override_check("need_to_be_extended")

    def action_set_expired(self):
        return self._action_set_state_with_override_check("expired")

    def _action_set_state_with_override_check(self, target_state):
        self.ensure_one()
        computed_state = self._get_next_state_for_state(target_state)
        if computed_state != target_state:
            return {
                "type": "ir.actions.act_window",
                "name": "Confirm Manual State Override",
                "res_model": "warranty.contract.state.override.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {
                    "default_contract_id": self.id,
                    "default_target_state": target_state,
                    "default_computed_state": computed_state,
                },
            }
        self.with_context(skip_auto_lifecycle_state=True).write({"state": target_state})
        return True

    def action_view_helpdesk_tickets(self):
        self.ensure_one()
        action = self.env.ref("helpdesk.helpdesk_ticket_action_main_tree").read()[0]
        action["domain"] = [("warranty_contract_id", "=", self.id)]
        action["context"] = {
            "default_warranty_contract_id": self.id,
            "default_partner_id": self.partner_id.id,
        }
        if len(self.helpdesk_team_ids) == 1:
            action["context"]["default_team_id"] = self.helpdesk_team_ids.id
        return action
