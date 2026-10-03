from datetime import timedelta

from odoo import _, api, fields, models

TODO_ACTIVITY = "mail.mail_activity_data_todo"
COLLATERAL = ("guarantee", "security")
OPEN_INCOMING = ("received",)
OPEN_OUTGOING = ("issued", "delivered", "presented")


class CheckReminderLog(models.Model):
    """One row per reminder already sent, so a trigger never fires twice."""

    _name = "check.reminder.log"
    _description = "Check Reminder Log"

    _sql_constraints = [
        ("trigger_unique", "UNIQUE(res_model, res_id, key, user_id)", "This reminder was already sent."),
    ]

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    key = fields.Char(required=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")


class CheckCheck(models.Model):
    _inherit = "check.check"

    @api.model
    def _cron_check_reminders(self):
        for company in self.env["res.company"].search([]):
            self.with_company(company).sudo()._send_company_reminders(company)

    @api.model
    def _send_company_reminders(self, company):
        today = fields.Date.context_today(self)
        self._remind_due_checks(company, today)
        self._remind_matured_not_deposited(company, today)
        self._remind_matured_not_cleared(company, today)
        self._remind_bounced(company)
        self._remind_guarantees(company, today)
        self._remind_waiting_approvals(company, today)
        self._remind_waiting_deposits(company, today)
        self._remind_pending_handovers(company, today)
        self._escalate(company, today)

    # ------------------------------------------------------------------
    # Triggers (one rule each)
    # ------------------------------------------------------------------
    @api.model
    def _remind_due_checks(self, company, today):
        limit = today + timedelta(days=company.check_reminder_due_days)
        checks = self.search([
            ("company_id", "=", company.id),
            ("purpose", "not in", COLLATERAL),
            ("due_date", ">=", today), ("due_date", "<=", limit),
            "|", "&", ("check_type", "=", "incoming"), ("state", "in", OPEN_INCOMING),
            "&", ("check_type", "=", "outgoing"), ("state", "in", OPEN_OUTGOING),
        ])
        for check in checks:
            summary = _("Check due today") if check.due_date == today else _("Check due on %s", check.due_date)
            self._schedule_once(check, f"due:{check.due_date}", check.responsible_user_id, summary)

    @api.model
    def _remind_matured_not_deposited(self, company, today):
        checks = self.search([
            ("company_id", "=", company.id), ("check_type", "=", "incoming"),
            ("state", "=", "received"), ("purpose", "not in", COLLATERAL), ("due_date", "<", today),
        ])
        for check in checks:
            self._schedule_once(check, f"matured:{check.due_date}", check.responsible_user_id,
                                _("Matured check not deposited yet"))

    @api.model
    def _remind_matured_not_cleared(self, company, today):
        checks = self.search([
            ("company_id", "=", company.id), ("check_type", "=", "outgoing"),
            ("state", "in", OPEN_OUTGOING), ("purpose", "not in", COLLATERAL), ("due_date", "<", today),
        ])
        for check in checks:
            self._schedule_once(check, f"matured_out:{check.due_date}", check.responsible_user_id,
                                _("Outgoing check past due and not cleared yet"))

    @api.model
    def _remind_bounced(self, company):
        checks = self.search([("company_id", "=", company.id), ("state", "in", ("bounced", "rejected"))])
        for check in checks:
            self._schedule_once(check, f"bounced:{check.last_bounce_date}", check.responsible_user_id,
                                _("Follow up the bounced check"))

    @api.model
    def _remind_guarantees(self, company, today):
        limit = today + timedelta(days=company.check_reminder_guarantee_days)
        checks = self.search([
            ("company_id", "=", company.id), ("purpose", "in", COLLATERAL),
            ("state", "in", ("received", "issued", "delivered")),
            ("guarantee_expiry_date", "!=", False), ("guarantee_expiry_date", "<=", limit),
        ])
        for check in checks:
            if check.guarantee_expiry_date < today:
                summary = _("Guarantee expired on %s", check.guarantee_expiry_date)
            else:
                summary = _("Guarantee expires on %s", check.guarantee_expiry_date)
            self._schedule_once(check, f"guarantee:{check.guarantee_expiry_date}", check.responsible_user_id, summary)

    @api.model
    def _remind_waiting_approvals(self, company, today):
        limit = fields.Datetime.to_datetime(today - timedelta(days=company.check_reminder_approval_days))
        checks = self.search([("company_id", "=", company.id), ("state", "=", "pending_approval")])
        for check in checks:
            line = check.current_approval_line_id
            if not line or line.create_date > limit:
                continue
            for user in line.group_id.users.filtered(lambda u: not u.share and company in u.company_ids):
                self._schedule_once(check, f"approval:{line.id}", user,
                                    _("Approval waiting: %s", line.name))

    @api.model
    def _remind_waiting_deposits(self, company, today):
        limit = today - timedelta(days=company.check_reminder_deposit_days)
        deposits = self.env["check.deposit"].search([
            ("company_id", "=", company.id), ("state", "=", "confirmed"), ("date", "<=", limit),
        ])
        for deposit in deposits:
            self._schedule_once(deposit, f"deposit:{deposit.id}", deposit.create_uid,
                                _("Record the bank results of this deposit"))

    @api.model
    def _remind_pending_handovers(self, company, today):
        limit = fields.Datetime.to_datetime(today - timedelta(days=1))
        handovers = self.env["check.handover"].search([
            ("company_id", "=", company.id), ("state", "=", "pending"), ("date", "<=", limit),
        ])
        for handover in handovers:
            self._schedule_once(handover, f"handover:{handover.id}",
                                handover.to_location_id.user_id or handover.sender_id,
                                _("Accept or refuse the check handover"))

    # ------------------------------------------------------------------
    # Escalation to Check Managers
    # ------------------------------------------------------------------
    @api.model
    def _escalate(self, company, today):
        days = company.check_escalation_days
        if days <= 0:
            return
        managers = self.env.ref("sa_check_management.group_check_manager").users.filtered(
            lambda user: user.active and not user.share and company in user.company_ids
        )
        if not managers:
            return
        for record, key, summary in self._escalation_items(company, today, days):
            for manager in managers:
                self._schedule_once(record, key, manager, summary)

    @api.model
    def _escalation_items(self, company, today, days):
        late = today - timedelta(days=days)
        late_dt = fields.Datetime.to_datetime(late)
        items = []
        for check in self.search([("company_id", "=", company.id), ("state", "in", ("bounced", "rejected")),
                                  ("last_bounce_date", "<=", late)]):
            items.append((check, f"escalate:bounced:{check.last_bounce_date}", _("Escalation: bounced check still open")))
        for check in self.search([("company_id", "=", company.id), ("check_type", "=", "outgoing"),
                                  ("state", "in", OPEN_OUTGOING), ("purpose", "not in", COLLATERAL),
                                  ("due_date", "<=", late)]):
            items.append((check, f"escalate:matured_out:{check.due_date}",
                          _("Escalation: outgoing check past due, not cleared")))
        approval_limit = late_dt - timedelta(days=company.check_reminder_approval_days)
        for check in self.search([("company_id", "=", company.id), ("state", "=", "pending_approval")]):
            line = check.current_approval_line_id
            if line and line.create_date <= approval_limit:
                items.append((check, f"escalate:approval:{line.id}", _("Escalation: approval overdue (%s)", line.name)))
        for request in self.env["check.action.request"].search([
            ("company_id", "=", company.id), ("state", "=", "pending"), ("create_date", "<=", late_dt),
        ]):
            items.append((request, f"escalate:request:{request.id}", _("Escalation: approval request still pending")))
        deposit_limit = late - timedelta(days=company.check_reminder_deposit_days)
        for deposit in self.env["check.deposit"].search([
            ("company_id", "=", company.id), ("state", "=", "confirmed"), ("date", "<=", deposit_limit),
        ]):
            items.append((deposit, f"escalate:deposit:{deposit.id}", _("Escalation: deposit results missing")))
        for handover in self.env["check.handover"].search([
            ("company_id", "=", company.id), ("state", "=", "pending"), ("date", "<=", late_dt - timedelta(days=1)),
        ]):
            items.append((handover, f"escalate:handover:{handover.id}", _("Escalation: handover not accepted")))
        return items

    # ------------------------------------------------------------------
    # Deduplicated scheduling
    # ------------------------------------------------------------------
    @api.model
    def _schedule_once(self, record, key, user, summary):
        if not user or not user.active or user.share:
            return False
        Log = self.env["check.reminder.log"].sudo()
        if Log.search_count([
            ("res_model", "=", record._name), ("res_id", "=", record.id),
            ("key", "=", key), ("user_id", "=", user.id),
        ], limit=1):
            return False
        record.sudo().activity_schedule(
            TODO_ACTIVITY, date_deadline=fields.Date.context_today(self), summary=summary, user_id=user.id,
        )
        Log.create({"res_model": record._name, "res_id": record.id, "key": key, "user_id": user.id})
        return True
