from odoo import fields, models


class HrPayslipInputType(models.Model):
    _inherit = "hr.payslip.input.type"

    is_expense_allowance_managed = fields.Boolean(
        string="Managed by Expense Allowance",
        default=False,
        help="When set, payslip computation replaces input lines of this type with automated expense totals.",
    )
