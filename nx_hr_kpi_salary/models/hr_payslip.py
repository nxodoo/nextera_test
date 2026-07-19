from odoo import api, fields, models, _
from odoo.exceptions import UserError

RULE_CODE = "KPI"


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    kpi_evaluation_line_id = fields.Many2one(
        "hr.kpi.evaluation.line",
        string="KPI Evaluation Line",
        readonly=True,
        copy=False,
    )
    kpi_bonus_amount = fields.Monetary(
        string="KPI Bonus",
        compute="_compute_kpi_bonus_amount",
        store=True,
    )
    kpi_warning_message = fields.Char(
        string="KPI Warning",
        compute="_compute_kpi_warning_message",
    )

    def _get_account_move_line_name(self, line):
        """Return the label used for payroll journal items.

        Parameters:
            line (hr.payslip.line): Salary computation line being posted.

        Returns:
            str: The description that should appear on the accounting move line.
        """
        self.ensure_one()
        if line.accounting_description:
            return line.accounting_description
        return False

    def _prepare_line_values(self, line, account_id, date, debit, credit):
        """Inject the custom payslip description into generated journal items."""
        values = super()._prepare_line_values(line, account_id, date, debit, credit)
        values["name"] = self._get_account_move_line_name(line)
        return values

    def _get_existing_lines(self, line_ids, line, account_id, debit, credit):
        """Match existing move lines using the effective accounting description."""
        target_name = self._get_account_move_line_name(line)
        return (
            line_id
            for line_id in line_ids
            if line_id["name"] == target_name
            and line_id["account_id"] == account_id
            and ((line_id["debit"] > 0 and credit <= 0) or (line_id["credit"] > 0 and debit <= 0))
            and (
                (
                    not line_id["analytic_distribution"]
                    and not line.salary_rule_id.analytic_account_id.id
                    and not line.slip_id.contract_id.analytic_account_id.id
                )
                or (
                    line_id["analytic_distribution"]
                    and line.salary_rule_id.analytic_account_id.id in line_id["analytic_distribution"]
                )
                or (
                    line_id["analytic_distribution"]
                    and line.slip_id.contract_id.analytic_account_id.id in line_id["analytic_distribution"]
                )
            )
            and self._check_debit_credit_tags(line_id, line, account_id)
        )

    @api.depends("kpi_evaluation_line_id.payout_value")
    def _compute_kpi_bonus_amount(self):
        for payslip in self:
            payslip.kpi_bonus_amount = payslip.kpi_evaluation_line_id.payout_value

    @api.depends("employee_id", "contract_id", "date_from", "date_to", "state")
    def _compute_kpi_warning_message(self):
        for payslip in self:
            if payslip.state not in ("draft", "verify") or not payslip._has_kpi_configuration():
                payslip.kpi_warning_message = False
                continue
            missing_line = payslip._find_matching_kpi_evaluation_line()
            payslip.kpi_warning_message = False if missing_line else _(
                "The following employees have no KPI defined: %(employee)s",
                employee=payslip.employee_id.name,
            )

    def _has_kpi_configuration(self):
        self.ensure_one()
        contract = self.contract_id
        return bool(
            contract
            and contract.kpi_type
            and contract.kpi_frequency
            and contract.kpi_value > 0
            and (not self.date_to or contract._is_kpi_due_for_date(self.date_to))
        )

    def _get_kpi_period_bounds(self):
        """Return the KPI period for the payslip based on the contract frequency."""
        self.ensure_one()
        if not self.contract_id or not self.date_to:
            return False, False
        return self.contract_id._get_kpi_period_bounds_for_frequency(self.date_to, self.contract_id.kpi_frequency, self.contract_id.quarterly_kpi_months)

    def _find_matching_kpi_evaluation_line(self):
        """Find the approved KPI line matching this payslip period."""
        self.ensure_one()
        if not self._has_kpi_configuration():
            return self.env["hr.kpi.evaluation.line"]

        period_start, period_end = self._get_kpi_period_bounds()
        if not period_start:
            return self.env["hr.kpi.evaluation.line"]
        domain = [
            ("employee_id", "=", self.employee_id.id),
            ("evaluation_id.company_id", "=", self.company_id.id),
            ("evaluation_id.frequency", "=", self.contract_id.kpi_frequency),
            ("evaluation_id.period_start", "=", period_start),
            ("evaluation_id.period_end", "=", period_end),
            ("evaluation_id.state", "in", ("confirmed", "under_pay", "paid")),
        ]
        if self.contract_id.kpi_frequency == "quarterly":
            domain.append(("evaluation_id.quarterly_kpi_months", "=", self.contract_id.quarterly_kpi_months))
        return self.env["hr.kpi.evaluation.line"].search(domain, limit=1)

    def _get_kpi_evaluation_line(self):
        """Return the KPI line to use and protect against duplicate payroll linkage."""
        self.ensure_one()
        evaluation_line = self._find_matching_kpi_evaluation_line()
        if not evaluation_line:
            return self.env["hr.kpi.evaluation.line"]
        if evaluation_line.payslip_id and evaluation_line.payslip_id != self:
            raise UserError(
                _(
                    "KPI has already been calculated for %(employee)s in %(period)s.",
                    employee=self.employee_id.name,
                    period=evaluation_line.evaluation_id.period_label,
                )
            )
        return evaluation_line

    def _release_kpi_evaluation_lines(self):
        """Detach KPI lines before recomputing or reopening payslips."""
        linked_lines = self.mapped("kpi_evaluation_line_id")
        if linked_lines:
            linked_lines.write({"payslip_id": False})
        self.filtered("kpi_evaluation_line_id").write({"kpi_evaluation_line_id": False})

    def _get_missing_kpi_payslips(self):
        return self.filtered(lambda slip: slip._has_kpi_configuration() and not slip._find_matching_kpi_evaluation_line())

    def _open_missing_kpi_wizard(self, missing_payslips):
        """Ask the user whether to proceed with KPI equal to zero."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Missing KPI Evaluations"),
            "res_model": "hr.payslip.kpi.missing.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_payslip_ids": self.ids,
                "default_missing_payslip_ids": missing_payslips.ids,
            },
        }

    def _get_kpi_salary_rule_result(self, categories=None):
        """Compute the KPI salary rule payload from the confirmed KPI evaluation."""
        self.ensure_one()
        payload = {
            "amount": 0.0,
            "name": _("KPI Bonus"),
            "line": self.env["hr.kpi.evaluation.line"],
        }
        if not self._has_kpi_configuration():
            return payload

        evaluation_line = self._get_kpi_evaluation_line()
        if not evaluation_line:
            if self.kpi_evaluation_line_id:
                self.write({"kpi_evaluation_line_id": False})
            return payload

        if evaluation_line.payslip_id != self:
            evaluation_line.write({"payslip_id": self.id})
        if self.kpi_evaluation_line_id != evaluation_line:
            self.write({"kpi_evaluation_line_id": evaluation_line.id})

        payload.update(
            {
                "amount": evaluation_line.payout_value,
                "name": self._build_kpi_rule_name(evaluation_line),
                "line": evaluation_line,
            }
        )
        return payload

    def _build_kpi_rule_name(self, evaluation_line):
        """Build a readable KPI rule name for the current payslip."""
        self.ensure_one()
        if evaluation_line.contract_id.kpi_type == "fixed":
            return _("KPI Bonus - %(period)s", period=evaluation_line.evaluation_id.period_label)
        return _(
            "KPI Bonus - %(period)s (%(score)s%%)",
            period=evaluation_line.evaluation_id.period_label,
            score=evaluation_line.kpi_percentage,
        )

    def _sync_kpi_evaluation_states(self):
        self.mapped("kpi_evaluation_line_id.evaluation_id")._sync_state_from_lines()

    def _get_empty_payroll_moves(self):
        """Return draft payroll moves that contain no effective journal items.

        Payroll accounting skips move regeneration when a payslip already has a
        linked move. If the first generated move is empty, users get stuck with
        an unpostable draft entry forever. We treat draft moves without any
        non-zero journal items as broken placeholders and rebuild them.
        """
        self.ensure_one()
        move = self.move_id
        if not move or move.state != "draft":
            return self.env["account.move"]
        effective_lines = move.line_ids.filtered(
            lambda line: not line.display_type and (line.debit or line.credit)
        )
        return move if not effective_lines else self.env["account.move"]

    def _reset_empty_payroll_moves(self):
        """Detach and delete draft payroll moves that were generated empty."""
        empty_moves = self.env["account.move"]
        for payslip in self:
            empty_moves |= payslip._get_empty_payroll_moves()
        if not empty_moves:
            return
        impacted_payslips = empty_moves.mapped("payslip_ids")
        impacted_runs = impacted_payslips.mapped("payslip_run_id")
        impacted_payslips.write({"move_id": False})
        impacted_runs.filtered(lambda run: run.move_id in empty_moves).write({"move_id": False})
        empty_moves.unlink()

    def compute_sheet(self):
        payslips = self.filtered(lambda slip: slip.state in ("draft", "verify"))
        payslips._release_kpi_evaluation_lines()
        if payslips and not self.env.context.get("skip_missing_kpi_warning"):
            missing_payslips = payslips._get_missing_kpi_payslips()
            if missing_payslips:
                return payslips._open_missing_kpi_wizard(missing_payslips)
        return super().compute_sheet()

    def action_payslip_draft(self):
        evaluations = self.mapped("kpi_evaluation_line_id.evaluation_id")
        self._release_kpi_evaluation_lines()
        result = super().action_payslip_draft()
        evaluations._sync_state_from_lines()
        return result

    def action_payslip_cancel(self):
        evaluations = self.mapped("kpi_evaluation_line_id.evaluation_id")
        self._release_kpi_evaluation_lines()
        result = super().action_payslip_cancel()
        evaluations._sync_state_from_lines()
        return result

    def action_payslip_done(self):
        self._reset_empty_payroll_moves()
        result = super().action_payslip_done()
        self._sync_kpi_evaluation_states()
        return result

    def write(self, vals):
        result = super().write(vals)
        if "state" in vals:
            self._sync_kpi_evaluation_states()
        return result

    @api.model
    def _prepare_kpi_rule_values(self, structure):
        """Prepare KPI salary rule values for a payroll structure."""
        return {
            "name": _("KPI Bonus"),
            "code": RULE_CODE,
            "struct_id": structure.id,
            "sequence": 180,
            "category_id": self.env.ref("hr_payroll.ALW").id,
            "appears_on_payslip": True,
            "condition_select": "none",
            "amount_select": "code",
            "amount_python_compute": """
payload = payslip._get_kpi_salary_rule_result(categories)
result = payload['amount']
result_name = payload['name']
            """.strip(),
            "note": _(
                "<p>Automatically calculates the KPI bonus from the confirmed KPI evaluation "
                "that matches the payslip period.</p>"
            ),
        }

    @api.model
    def _sync_kpi_rules_to_structures(self):
        """Create the KPI salary rule on payroll structures missing it."""
        structures = self.env["hr.payroll.structure"].search([])
        if not structures:
            return
        existing_rules = self.env["hr.salary.rule"].search([("code", "=", RULE_CODE)])
        structures_with_rule = set(existing_rules.mapped("struct_id").ids)
        rule_values = [
            self._prepare_kpi_rule_values(structure)
            for structure in structures.filtered(lambda struct: struct.id not in structures_with_rule)
        ]
        if rule_values:
            self.env["hr.salary.rule"].create(rule_values)


class HrPayslipLine(models.Model):
    _inherit = "hr.payslip.line"

    accounting_description = fields.Char(
        string="Description",
        help="Description used on the generated accounting journal items.",
    )
