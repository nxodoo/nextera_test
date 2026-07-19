from odoo import api, fields, models


class HrLeaveType(models.Model):
    _inherit = "hr.leave.type"

    hide_from_employee = fields.Boolean(
        string="Hide From Employee",
        help="Hide this time off type from non-HR employees in employee-facing time off screens.",
    )

    def _search(self, domain, offset=0, limit=None, order=None):
        """Hide configured leave types only in flows that explicitly request it."""
        if self.env.context.get("hide_employee_leave_types"):
            domain = list(domain) + [("hide_from_employee", "=", False)]
        return super()._search(domain, offset=offset, limit=limit, order=order)

    @api.model
    def get_hidden_allocation_data_request(self, target_date=None):
        """Return only hidden leave types for the dashboard side rail."""
        allocation_data = super().get_allocation_data_request(
            target_date=target_date,
            hidden_allocations=True,
        )
        leave_type_ids = [leave_type_id for _, _, _, leave_type_id in allocation_data]
        hidden_type_ids = set(
            self.browse(leave_type_ids).filtered(lambda leave_type: leave_type.hide_from_employee).ids
        )
        return [
            allocation_line
            for allocation_line in allocation_data
            if allocation_line[3] in hidden_type_ids
        ]

    @api.model
    def get_allocation_data_request(self, target_date=None, hidden_allocations=True):
        """Hide employee-hidden leave types from the main dashboard cards."""
        allocation_data = super().get_allocation_data_request(
            target_date=target_date,
            hidden_allocations=hidden_allocations,
        )
        if not self.env.context.get("from_dashboard"):
            return allocation_data

        leave_type_ids = [leave_type_id for _, _, _, leave_type_id in allocation_data]
        hidden_type_ids = set(
            self.browse(leave_type_ids).filtered(lambda leave_type: leave_type.hide_from_employee).ids
        )
        return [
            allocation_line
            for allocation_line in allocation_data
            if allocation_line[3] not in hidden_type_ids
        ]
