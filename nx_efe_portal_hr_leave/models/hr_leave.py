from odoo import models, fields, api, _
import uuid


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    approval_token = fields.Char('Approval Token', copy=False)

    def generate_token(self):
        for rec in self:
            rec.approval_token = str(uuid.uuid4())

    def send_leave_approval_mail(self):
        for leave in self:
            employee = leave.employee_id
            manager = employee.parent_id

            if not manager or not manager.email:
                continue

            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

            approve_url = f"{base_url}/leave/approve/{leave.id}/{leave.approval_token}"
            reject_url = f"{base_url}/leave/reject/{leave.id}/{leave.approval_token}"

            days = int(leave.number_of_days) or 0

            leave_type = leave.holiday_status_id.name
            date_from = leave.request_date_from and leave.request_date_from.strftime("%Y-%m-%d %H:%M")
            date_to = leave.request_date_to and leave.request_date_to.strftime("%Y-%m-%d %H:%M")
            description = leave.name or "No description provided"

            mail_body = f"""
                <p>Dear {manager.name},</p>
                <p>The employee <strong>{employee.name}</strong> has submitted a leave request with the following details:</p>

                <table style="border-collapse: collapse; margin: 10px 0;">
                    <tr>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;"><strong>Leave Type:</strong></td>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;">{leave_type}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;"><strong>Date From:</strong></td>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;">{date_from}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;"><strong>Date To:</strong></td>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;">{date_to}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;"><strong>Total Days:</strong></td>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;">{days}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;"><strong>Description:</strong></td>
                        <td style="padding: 6px 12px; border: 1px solid #ddd;">{description}</td>
                    </tr>
                </table>

                <p>Please choose an action:</p>

                <p>
                    <a href="{approve_url}" style="padding:10px 20px;background:#28a745;color:white;text-decoration:none;border-radius:5px; font-weight:bold;">
                        Approve
                    </a>
                    &nbsp;&nbsp;
                    <a href="{reject_url}" style="padding:10px 20px;background:#dc3545;color:white;text-decoration:none;border-radius:5px; font-weight:bold;">
                        Reject
                    </a>
                </p>

                <p>Thank you.</p>
            """

            mail_vals = {
                'subject': _('Leave Approval Request'),
                'body_html': mail_body,
                'email_to': manager.email,
                'email_from': leave.employee_id.work_email or 'no-reply@yourcompany.com',
            }

            self.env['mail.mail'].sudo().create(mail_vals).send()

