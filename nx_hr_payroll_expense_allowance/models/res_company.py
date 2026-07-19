from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    payroll_expense_allowance_input_type_id = fields.Many2one(
        "hr.payslip.input.type",
        string="Expense Allowance Payslip Input",
        help="Default payslip input used to carry approved employee expenses before the EXP salary rule is computed.",
    )

    def _ensure_allowance_input_type_managed(self):
        for company in self:
            t = company.payroll_expense_allowance_input_type_id
            if t and not t.is_expense_allowance_managed:
                t.is_expense_allowance_managed = True

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._ensure_allowance_input_type_managed()
        return companies

    def write(self, vals):
        res = super().write(vals)
        if vals.get("payroll_expense_allowance_input_type_id"):
            self._ensure_allowance_input_type_managed()
        return res
