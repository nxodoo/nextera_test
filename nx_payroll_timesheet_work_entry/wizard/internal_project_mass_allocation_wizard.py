# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class InternalProjectMassAllocationWizard(models.TransientModel):
    """Bulk-create restricted internal project timesheet entries."""

    _name = "nx.internal.project.mass.allocation.wizard"
    _description = "Internal Project Mass Allocation"

    @api.model
    def _get_default_internal_project(self):
        """Return the preferred default project for mass internal allocations."""
        company = self.env.company
        if "internal_project_id" in company._fields and company.internal_project_id:
            return company.internal_project_id
        return self.env["nx.timesheet.internal.mixin"]._get_internal_project()

    @api.model
    def _get_mass_allocation_project_domain(self):
        """Allow restricted projects and the company's built-in internal project."""
        company = self.env.company
        internal_project = (
            company.internal_project_id
            if "internal_project_id" in company._fields and company.internal_project_id
            else self.env["project.project"]
        )
        domain = [("allow_timesheets", "=", True)]
        if internal_project:
            domain.extend(["|", ("restricted_internal_entries", "=", True), ("id", "=", internal_project.id)])
        else:
            domain.append(("restricted_internal_entries", "=", True))
        return domain

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        default=lambda self: self._get_default_internal_project(),
        domain=lambda self: self._get_mass_allocation_project_domain(),
    )
    task_id = fields.Many2one(
        "project.task",
        string="Task",
        domain="[('project_id', '=', project_id)]",
    )
    activity_type = fields.Char(string="Activity Type")
    description = fields.Char(string="Description", required=True)
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    number_of_hours = fields.Float(string="Number of Hours", required=True)
    department_id = fields.Many2one("hr.department", string="Team")
    employee_ids = fields.Many2many("hr.employee", string="Employees")

    @api.constrains("number_of_hours")
    def _check_number_of_hours(self):
        """Ensure allocated hours are always positive."""
        for wizard in self:
            if wizard.number_of_hours <= 0:
                raise ValidationError(_("Number of Hours must be greater than zero."))

    def _get_target_employees(self):
        """Return the active employees selected directly or through the chosen team."""
        self.ensure_one()
        employees = self.employee_ids.filtered("active")
        if self.department_id:
            employees |= self.env["hr.employee"].search([
                ("department_id", "=", self.department_id.id),
                ("active", "=", True),
            ])
        return employees

    @api.onchange("department_id")
    def _onchange_department_id(self):
        """Auto-fill employees with all active members of the selected team."""
        for wizard in self:
            if not wizard.department_id:
                continue
            team_employees = self.env["hr.employee"].search([
                ("department_id", "=", wizard.department_id.id),
                ("active", "=", True),
            ])
            wizard.employee_ids = [(6, 0, team_employees.ids)]

    @api.onchange("project_id")
    def _onchange_project_id(self):
        """Keep the selected task aligned with the selected project."""
        for wizard in self:
            if not wizard.project_id:
                wizard.task_id = False
                continue

            if wizard.task_id and wizard.task_id.project_id != wizard.project_id:
                wizard.task_id = False

            if wizard.task_id:
                continue

            company = wizard.env.company
            if (
                "internal_project_id" in company._fields
                and "leave_timesheet_task_id" in company._fields
                and company.internal_project_id == wizard.project_id
                and company.leave_timesheet_task_id
                and company.leave_timesheet_task_id.project_id == wizard.project_id
            ):
                wizard.task_id = company.leave_timesheet_task_id

    def _build_entry_description(self):
        """Build the final timesheet description shown on every created entry."""
        self.ensure_one()
        if self.activity_type and self.description:
            return "%s - %s" % (self.activity_type, self.description)
        return self.description or self.activity_type

    def _get_project_task(self, employee):
        """Resolve the task to use for the selected project and employee company."""
        self.ensure_one()
        if self.task_id:
            return self.task_id

        company = employee.company_id
        if (
            "internal_project_id" in company._fields
            and "leave_timesheet_task_id" in company._fields
            and company.internal_project_id == self.project_id
            and company.leave_timesheet_task_id
            and company.leave_timesheet_task_id.project_id == self.project_id
        ):
            return company.leave_timesheet_task_id
        return self.env["project.task"]

    def _is_allowed_mass_allocation_project(self):
        """Return whether the selected project is valid for internal mass allocation."""
        self.ensure_one()
        company = self.env.company
        internal_project = (
            company.internal_project_id
            if "internal_project_id" in company._fields
            else self.env["project.project"]
        )
        return bool(
            self.project_id
            and self.project_id.allow_timesheets
            and (
                self.project_id.restricted_internal_entries
                or (internal_project and self.project_id == internal_project)
            )
        )

    def _ensure_project_followers(self, employees):
        """Grant read visibility on followers-only projects to targeted employees."""
        self.ensure_one()
        if self.project_id.privacy_visibility != "followers":
            return

        partner_ids = employees.mapped("user_id.partner_id").ids
        if partner_ids:
            self.project_id.sudo().message_subscribe(partner_ids=partner_ids)

    def action_confirm(self):
        """Create one restricted internal timesheet line per targeted employee."""
        self.ensure_one()

        if not self.env.user.has_group(
            "nx_payroll_timesheet_work_entry.group_manage_internal_project_entries"
        ) and not self.env.user.has_group("base.group_system"):
            raise ValidationError(
                _("You are not allowed to create entries in the Internal Project.")
            )

        if not self._is_allowed_mass_allocation_project():
            raise ValidationError(
                _(
                    "The selected project must be a restricted internal project or "
                    "your company's standard internal project."
                )
            )

        employees = self._get_target_employees()
        if not employees:
            raise ValidationError(_("Please select at least one employee or one team."))

        self._ensure_project_followers(employees)

        description = self._build_entry_description()
        duplicate_domain = [
            ("project_id", "=", self.project_id.id),
            ("employee_id", "in", employees.ids),
            ("date", "=", self.date),
            ("name", "=", description),
        ]
        if self.env["account.analytic.line"].sudo().search_count(duplicate_domain):
            raise ValidationError(
                _("Some employees already have internal entries for this activity.")
            )

        vals_list = []
        for employee in employees:
            task = self._get_project_task(employee)
            vals_list.append({
                "employee_id": employee.id,
                "project_id": self.project_id.id,
                "task_id": task.id if task else False,
                "account_id": self.project_id.account_id.id,
                "company_id": employee.company_id.id,
                "user_id": employee.user_id.id,
                "date": self.date,
                "name": description,
                "mass_internal_entry": True,
                "unit_amount": self.number_of_hours,
            })

        created_lines = self.env["account.analytic.line"].sudo().with_context(
            bypass_timesheet_date_restriction=True,
        ).create(vals_list)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _(
                    "%(count)s internal timesheet line(s) created successfully.",
                    count=len(created_lines),
                ),
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
