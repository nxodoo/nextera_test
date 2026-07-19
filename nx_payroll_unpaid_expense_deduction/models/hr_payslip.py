import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

RULE_CODE = "UNPAID_EXP"


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    deducted_expense_ids = fields.One2many(
        "hr.expense",
        "payslip_deduction_id",
        string="Deducted Expenses",
        readonly=True,
    )
    total_deducted_expenses = fields.Monetary(
        string="Total Deducted Expenses",
        compute="_compute_deducted_expenses",
        store=True,
    )
    deducted_expense_count = fields.Integer(
        string="Deducted Expense Count",
        compute="_compute_deducted_expenses",
        store=True,
    )
    expense_deduction_warning = fields.Char(
        string="Expense Deduction Warning",
        compute="_compute_expense_deduction_warning",
    )

    @api.depends("deducted_expense_ids", "deducted_expense_ids.total_amount", "deducted_expense_ids.currency_id", "currency_id")
    def _compute_deducted_expenses(self):
        for payslip in self:
            payslip.deducted_expense_count = len(payslip.deducted_expense_ids)
            payslip.total_deducted_expenses = sum(
                payslip._convert_expense_amount_to_payslip_currency(expense)
                for expense in payslip.deducted_expense_ids
            )

    @api.depends("deducted_expense_ids", "net_wage")
    def _compute_expense_deduction_warning(self):
        for payslip in self:
            warning = False
            if payslip.deducted_expense_ids and payslip.net_wage < 0:
                warning = _(
                    "This payslip includes expense deductions that pushed the net salary below zero."
                )
            payslip.expense_deduction_warning = warning

    def _convert_expense_amount_to_payslip_currency(self, expense):
        """Convert an expense amount from company currency to payslip currency."""
        self.ensure_one()
        target_currency = self.currency_id or self.company_id.currency_id
        source_currency = expense.company_currency_id
        if not target_currency or not source_currency:
            return expense.total_amount
        return source_currency._convert(
            expense.total_amount,
            target_currency,
            self.company_id,
            self.date_to or expense.date or fields.Date.today(),
        )

    def _get_expense_residual_ratio(self, expense):
        """Return the unpaid ratio of an expense based on its sheet payment status."""
        self.ensure_one()
        sheet = expense.sheet_id
        if not sheet:
            return 1.0
        if sheet.payment_state in ("paid", "reversed"):
            return 0.0
        if sheet.payment_state == "partial" and sheet.total_amount:
            return max(min(sheet.amount_residual / sheet.total_amount, 1.0), 0.0)
        return 1.0

    def _get_expense_deduction_domain(self):
        """Build the domain for deductible expenses in the current payslip window."""
        self.ensure_one()
        return [
            ("employee_id", "=", self.employee_id.id),
            ("payment_mode", "=", "company_account"),
            ("state", "=", "approved"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            "|",
            ("payslip_deduction_id", "=", False),
            ("payslip_deduction_id", "=", self.id),
        ]

    def _get_unpaid_expense_candidates(self):
        """Return expenses that match the configured deduction rules."""
        self.ensure_one()
        if not self.employee_id or not self.date_from or not self.date_to:
            return self.env["hr.expense"]

        company = self.company_id
        expenses = self.env["hr.expense"].search(self._get_expense_deduction_domain(), order="date asc, id asc")
        if company.expense_deduction_product_ids:
            expenses = expenses.filtered(lambda expense: expense.product_id in company.expense_deduction_product_ids)
        return expenses

    def _build_expense_deduction_rule_name(self, expenses):
        """Build a descriptive payslip line label for the deducted expenses."""
        self.ensure_one()
        base_name = _("Deduction - Unpaid Approved Expenses")
        if not expenses:
            return base_name
        names = expenses.mapped("name")
        preview = ", ".join(names[:3])
        if len(names) > 3:
            preview = _("%(preview)s, +%(remaining)s more", preview=preview, remaining=len(names) - 3)
        return _("%(name)s (%(count)s expenses: %(preview)s)", name=base_name, count=len(expenses), preview=preview)

    def _sync_deducted_expenses(self, expenses):
        """Keep the payslip-to-expense linkage in sync with the latest rule computation."""
        self.ensure_one()
        current_expenses = self.deducted_expense_ids
        expenses_to_unlink = current_expenses - expenses
        expenses_to_link = expenses - current_expenses
        if expenses_to_unlink:
            expenses_to_unlink.write({"payslip_deduction_id": False})
        if expenses_to_link:
            expenses_to_link.write({"payslip_deduction_id": self.id})

    def _get_unpaid_expense_salary_rule_result(self, categories=None):
        """Compute the salary rule payload for unpaid approved expenses.

        The rule returns a negative amount because it belongs to the payroll
        deduction category. Expenses are linked to the current payslip during
        computation so the user can audit the recovered items directly from the
        payslip form and reports.
        """
        self.ensure_one()
        empty_result = {
            "amount": 0.0,
            "name": _("Deduction - Unpaid Approved Expenses"),
            "expenses": self.env["hr.expense"],
        }
        if not self.company_id.auto_deduct_unpaid_expenses:
            self._sync_deducted_expenses(self.env["hr.expense"])
            return empty_result

        expenses = self._get_unpaid_expense_candidates()
        if not expenses:
            self._sync_deducted_expenses(expenses)
            return empty_result

        precision_rounding = (self.currency_id or self.company_id.currency_id).rounding
        available_before_rule = None
        if categories is not None:
            gross_total = categories.get("GROSS", 0.0) or 0.0
            previous_deductions = categories.get("DED", 0.0) or 0.0
            available_before_rule = max(gross_total + previous_deductions, 0.0)

        selected_expenses = self.env["hr.expense"]
        total_amount = 0.0
        for expense in expenses:
            residual_ratio = self._get_expense_residual_ratio(expense)
            if float_is_zero(residual_ratio, precision_rounding=precision_rounding):
                continue
            converted_amount = self._convert_expense_amount_to_payslip_currency(expense) * residual_ratio
            if float_is_zero(converted_amount, precision_rounding=precision_rounding):
                continue
            if available_before_rule is not None and float_compare(converted_amount, available_before_rule, precision_rounding=precision_rounding) == 1:
                continue
            selected_expenses |= expense
            total_amount += converted_amount
            if available_before_rule is not None:
                available_before_rule -= converted_amount

        self._sync_deducted_expenses(selected_expenses)

        if not selected_expenses:
            return empty_result

        _logger.info(
            "Computed unpaid expense deduction for payslip %s with expenses %s and total %.2f",
            self.id,
            selected_expenses.ids,
            total_amount,
        )
        return {
            "amount": -total_amount,
            "name": self._build_expense_deduction_rule_name(selected_expenses),
            "expenses": selected_expenses,
        }

    def action_open_deducted_expenses(self):
        """Open the expenses deducted in the current payslip."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Deducted Expenses"),
            "res_model": "hr.expense",
            "view_mode": "list,form",
            "domain": [("id", "in", self.deducted_expense_ids.ids)],
            "context": {"default_employee_id": self.employee_id.id},
        }

    def action_payslip_draft(self):
        for payslip in self:
            payslip.deducted_expense_ids.write({"payslip_deduction_id": False})
        return super().action_payslip_draft()

    def action_payslip_cancel(self):
        draft_or_waiting = self.filtered(lambda payslip: payslip.state in ("draft", "verify"))
        if draft_or_waiting:
            draft_or_waiting.deducted_expense_ids.write({"payslip_deduction_id": False})
        return super().action_payslip_cancel()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        self._send_deduction_notification()
        return res

    def _send_deduction_notification(self):
        """Notify employees that expenses were deducted in their payslip."""
        template = self.env.ref(
            "nx_payroll_unpaid_expense_deduction.email_template_expense_deducted",
            raise_if_not_found=False,
        )
        if not template:
            return
        for payslip in self.filtered("deducted_expense_ids"):
            template.send_mail(payslip.id, force_send=False)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_with_deductions(self):
        if any(payslip.deducted_expense_ids for payslip in self):
            raise UserError(_("Cannot delete a payslip with deducted expenses. Reset it to draft first."))

    @api.model
    def _prepare_unpaid_expense_rule_values(self, structure):
        """Prepare rule values for a payroll structure."""
        return {
            "name": _("Deduction - Unpaid Approved Expenses"),
            "code": RULE_CODE,
            "struct_id": structure.id,
            "sequence": 175,
            "category_id": self.env.ref("hr_payroll.DED").id,
            "appears_on_payslip": True,
            "condition_select": "none",
            "amount_select": "code",
            "amount_python_compute": """
payload = payslip._get_unpaid_expense_salary_rule_result(categories)
result = payload['amount']
result_name = payload['name']
""".strip(),
            "note": _(
                "<p>Automatically deducts approved expenses that match the payslip period "
                "and are still pending salary recovery.</p>"
            ),
        }

    @api.model
    def _sync_unpaid_expense_rules_to_structures(self):
        """Create the deduction rule on payroll structures that do not have it yet."""
        structures = self.env["hr.payroll.structure"].search([])
        if not structures:
            return
        existing_rules = self.env["hr.salary.rule"].search([("code", "=", RULE_CODE)])
        structures_with_rule = set(existing_rules.mapped("struct_id").ids)
        rules_to_create = []
        for structure in structures.filtered(lambda struct: struct.id not in structures_with_rule):
            rules_to_create.append(self._prepare_unpaid_expense_rule_values(structure))
        if rules_to_create:
            self.env["hr.salary.rule"].create(rules_to_create)
