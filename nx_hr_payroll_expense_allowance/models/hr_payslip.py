import logging
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

RULE_CODE = "EXP"


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    payroll_allowance_expense_ids = fields.One2many(
        "hr.expense",
        "payroll_allowance_payslip_id",
        string="Payroll Allowance Expenses",
        readonly=True,
    )
    payroll_allowance_expense_count = fields.Integer(
        string="Allowance Expense Count",
        compute="_compute_payroll_allowance_expense_stats",
        store=True,
    )
    payroll_allowance_total = fields.Monetary(
        string="Allowance Expenses Total",
        compute="_compute_payroll_allowance_expense_stats",
        store=True,
        currency_field="currency_id",
    )

    @api.depends(
        "payroll_allowance_expense_ids",
        "input_line_ids",
        "input_line_ids.amount",
        "input_line_ids.input_type_id.is_expense_allowance_managed",
        "currency_id",
    )
    def _compute_payroll_allowance_expense_stats(self):
        for payslip in self:
            payslip.payroll_allowance_expense_count = len(payslip.payroll_allowance_expense_ids)
            payslip.payroll_allowance_total = sum(
                line.amount
                for line in payslip.input_line_ids
                if line.input_type_id.is_expense_allowance_managed
            )

    def _get_expense_allowance_residual_ratio(self, expense):
        """Return the unpaid portion of an expense based on its report payment status."""
        self.ensure_one()
        sheet = expense.sheet_id
        if not sheet:
            return 1.0
        if sheet.payment_state in ("paid", "reversed"):
            return 0.0
        if sheet.payment_state == "partial" and sheet.total_amount:
            return max(min(sheet.amount_residual / sheet.total_amount, 1.0), 0.0)
        return 1.0

    def _expense_allowance_not_salary_deducted(self, expense):
        if "payslip_deduction_id" not in expense._fields:
            return True
        return not expense.payslip_deduction_id

    def _expense_has_payroll_allowance_lines(self, expense):
        self.ensure_one()
        contract = self.contract_id
        allowed_types = contract.payroll_expense_reimburse_type_ids
        for line in expense.expense_line_ids:
            line_type = line.expense_line_type_id
            if not line_type.payroll_post_to_payroll:
                continue
            if allowed_types and line_type not in allowed_types:
                continue
            return True
        return False

    def _expense_allowance_fully_paid(self, expense):
        self.ensure_one()
        precision = (self.currency_id or self.company_id.currency_id).rounding
        ratio = self._get_expense_allowance_residual_ratio(expense)
        return float_is_zero(ratio, precision_rounding=precision)

    def _get_payroll_allowance_expense_candidates(self):
        self.ensure_one()
        if not self.employee_id or not self.date_from or not self.date_to:
            return self.env["hr.expense"]

        domain = [
            ("employee_id", "=", self.employee_id.id),
            ("payment_mode", "=", "own_account"),
            ("payroll_reimbursed_via_payroll", "=", False),
            ("state", "in", ("approved", "payroll_pending")),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            "|",
            ("payroll_allowance_payslip_id", "=", False),
            ("payroll_allowance_payslip_id", "=", self.id),
        ]
        expenses = self.env["hr.expense"].search(domain, order="date asc, id asc")
        expenses = expenses.filtered(self._expense_allowance_not_salary_deducted)
        expenses = expenses.filtered(lambda e: self._expense_has_payroll_allowance_lines(e))
        expenses = expenses.filtered(lambda e: not self._expense_allowance_fully_paid(e))
        return expenses

    def _convert_expense_line_amount_to_payslip_currency(self, line, expense):
        self.ensure_one()
        line_currency = line.currency_id
        company_currency = expense.company_currency_id
        payslip_currency = self.currency_id or self.company_id.currency_id
        conversion_date = self.date_to or expense.date or fields.Date.today()
        amount_company = line_currency._convert(
            line.total_amount,
            company_currency,
            expense.company_id,
            expense.date or conversion_date,
        )
        return company_currency._convert(
            amount_company,
            payslip_currency,
            expense.company_id,
            conversion_date,
        )

    def _collect_payroll_allowance_buckets(self, expenses):
        """Return {input_type: amount} for automated allowance inputs."""
        self.ensure_one()
        buckets = defaultdict(float)
        precision = (self.currency_id or self.company_id.currency_id).rounding

        for expense in expenses:
            ratio = self._get_expense_allowance_residual_ratio(expense)
            if float_is_zero(ratio, precision_rounding=precision):
                continue
            contract = self.contract_id
            allowed_types = contract.payroll_expense_reimburse_type_ids
            for line in expense.expense_line_ids:
                line_type = line.expense_line_type_id
                if not line_type.payroll_post_to_payroll:
                    continue
                if allowed_types and line_type not in allowed_types:
                    continue
                input_type = (
                    line_type.payroll_payslip_input_type_id
                    or self.company_id.payroll_expense_allowance_input_type_id
                )
                if not input_type:
                    continue
                line_total = self._convert_expense_line_amount_to_payslip_currency(line, expense)
                buckets[input_type] += line_total * ratio
        return buckets

    def _payroll_allowance_expenses_from_buckets(self, expenses, buckets):
        """Expenses that contribute a non-zero allowance after residual ratio."""
        self.ensure_one()
        precision = (self.currency_id or self.company_id.currency_id).rounding
        if not buckets:
            return self.env["hr.expense"]

        linked = self.env["hr.expense"]
        for expense in expenses:
            ratio = self._get_expense_allowance_residual_ratio(expense)
            if float_is_zero(ratio, precision_rounding=precision):
                continue
            contribution = 0.0
            contract = self.contract_id
            allowed_types = contract.payroll_expense_reimburse_type_ids
            for line in expense.expense_line_ids:
                line_type = line.expense_line_type_id
                if not line_type.payroll_post_to_payroll:
                    continue
                if allowed_types and line_type not in allowed_types:
                    continue
                input_type = (
                    line_type.payroll_payslip_input_type_id
                    or self.company_id.payroll_expense_allowance_input_type_id
                )
                if not input_type or input_type not in buckets:
                    continue
                line_total = self._convert_expense_line_amount_to_payslip_currency(line, expense)
                contribution += line_total * ratio
            if float_compare(contribution, 0.0, precision_rounding=precision) == 1:
                linked |= expense
        return linked

    def _clear_managed_allowance_inputs(self):
        self.ensure_one()
        managed_inputs = self.input_line_ids.filtered(
            lambda line: line.input_type_id.is_expense_allowance_managed
        )
        managed_inputs.unlink()

    def _apply_payroll_allowance_input_lines(self, buckets):
        self.ensure_one()
        Input = self.env["hr.payslip.input"]
        contract = self.contract_id
        rounding = (self.currency_id or self.company_id.currency_id).rounding
        for input_type, amount in buckets.items():
            if float_is_zero(amount, precision_rounding=rounding):
                continue
            Input.create(
                {
                    "payslip_id": self.id,
                    "input_type_id": input_type.id,
                    "amount": amount,
                    "contract_id": contract.id if contract else False,
                }
            )

    def _sync_payroll_expense_allowance_inputs(self):
        """Populate payslip inputs and link expenses before salary rules run."""
        for payslip in self:
            if payslip.state not in ("draft", "verify"):
                continue

            payslip.env["hr.expense"].search(
                [("payroll_allowance_payslip_id", "=", payslip.id)]
            ).write({"payroll_allowance_payslip_id": False})

            payslip._clear_managed_allowance_inputs()

            candidates = payslip._get_payroll_allowance_expense_candidates()
            buckets = payslip._collect_payroll_allowance_buckets(candidates)
            payslip._apply_payroll_allowance_input_lines(buckets)
            to_link = payslip._payroll_allowance_expenses_from_buckets(candidates, buckets)
            if to_link:
                to_link.write({"payroll_allowance_payslip_id": payslip.id})

            _logger.info(
                "Payroll expense allowance for payslip %s: %s expense(s), inputs %s",
                payslip.id,
                len(to_link),
                {k.code: round(v, 2) for k, v in buckets.items()},
            )

    def compute_sheet(self):
        payslips = self.filtered(lambda slip: slip.state in ("draft", "verify"))
        payslips._sync_payroll_expense_allowance_inputs()
        return super().compute_sheet()

    def action_open_payroll_allowance_expenses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Payroll Allowance Expenses"),
            "res_model": "hr.expense",
            "view_mode": "list,form",
            "domain": [("id", "in", self.payroll_allowance_expense_ids.ids)],
            "context": {"default_employee_id": self.employee_id.id},
        }

    def action_payslip_draft(self):
        for payslip in self:
            if payslip.payroll_allowance_expense_ids:
                payslip.payroll_allowance_expense_ids.write(
                    {
                        "payroll_allowance_payslip_id": False,
                        "payroll_reimbursed_via_payroll": False,
                    }
                )
            payslip._clear_managed_allowance_inputs()
        return super().action_payslip_draft()

    def action_payslip_cancel(self):
        for payslip in self:
            if payslip.payroll_allowance_expense_ids:
                payslip.payroll_allowance_expense_ids.write(
                    {
                        "payroll_allowance_payslip_id": False,
                        "payroll_reimbursed_via_payroll": False,
                    }
                )
            payslip._clear_managed_allowance_inputs()
        return super().action_payslip_cancel()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for payslip in self:
            payslip.payroll_allowance_expense_ids.write({"payroll_reimbursed_via_payroll": True})
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_payroll_allowance_expenses(self):
        if any(payslip.payroll_allowance_expense_ids for payslip in self):
            raise UserError(
                _("Reset the payslip to draft and clear payroll allowance expenses before deleting it.")
            )

    @api.model
    def _prepare_expense_allowance_rule_values(self, structure):
        return {
            "name": _("Employee Expenses"),
            "code": RULE_CODE,
            "struct_id": structure.id,
            "sequence": 176,
            "category_id": self.env.ref("hr_payroll.ALW").id,
            "appears_on_payslip": True,
            "condition_select": "none",
            "amount_select": "code",
            "amount_python_compute": """
result = sum(
    line.amount
    for line in payslip.input_line_ids
    if line.input_type_id.is_expense_allowance_managed
)
            """.strip(),
            "note": _(
                "<p>Reads the Employee Expenses payslip input filled from approved unpaid expenses.</p>"
            ),
        }

    @api.model
    def _sync_expense_allowance_rules_to_structures(self):
        structures = self.env["hr.payroll.structure"].search([])
        if not structures:
            return
        existing = self.env["hr.salary.rule"].search([("code", "=", RULE_CODE)])
        covered = set(existing.mapped("struct_id").ids)
        to_create = [
            self._prepare_expense_allowance_rule_values(structure)
            for structure in structures.filtered(lambda s: s.id not in covered)
        ]
        if to_create:
            self.env["hr.salary.rule"].create(to_create)
