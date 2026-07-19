from odoo import fields, models


class HrLeaveAllocation(models.Model):
    _inherit = "hr.leave.allocation"

    policy_generation_type = fields.Selection(
        [
            ("service_years", "Years of Service"),
            ("employee_rule", "Employee Rule"),
        ],
        string="Policy Generation Type",
        readonly=True,
        copy=False,
    )
    based_on_years_of_service = fields.Boolean(
        string="Based on Years of Service",
        readonly=True,
        copy=False,
    )
    leave_allowance_rule_id = fields.Many2one(
        "hr.leave.allowance.rule",
        string="Rule Applied",
        readonly=True,
        copy=False,
    )
    service_anniversary_date = fields.Date(
        string="Allocation Date",
        readonly=True,
        copy=False,
    )
    service_year_number = fields.Integer(
        string="Service Year Number",
        readonly=True,
        copy=False,
    )
