from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


QUARTERLY_MONTH_OPTIONS = [("mar_jun_sep_dec", "3, 6, 9, 12"), ("apr_jul_oct_jan", "4, 7, 10, 1"), ("may_aug_nov_feb", "5, 8, 11, 2")]
QUARTERLY_MONTHS_BY_CYCLE = {"mar_jun_sep_dec": (3, 6, 9, 12), "apr_jul_oct_jan": (4, 7, 10, 1), "may_aug_nov_feb": (5, 8, 11, 2)}


class HrContract(models.Model):
    _inherit = "hr.contract"

    kpi_type = fields.Selection(
        [
            ("percentage", "Percentage"),
            ("fixed", "Fixed Amount"),
        ],
        string="KPI Type",
        default="percentage",
        tracking=True,
    )
    kpi_value = fields.Float(
        string="KPI Value",
        digits=(16, 2),
        tracking=True,
        help=(
            "Variable salary component defined on the contract. "
            "When the KPI type is Percentage, this value is a percentage of the wage. "
            "When the KPI type is Fixed Amount, this value is the fixed KPI amount."
        ),
    )
    kpi_frequency = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
        ],
        string="KPI Frequency",
        default="monthly",
        tracking=True,
    )
    quarterly_kpi_months = fields.Selection(
        QUARTERLY_MONTH_OPTIONS,
        string="Quarterly KPI Months",
        required=True,
        default="mar_jun_sep_dec",
        tracking=True,
        help="The months in which a quarterly KPI is calculated.",
    )
    has_kpi_configuration = fields.Boolean(
        string="Has KPI Configuration",
        compute="_compute_has_kpi_configuration",
        store=True,
    )

    @api.depends("kpi_type", "kpi_value", "kpi_frequency", "quarterly_kpi_months")
    def _compute_has_kpi_configuration(self):
        for contract in self:
            contract.has_kpi_configuration = bool(
                contract.kpi_type and contract.kpi_frequency and contract.kpi_value > 0
            )

    @api.model
    def _get_kpi_period_bounds_for_frequency(self, target_date, frequency, quarterly_months=False):
        """Return the KPI period, or no period when a quarterly KPI is not due."""
        target_date = fields.Date.to_date(target_date)
        period_end = fields.Date.end_of(target_date, "month")
        if frequency != "quarterly":
            return fields.Date.start_of(target_date, "month"), period_end
        due_months = QUARTERLY_MONTHS_BY_CYCLE.get(quarterly_months or "mar_jun_sep_dec", QUARTERLY_MONTHS_BY_CYCLE["mar_jun_sep_dec"])
        if target_date.month not in due_months:
            return False, False
        return fields.Date.start_of(target_date - relativedelta(months=2), "month"), period_end

    def _is_kpi_due_for_date(self, target_date):
        """Return whether this contract has a KPI calculation due on a date."""
        self.ensure_one()
        period_start, _period_end = self._get_kpi_period_bounds_for_frequency(target_date, self.kpi_frequency, self.quarterly_kpi_months)
        return bool(period_start)

    @api.model
    def default_get(self, fields_list):
        """Default contract department and job position from the selected employee."""
        values = super().default_get(fields_list)
        employee_id = values.get("employee_id") or self.env.context.get("default_employee_id")
        if not employee_id:
            return values
        employee = self.env["hr.employee"].browse(employee_id)
        if "department_id" in fields_list and employee.department_id and not values.get("department_id"):
            values["department_id"] = employee.department_id.id
        if "job_id" in fields_list and employee.job_id and not values.get("job_id"):
            values["job_id"] = employee.job_id.id
        return values

    @api.onchange("employee_id")
    def _onchange_employee_id_sync_contract_profile_fields(self):
        """Keep contract department and job aligned with the selected employee profile."""
        for contract in self:
            employee = contract.employee_id
            contract.department_id = employee.department_id
            if employee.job_id:
                contract.job_id = employee.job_id

    @api.model_create_multi
    def create(self, vals_list):
        """Persist employee department/job defaults when contracts are created."""
        prepared_vals_list = []
        for vals in vals_list:
            prepared_vals = dict(vals)
            employee_id = prepared_vals.get("employee_id")
            if employee_id:
                employee = self.env["hr.employee"].browse(employee_id)
                if employee.department_id and not prepared_vals.get("department_id"):
                    prepared_vals["department_id"] = employee.department_id.id
                if employee.job_id and not prepared_vals.get("job_id"):
                    prepared_vals["job_id"] = employee.job_id.id
            prepared_vals_list.append(prepared_vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        """Keep contract department aligned with the employee profile on updates."""
        if "employee_id" not in vals:
            return super().write(vals)

        employee = self.env["hr.employee"].browse(vals["employee_id"])
        synced_vals = dict(vals)
        synced_vals["department_id"] = employee.department_id.id or False
        if employee.job_id and not synced_vals.get("job_id"):
            synced_vals["job_id"] = employee.job_id.id
        return super().write(synced_vals)
