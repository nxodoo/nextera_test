from odoo import fields, models, _


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    kpi_evaluation_line_count = fields.Integer(
        string="KPI Evaluations",
        compute="_compute_kpi_evaluation_line_count",
    )

    def _compute_kpi_evaluation_line_count(self):
        grouped_data = self.env["hr.kpi.evaluation.line"].read_group(
            [("employee_id", "in", self.ids)],
            ["employee_id"],
            ["employee_id"],
        )
        counts = {item["employee_id"][0]: item["employee_id_count"] for item in grouped_data}
        for employee in self:
            employee.kpi_evaluation_line_count = counts.get(employee.id, 0)

    def action_view_kpi_evaluation_lines(self):
        """Open KPI history for the current employee."""
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "nx_hr_kpi_salary.action_hr_kpi_evaluation_line"
        )
        action["domain"] = [("employee_id", "=", self.id)]
        action["context"] = {
            "default_employee_id": self.id,
            "search_default_group_by_period": 1,
        }
        action["name"] = _("KPI Evaluations")
        return action
