from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    auto_deduct_unpaid_expenses = fields.Boolean(
        string="Auto Deduct Unpaid Expenses",
        default=True,
        help="Automatically deduct approved unpaid expenses during payslip computation.",
    )
    expense_deduction_product_ids = fields.Many2many(
        "product.product",
        "res_company_expense_deduction_product_rel",
        "company_id",
        "product_id",
        string="Expense Categories to Deduct",
        domain=[("can_be_expensed", "=", True)],
        help="Leave empty to include all expense categories.",
    )
    deduct_only_company_expenses = fields.Boolean(
        string="Deduct Only Company-Paid Expenses",
        default=True,
        help="Deprecated: payroll deduction (UNPAID_EXP) always applies to company-paid expenses only. "
        "Employee (to reimburse) expenses belong in payroll allowance (EXP), not in this deduction.",
    )
