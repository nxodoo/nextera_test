import logging

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.tools import format_date

_logger = logging.getLogger(__name__)

BIRTHDAY_MISSING_EMAIL_ACTIVITY_SUMMARY = 'Update employee work email for birthday greeting'


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    birthday_last_greeting_date = fields.Date(
        string='Last Birthday Greeting Date',
        copy=False,
        groups='hr.group_hr_user',
        help='Technical field used to avoid sending multiple birthday greetings on the same day.',
    )

    @api.model
    def _cron_send_monthly_birthday_reminders(self):
        """Send the monthly birthday reminder to the configured HR manager.

        The cron runs daily but only sends reminders on the first day of the
        month. A technical date on the company prevents duplicate reminders if
        the cron is executed more than once on the same day.
        """
        today = fields.Date.context_today(self)
        if today.day != 1:
            return True

        companies = self.env['res.company'].sudo().search([
            ('birthday_management_enabled', '=', True),
            ('send_monthly_birthday_reminder', '=', True),
        ])
        for company in companies:
            if self._is_same_month(company.birthday_last_reminder_date, today):
                continue

            employees = self._get_company_birthday_employees(company, month=today.month)
            company.birthday_last_reminder_date = today

            if not employees:
                _logger.info(
                    "No birthdays found for company %s during month %s.",
                    company.display_name,
                    today.month,
                )
                continue

            manager = company.birthday_reminder_manager_id
            if not manager or not manager.partner_id:
                _logger.warning(
                    "Birthday reminder manager is not configured for company %s.",
                    company.display_name,
                )
                continue

            self._send_monthly_birthday_reminder(company, manager, employees, today)

        return True

    @api.model
    def _cron_send_birthday_greetings(self):
        """Send birthday greetings and missing-email activities for today.

        Employees with a work email receive the configured greeting template.
        Employees without a work email trigger one automated activity for the
        configured HR manager so the email can be updated.
        """
        today = fields.Date.context_today(self)
        companies = self.env['res.company'].sudo().search([
            ('birthday_management_enabled', '=', True),
            ('send_automatic_birthday_greeting', '=', True),
        ])

        for company in companies:
            employees = self._get_company_birthday_employees(
                company,
                month=today.month,
                day=today.day,
            ).filtered(lambda employee: employee.birthday_last_greeting_date != today)

            if not employees:
                continue

            template = self._get_birthday_greeting_template(company)
            if not template:
                _logger.warning(
                    "No birthday greeting template is available for company %s.",
                    company.display_name,
                )
                continue

            employees_with_email = employees.filtered('work_email')
            employees_without_email = employees - employees_with_email

            self._send_birthday_greetings(template, employees_with_email, today)

            manager = company.birthday_reminder_manager_id
            if employees_without_email and manager:
                self._schedule_missing_email_activities(
                    employees_without_email,
                    manager,
                    today,
                )
            elif employees_without_email:
                _logger.warning(
                    "Skipping missing email activities for company %s because no birthday reminder manager is configured.",
                    company.display_name,
                )

        return True

    @api.model
    def _get_company_birthday_employees(self, company, month, day=None):
        """Return active employees for a company whose birthday matches a period.

        :param res.company company: company to search employees for
        :param int month: target month number
        :param int day: optional target day number
        :return: matching employee recordset
        :rtype: hr.employee
        """
        employees = self.sudo().search([
            ('company_id', '=', company.id),
            ('birthday', '!=', False),
            ('active', '=', True),
        ])

        def _matches_birthday(employee):
            if employee.birthday.month != month:
                return False
            return day is None or employee.birthday.day == day

        return employees.filtered(_matches_birthday).sorted(
            key=lambda employee: (employee.birthday.month, employee.birthday.day, employee.name or '')
        )

    @api.model
    def _send_monthly_birthday_reminder(self, company, manager, employees, today):
        """Send the monthly birthday reminder notification to the HR manager.

        :param res.company company: company owning the reminder configuration
        :param res.users manager: user receiving the reminder
        :param hr.employee employees: employees whose birthdays are in the month
        :param date today: current execution date
        :return: created mail.message
        :rtype: mail.message
        """
        month_name = format_date(
            self.env,
            today,
            date_format='MMMM',
            lang_code=manager.lang,
        )
        subject = _('Employee Birthday Reminder for %(month)s', month=month_name)
        body = self._build_monthly_birthday_reminder_body(manager, employees, month_name)
        odoobot = self.env.ref('base.partner_root', raise_if_not_found=False)

        return self.env['mail.thread'].sudo().message_notify(
            model='res.company',
            res_id=company.id,
            subject=subject,
            body=body,
            author_id=odoobot.id if odoobot else False,
            partner_ids=[manager.partner_id.id],
            email_layout_xmlid='mail.mail_notification_light',
        )

    @api.model
    def _build_monthly_birthday_reminder_body(self, manager, employees, month_name):
        """Build the monthly birthday reminder HTML body.

        :param res.users manager: manager receiving the reminder
        :param hr.employee employees: employees to list in the reminder
        :param str month_name: translated month label
        :return: HTML body markup
        :rtype: markupsafe.Markup
        """
        rows = []
        for employee in employees:
            birthday_label = format_date(
                self.env,
                employee.birthday,
                date_format='dd/MM',
                lang_code=manager.lang,
            )
            rows.append(
                Markup(
                    '<tr>'
                    '<td style="padding: 8px; border-bottom: 1px solid #e9ecef;">%s</td>'
                    '<td style="padding: 8px; border-bottom: 1px solid #e9ecef; text-align: center;">%s</td>'
                    '</tr>'
                ) % (escape(employee.name or ''), escape(birthday_label))
            )

        return Markup(
            '<div>'
            '<p>%s</p>'
            '<p>%s</p>'
            '<table style="width: 100%%; border-collapse: collapse; margin-top: 16px;">'
            '<thead>'
            '<tr>'
            '<th style="padding: 8px; border-bottom: 2px solid #ced4da; text-align: left;">%s</th>'
            '<th style="padding: 8px; border-bottom: 2px solid #ced4da; text-align: center;">%s</th>'
            '</tr>'
            '</thead>'
            '<tbody>%s</tbody>'
            '</table>'
            '<p style="margin-top: 16px;">%s</p>'
            '</div>'
        ) % (
            escape(_('Dear %(manager)s,', manager=manager.name or _('HR Manager'))),
            escape(_('Here is a reminder of employee birthdays in %(month)s:', month=month_name)),
            escape(_('Name')),
            escape(_('Birthday')),
            Markup('').join(rows),
            escape(_('Please make the necessary arrangements to celebrate their special day.')),
        )

    @api.model
    def _get_birthday_greeting_template(self, company):
        """Return the greeting template configured for a company.

        The company-specific template is used first. If it is not configured,
        the module default template is used as a fallback.

        :param res.company company: company whose template is requested
        :return: greeting template or empty recordset
        :rtype: mail.template
        """
        return company.birthday_greeting_template_id or self.env.ref(
            'nx_hr_birthday_management.mail_template_employee_birthday_greeting',
            raise_if_not_found=False,
        )

    @api.model
    def _send_birthday_greetings(self, template, employees, today):
        """Send birthday greeting emails to employees with a work email.

        :param mail.template template: greeting email template
        :param hr.employee employees: employees to greet
        :param date today: current execution date
        :return: None
        """
        greeted_employees = self.env['hr.employee']
        for employee in employees:
            try:
                template.send_mail(
                    employee.id,
                    force_send=True,
                    email_values={'email_to': employee.work_email},
                )
                greeted_employees |= employee
            except Exception:
                _logger.exception(
                    "Failed to send birthday greeting email to employee %s (%s).",
                    employee.display_name,
                    employee.work_email,
                )

        if greeted_employees:
            greeted_employees.sudo().write({'birthday_last_greeting_date': today})

    @api.model
    def _schedule_missing_email_activities(self, employees, manager, today):
        """Create one missing-email activity per employee when needed.

        :param hr.employee employees: birthday employees without work email
        :param res.users manager: HR responsible user
        :param date today: current execution date
        :return: None
        """
        activity_model = self.env['mail.activity'].sudo()
        employee_model_id = self.env['ir.model']._get_id('hr.employee')
        existing_activities = activity_model.search([
            ('res_model_id', '=', employee_model_id),
            ('res_id', 'in', employees.ids),
            ('user_id', '=', manager.id),
            ('summary', '=', BIRTHDAY_MISSING_EMAIL_ACTIVITY_SUMMARY),
            ('active', '=', True),
        ])
        existing_employee_ids = set(existing_activities.mapped('res_id'))

        for employee in employees.filtered(lambda record: record.id not in existing_employee_ids):
            birthday_label = format_date(
                self.env,
                employee.birthday,
                date_format='dd/MM',
                lang_code=manager.lang,
            )
            note = _(
                'Employee %(employee)s has a birthday on %(birthday)s, but the work email is missing. '
                'Please update the employee work email so the birthday greeting can be sent later.',
                employee=employee.name,
                birthday=birthday_label,
            )
            employee.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=today,
                summary=BIRTHDAY_MISSING_EMAIL_ACTIVITY_SUMMARY,
                note=note,
                user_id=manager.id,
            )

    @api.model
    def _is_same_month(self, left_date, right_date):
        """Check whether two dates belong to the same month and year.

        :param date left_date: first date
        :param date right_date: second date
        :return: whether both dates share the same month and year
        :rtype: bool
        """
        return bool(
            left_date
            and right_date
            and left_date.year == right_date.year
            and left_date.month == right_date.month
        )
