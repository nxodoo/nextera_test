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

    def _is_worked_amount_based(self):
        """Return whether pay comes from worked time instead of the wage field.

        Timesheet and hourly contracts are paid ``hours x hourly cost``, and the
        "Both" source stores a daily wage, so in those cases the payslip worked
        days carry the real salary. Standard contracts are paid their wage.
        """
        self.ensure_one()
        return self.wage_type == "hourly" or self.work_entry_source in ("timesheet", "both")

    def _get_kpi_hourly_rate(self):
        """Return the value of one worked hour for this contract.

        Timesheet contracts are paid ``hours x employee hourly cost``, so their
        ``wage`` field carries no meaning for the KPI base.
        """
        self.ensure_one()
        if not self._is_worked_amount_based():
            return 0.0
        get_timesheet_cost = getattr(self, "_get_timesheet_hourly_cost", None)
        if get_timesheet_cost and self.work_entry_source == "timesheet":
            hourly_cost = get_timesheet_cost()
            if hourly_cost:
                return hourly_cost
        return self.hourly_wage or getattr(self.employee_id, "hourly_cost", 0.0) or 0.0

    def _get_kpi_period_payslips(self, date_from, date_to):
        """Return one payslip per pay period covered by the KPI period.

        Draft duplicates for the same period would otherwise inflate the KPI
        base, so the most advanced payslip of each period wins.
        """
        self.ensure_one()
        payslips = self.env["hr.payslip"].search(
            [
                ("contract_id", "=", self.id),
                ("state", "in", ("draft", "verify", "done", "paid")),
                ("date_from", ">=", date_from),
                ("date_to", "<=", date_to),
            ]
        )
        state_rank = {"paid": 0, "done": 1, "verify": 2, "draft": 3}
        selected = {}
        for payslip in payslips.sorted(lambda slip: (state_rank.get(slip.state, 9), -slip.id)):
            selected.setdefault((payslip.date_from, payslip.date_to), payslip)
        return self.env["hr.payslip"].browse([slip.id for slip in selected.values()])

    def _get_kpi_period_hours(self, date_from, date_to):
        """Return the paid hours worked during the KPI period."""
        self.ensure_one()
        get_timesheet_hours = getattr(self, "_get_timesheet_hours_total", None)
        if get_timesheet_hours and self.work_entry_source == "timesheet":
            return get_timesheet_hours(date_from, date_to)
        worked_days = self._get_kpi_period_payslips(date_from, date_to).mapped("worked_days_line_ids")
        return sum(worked_days.filtered(lambda line: line.is_paid).mapped("number_of_hours"))

    def _get_kpi_period_month_count(self, date_from, date_to):
        """Return how many months the KPI period spans (1 monthly, 3 quarterly)."""
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        if not date_from or not date_to:
            return 0
        return max(1, (date_to.year - date_from.year) * 12 + date_to.month - date_from.month + 1)

    def _get_kpi_base_amount(self, date_from, date_to):
        """Return the salary earned over the KPI period.

        This is the amount a percentage KPI applies to. Standard contracts use
        their wage, one month at a time. Worked-time contracts use the salary
        they actually earned: the payslip worked days when payroll already ran,
        then hours x hourly rate.
        """
        self.ensure_one()
        if not date_from or not date_to:
            return 0.0

        month_count = self._get_kpi_period_month_count(date_from, date_to)
        if not self._is_worked_amount_based():
            return self.wage * month_count

        payslip_amount = sum(
            self._get_kpi_period_payslips(date_from, date_to).mapped("worked_days_line_ids").mapped("amount")
        )
        if payslip_amount:
            return payslip_amount

        hourly_rate = self._get_kpi_hourly_rate()
        if hourly_rate:
            return self._get_kpi_period_hours(date_from, date_to) * hourly_rate

        return self.wage * month_count

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
