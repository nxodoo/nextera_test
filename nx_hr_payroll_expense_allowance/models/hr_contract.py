from odoo import fields, models


class HrContract(models.Model):
    _inherit = "hr.contract"

    payroll_expense_reimburse_type_ids = fields.Many2many(
        "hr.expense.line.type",
        "hr_contract_payroll_expense_line_type_rel",
        "contract_id",
        "expense_line_type_id",
        string="Payroll Expense Line Types",
        domain="[('payroll_post_to_payroll', '=', True)]",
        help="If set, only these expense line types (among those marked for payroll) are reimbursed on payslips. "
        "Leave empty to allow every type configured for payroll posting.",
    )
