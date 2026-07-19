from datetime import date

from odoo import fields, models
from odoo.tools.float_utils import float_round

from odoo.addons.resource.models.utils import HOURS_PER_DAY


class HrEmployeeBase(models.AbstractModel):
    _inherit = "hr.employee.base"

    def _compute_allocation_count(self):
        """Exclude hidden leave types from employee smart-button allocation totals."""
        current_date = date.today()
        data = self.env["hr.leave.allocation"]._read_group(
            [
                ("employee_id", "in", self.ids),
                ("holiday_status_id.active", "=", True),
                ("holiday_status_id.requires_allocation", "=", "yes"),
                ("holiday_status_id.hide_from_employee", "=", False),
                ("state", "=", "validate"),
                ("date_from", "<=", current_date),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", current_date),
            ],
            ["employee_id"],
            ["__count", "number_of_days:sum"],
        )
        grouped_results = {employee.id: (count, days) for employee, count, days in data}
        for employee in self:
            count, days = grouped_results.get(employee.id, (0, 0))
            employee.allocation_count = float_round(days, precision_digits=2)
            employee.allocations_count = count

    def _compute_allocation_remaining_display(self):
        """Exclude hidden leave types from employee smart-button balance displays."""
        current_date = date.today()
        allocations = self.env["hr.leave.allocation"].search(
            [
                ("employee_id", "in", self.ids),
                ("holiday_status_id.hide_from_employee", "=", False),
            ]
        )
        leaves_taken = self._get_consumed_leaves(allocations.holiday_status_id)[0]
        for employee in self:
            employee_remaining_leaves = 0
            employee_max_leaves = 0
            for leave_type in leaves_taken[employee]:
                if (
                    leave_type.requires_allocation == "no"
                    or not leave_type.show_on_dashboard
                    or not leave_type.active
                    or leave_type.hide_from_employee
                ):
                    continue
                for allocation in leaves_taken[employee][leave_type]:
                    if allocation and allocation.date_from <= current_date and (not allocation.date_to or allocation.date_to >= current_date):
                        virtual_remaining_leaves = leaves_taken[employee][leave_type][allocation]["virtual_remaining_leaves"]
                        employee_remaining_leaves += (
                            virtual_remaining_leaves
                            if leave_type.request_unit in ["day", "half_day"]
                            else virtual_remaining_leaves / (employee.resource_calendar_id.hours_per_day or HOURS_PER_DAY)
                        )
                        employee_max_leaves += allocation.number_of_days
            employee.allocation_remaining_display = "%g" % float_round(employee_remaining_leaves, precision_digits=2)
            employee.allocation_display = "%g" % float_round(employee_max_leaves, precision_digits=2)
