from odoo import models, fields, _
import uuid


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    approval_token = fields.Char('Approval Token', copy=False)
    alternative_date_from = fields.Date(
        string="Alternative Date From"
    )

    alternative_date_to = fields.Date(
        string="Alternative Date To"
    )

    def generate_token(self):
        for rec in self:
            rec.approval_token = str(uuid.uuid4())

    def send_allocation_approval_mail(self):
        for allocation in self:
            employee = allocation.employee_id
            manager = employee.parent_id

            if not manager or not manager.email:
                continue

            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

            approve_url = f"{base_url}/allocation/approve/{allocation.id}/{allocation.approval_token}"
            reject_url = f"{base_url}/allocation/reject/{allocation.id}/{allocation.approval_token}"

            leave_type = allocation.holiday_status_id.name
            days = allocation.number_of_days

            mail_body = f"""
                <p>Dear {manager.name},</p>
                <p>The employee <strong>{employee.name}</strong> requested a leave allocation:</p>

                <ul>
                    <li><strong>Leave Type:</strong> {leave_type}</li>
                    <li><strong>Days:</strong> {days}</li>
                </ul>

                <p>
                    <a href="{approve_url}" style="padding:10px 20px;background:#28a745;color:white;text-decoration:none;border-radius:5px;">
                        Approve
                    </a>
                    &nbsp;&nbsp;
                    <a href="{reject_url}" style="padding:10px 20px;background:#dc3545;color:white;text-decoration:none;border-radius:5px;">
                        Reject
                    </a>
                </p>
            """

            mail_vals = {
                'subject': _('Leave Allocation Approval Request'),
                'body_html': mail_body,
                'email_to': manager.email,
                'email_from': employee.work_email or 'no-reply@company.com',
            }

            self.env['mail.mail'].sudo().create(mail_vals).send()
