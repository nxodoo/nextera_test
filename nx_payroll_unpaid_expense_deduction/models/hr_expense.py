import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrExpense(models.Model):
    _inherit = "hr.expense"

    payslip_deduction_id = fields.Many2one(
        "hr.payslip",
        string="Deducted in Payslip",
        readonly=True,
        copy=False,
        tracking=True,
        help="Payslip where this unpaid expense was deducted from salary.",
    )
    is_deducted_from_salary = fields.Boolean(
        string="Deducted from Salary",
        compute="_compute_is_deducted_from_salary",
        store=True,
    )
    salary_deduction_pending = fields.Boolean(
        string="Pending Salary Deduction",
        compute="_compute_salary_deduction_pending",
    )

    @api.depends("payslip_deduction_id")
    def _compute_is_deducted_from_salary(self):
        for expense in self:
            expense.is_deducted_from_salary = bool(expense.payslip_deduction_id)

    @api.depends("state", "payment_mode", "payslip_deduction_id", "employee_id", "product_id", "company_id")
    def _compute_salary_deduction_pending(self):
        for expense in self:
            company = expense.company_id
            if not company.auto_deduct_unpaid_expenses:
                expense.salary_deduction_pending = False
                continue
            if expense.state != "approved" or expense.payslip_deduction_id:
                expense.salary_deduction_pending = False
                continue
            # Recover unpaid company-paid spend via payroll deduction; employee reimbursements use allowance rules.
            if expense.payment_mode != "company_account":
                expense.salary_deduction_pending = False
                continue
            categories = company.expense_deduction_product_ids
            expense.salary_deduction_pending = not categories or expense.product_id in categories

    def action_open_deduction_payslip(self):
        """Open the payslip where the expense was deducted."""
        self.ensure_one()
        if not self.payslip_deduction_id:
            return False
        action = self.env.ref("hr_payroll.action_view_hr_payslip_form").read()[0]
        action.update({
            "views": [(self.env.ref("hr_payroll.view_hr_payslip_form").id, "form")],
            "res_id": self.payslip_deduction_id.id,
            "view_mode": "form",
        })
        return action

    def write(self, vals):
        protected_fields = {"date", "employee_id", "product_id", "payment_mode", "currency_id", "total_amount", "total_amount_currency", "sheet_id"}
        if protected_fields.intersection(vals):
            locked_expenses = self.filtered(lambda expense: expense.payslip_deduction_id.state in ("done", "paid"))
            if locked_expenses:
                raise UserError(_("You cannot modify expenses that were already deducted from a confirmed payslip."))
        res = super().write(vals)
        if "payslip_deduction_id" in vals:
            _logger.info(
                "Updated salary deduction linkage for expenses %s to payslip %s",
                self.ids,
                vals.get("payslip_deduction_id"),
            )
        return res

    @api.ondelete(at_uninstall=False)
    def _check_deduction_before_delete(self):
        if any(expense.payslip_deduction_id.state in ("done", "paid") for expense in self):
            raise UserError(_("Cannot delete an expense already deducted from a confirmed payslip."))
