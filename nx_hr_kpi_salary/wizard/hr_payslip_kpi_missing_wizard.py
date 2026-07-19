from odoo import api, fields, models, _


class HrPayslipKpiMissingWizard(models.TransientModel):
    _name = "hr.payslip.kpi.missing.wizard"
    _description = "Missing KPI Evaluation Warning"

    payslip_ids = fields.Many2many(
        "hr.payslip",
        "hr_payslip_kpi_missing_wizard_payslip_rel",
        "wizard_id",
        "payslip_id",
        string="Payslips",
        required=True,
    )
    missing_payslip_ids = fields.Many2many(
        "hr.payslip",
        "hr_payslip_kpi_missing_wizard_missing_rel",
        "wizard_id",
        "payslip_id",
        string="Missing KPI Payslips",
        required=True,
    )
    missing_employee_names = fields.Text(
        string="Employees",
        compute="_compute_missing_employee_names",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "payslip_ids" in fields_list and self.env.context.get("default_payslip_ids"):
            values["payslip_ids"] = [fields.Command.set(self.env.context["default_payslip_ids"])]
        if "missing_payslip_ids" in fields_list and self.env.context.get("default_missing_payslip_ids"):
            values["missing_payslip_ids"] = [
                fields.Command.set(self.env.context["default_missing_payslip_ids"])
            ]
        return values

    def _compute_missing_employee_names(self):
        for wizard in self:
            names = wizard.missing_payslip_ids.mapped("employee_id.name")
            wizard.missing_employee_names = "\n".join(names)

    def action_proceed(self):
        """Continue payroll computation and treat missing KPI as zero."""
        self.ensure_one()
        result = self.payslip_ids.with_context(skip_missing_kpi_warning=True).compute_sheet()
        return result or {"type": "ir.actions.act_window_close"}

    def action_cancel(self):
        return {"type": "ir.actions.act_window_close"}
