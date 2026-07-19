from datetime import timedelta

from odoo import _, api, fields, models


class HrHolidayGreetingTemplate(models.Model):
    _name = "hr.holiday.greeting.template"
    _description = "Holiday Greeting Email Template"
    _order = "name"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    subject_template = fields.Char(
        string="Email Subject",
        required=True,
    )
    body_html = fields.Html(
        string="Email Body",
        required=True,
        sanitize=True,
    )
    send_timing = fields.Selection(
        selection=[
            ("same_day", "Same Day"),
            ("before", "Before Holiday"),
            ("after", "After Holiday"),
        ],
        string="Send Timing",
        required=True,
        default="same_day",
    )
    number_of_days = fields.Integer(
        string="Number of Days",
        default=0,
        help="Number of days before or after the holiday when the email should be sent.",
    )
    active = fields.Boolean(default=True)
    public_holiday_ids = fields.One2many(
        "resource.calendar.leaves",
        "holiday_greeting_template_id",
        string="Public Holidays",
    )
    greeting_log_ids = fields.One2many(
        "hr.holiday.greeting.log",
        "template_id",
        string="Greeting Logs",
    )

    _sql_constraints = [
        (
            "check_number_of_days_positive",
            "CHECK(number_of_days >= 0)",
            "The number of days must be zero or greater.",
        ),
    ]

    def _get_render_values(self, employee, holiday):
        """Build placeholder values used by greeting subject and body templates."""
        return {
            "employee_name": employee.name or "",
            "company_name": employee.company_id.name or holiday.company_id.name or "",
            "holiday_name": holiday.name or "",
        }

    def _render_text_template(self, template_text, values):
        """Render supported `${...}` placeholders in a template string."""
        rendered_text = template_text or ""
        for placeholder, value in values.items():
            rendered_text = rendered_text.replace("${%s}" % placeholder, value)
        return rendered_text

    def _get_target_holidays(self, today):
        """Return public holidays whose greeting must be processed on the given date."""
        self.ensure_one()
        if not self.active:
            return self.env["resource.calendar.leaves"]

        public_holidays = self.public_holiday_ids.filtered(lambda holiday: not holiday.resource_id)
        due_holidays = self.env["resource.calendar.leaves"]
        for holiday in public_holidays:
            holiday_date = fields.Datetime.to_datetime(holiday.date_from).date()
            if self.send_timing == "before":
                target_date = holiday_date - timedelta(days=self.number_of_days)
            elif self.send_timing == "after":
                target_date = holiday_date + timedelta(days=self.number_of_days)
            else:
                target_date = holiday_date
            if target_date == today:
                due_holidays |= holiday
        return due_holidays

    def _prepare_mail_values(self, employee, holiday):
        """Prepare a one-off mail.mail payload for a greeting email."""
        self.ensure_one()
        render_values = self._get_render_values(employee, holiday)
        email_from = (
            employee.company_id.email
            or holiday.company_id.email
            or self.env.user.email
            or self.env.company.email
        )
        return {
            "subject": self._render_text_template(self.subject_template, render_values),
            "body_html": self._render_text_template(self.body_html, render_values),
            "email_to": employee.work_email,
            "email_from": email_from,
            "auto_delete": True,
        }

    @api.model
    def _cron_send_holiday_greeting_emails(self):
        """Send due public holiday greetings once per employee and holiday."""
        companies = self.env["res.company"].search(
            [("holiday_greeting_scheduler_enabled", "=", True)]
        )
        if not companies:
            return

        today = fields.Date.context_today(self)
        templates = self.search(
            [
                ("active", "=", True),
                ("company_id", "in", companies.ids),
                ("public_holiday_ids", "!=", False),
            ]
        )
        log_model = self.env["hr.holiday.greeting.log"]
        mail_model = self.env["mail.mail"]

        for template in templates:
            due_holidays = template._get_target_holidays(today)
            for holiday in due_holidays:
                employees = self.env["hr.employee"].search(
                    [
                        ("active", "=", True),
                        ("company_id", "=", holiday.company_id.id),
                    ]
                )
                if not employees:
                    continue

                existing_logs = log_model.search(
                    [
                        ("holiday_id", "=", holiday.id),
                        ("employee_id", "in", employees.ids),
                    ]
                )
                processed_employee_ids = set(existing_logs.mapped("employee_id").ids)

                for employee in employees:
                    if employee.id in processed_employee_ids:
                        continue

                    if not employee.work_email:
                        log_model.create(
                            {
                                "template_id": template.id,
                                "holiday_id": holiday.id,
                                "employee_id": employee.id,
                                "state": "skipped",
                                "skip_reason": _("Skipped because the employee has no work email."),
                            }
                        )
                        continue

                    mail = mail_model.create(template._prepare_mail_values(employee, holiday))
                    mail.send()
                    log_model.create(
                        {
                            "template_id": template.id,
                            "holiday_id": holiday.id,
                            "employee_id": employee.id,
                            "mail_mail_id": mail.id,
                            "state": "sent",
                            "sent_datetime": fields.Datetime.now(),
                        }
                    )


class HrHolidayGreetingLog(models.Model):
    _name = "hr.holiday.greeting.log"
    _description = "Holiday Greeting Email Log"
    _order = "create_date desc"

    template_id = fields.Many2one(
        "hr.holiday.greeting.template",
        string="Greeting Template",
        required=True,
        ondelete="cascade",
    )
    holiday_id = fields.Many2one(
        "resource.calendar.leaves",
        string="Public Holiday",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="holiday_id.company_id",
        store=True,
        readonly=True,
    )
    mail_mail_id = fields.Many2one(
        "mail.mail",
        string="Email",
        readonly=True,
        ondelete="set null",
    )
    state = fields.Selection(
        selection=[
            ("sent", "Sent"),
            ("skipped", "Skipped"),
        ],
        required=True,
        default="sent",
    )
    sent_datetime = fields.Datetime(string="Sent On", readonly=True)
    skip_reason = fields.Char(string="Skip Reason", readonly=True)

    _sql_constraints = [
        (
            "unique_holiday_employee_greeting",
            "UNIQUE(holiday_id, employee_id)",
            "A holiday greeting has already been processed for this employee and public holiday.",
        ),
    ]
