from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrExpenseLineType(models.Model):
    _inherit = "hr.expense.line.type"

    payroll_post_to_payroll = fields.Boolean(
        string="Post to Payroll",
        help="Approved unpaid expenses with lines of this type can be added to payslips as allowance.",
    )
    payroll_salary_rule_id = fields.Many2one(
        "hr.salary.rule",
        string="Related Salary Rule",
        domain="[('struct_id', '!=', False)]",
        help="Optional: salary rule that pays this allowance (typically reads the payslip input).",
    )
    payroll_payslip_input_type_id = fields.Many2one(
        "hr.payslip.input.type",
        string="Payslip Input Type",
        help="Override the company default input. Amounts for this expense type are summed into this input.",
    )

    @api.constrains(
        "payroll_post_to_payroll",
        "payroll_payslip_input_type_id",
        "company_id",
    )
    def _check_payroll_default_input(self):
        for rec in self.filtered("payroll_post_to_payroll"):
            company = rec.company_id or self.env.company
            if rec.payroll_payslip_input_type_id:
                continue
            if not company.payroll_expense_allowance_input_type_id:
                raise ValidationError(
                    _(
                        "Expense line type “%(name)s” is marked for payroll posting, but company “%(company)s” "
                        "has no default payslip input. Configure it in Payroll settings or set an input on the type.",
                        name=rec.display_name,
                        company=company.display_name,
                    )
                )

    def _ensure_payroll_input_types_managed(self):
        to_fix = self.mapped("payroll_payslip_input_type_id").filtered(
            lambda t: t and not t.is_expense_allowance_managed
        )
        if to_fix:
            to_fix.write({"is_expense_allowance_managed": True})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_payroll_input_types_managed()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get("payroll_payslip_input_type_id"):
            self._ensure_payroll_input_types_managed()
        return res
