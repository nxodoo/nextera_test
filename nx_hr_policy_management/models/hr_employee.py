from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    years_of_service = fields.Integer(
        string="Years of Service",
        compute="_compute_leave_allowance_service_fields",
    )
    next_allowance_date = fields.Date(
        string="Next Allowance Date",
        compute="_compute_leave_allowance_service_fields",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create employees and apply matching one-time policy allocations."""
        employees = super().create(vals_list)
        employees._apply_employee_policy_allocations()
        return employees

    def write(self, vals):
        """Apply matching one-time policy allocations after relevant employee updates."""
        result = super().write(vals)
        if "gender" in vals or "company_id" in vals:
            self._apply_employee_policy_allocations()
        return result

    def _get_leave_allowance_active_contract(self):
        """Return the employee active running contract used for allowance eligibility."""
        self.ensure_one()
        return self.contract_id.filtered(lambda contract: contract.state == "open")[:1]

    def _get_leave_allowance_service_start_date(self):
        """Resolve the service start date from contract start or employee joining date."""
        self.ensure_one()
        active_contract = self._get_leave_allowance_active_contract()
        return active_contract.date_start or self.first_contract_date or False

    def _get_completed_service_years(self, reference_date=None):
        """Return the number of full service years completed at the reference date."""
        self.ensure_one()
        service_start_date = self._get_leave_allowance_service_start_date()
        if not service_start_date:
            return 0

        reference_date = reference_date or fields.Date.context_today(self)
        return max(relativedelta(reference_date, service_start_date).years, 0)

    def _get_next_leave_allowance_date(self):
        """Compute the next pending or upcoming service-anniversary allowance date."""
        self.ensure_one()
        service_start_date = self._get_leave_allowance_service_start_date()
        if not service_start_date:
            return False

        today = fields.Date.context_today(self)
        completed_service_years = self._get_completed_service_years(today)
        if completed_service_years < 1:
            return service_start_date + relativedelta(years=1)

        allocations = self.env["hr.leave.allocation"].search(
            [
                ("employee_id", "=", self.id),
                ("based_on_years_of_service", "=", True),
            ],
            order="service_year_number desc, service_anniversary_date desc",
            limit=1,
        )
        if allocations.service_year_number < completed_service_years:
            next_service_year = completed_service_years
        else:
            next_service_year = allocations.service_year_number + 1
        return service_start_date + relativedelta(years=next_service_year)

    @api.depends("contract_id", "contract_id.state", "contract_id.date_start", "first_contract_date")
    def _compute_leave_allowance_service_fields(self):
        today = fields.Date.context_today(self)
        for employee in self:
            service_start_date = employee._get_leave_allowance_service_start_date()
            if not service_start_date:
                employee.years_of_service = 0
                employee.next_allowance_date = False
                continue

            employee.years_of_service = employee._get_completed_service_years(today)
            employee.next_allowance_date = employee._get_next_leave_allowance_date()

    def _apply_employee_policy_allocations(self):
        """Create one-time employee policy allocations for matching employees."""
        rule_model = self.env["hr.leave.allowance.rule"]
        for employee in self.filtered(lambda current_employee: current_employee.gender == "female"):
            rule_model._ensure_employee_rule_allocation(employee)
