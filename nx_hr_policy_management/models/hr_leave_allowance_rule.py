import logging
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class HrLeaveAllowanceRule(models.Model):
    _name = "hr.leave.allowance.rule"
    _description = "Leave Allowance Rule"
    _order = "min_years_of_service, id"

    name = fields.Char(string="Rule Name", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    leave_type_id = fields.Many2one(
        "hr.leave.type",
        string="Leave Type",
        required=True,
        domain=[("requires_allocation", "=", "yes")],
    )
    rule_scope = fields.Selection(
        [
            ("service_years", "Years of Service"),
            ("employee_condition", "Employee Condition"),
        ],
        string="Rule Scope",
        required=True,
        default="service_years",
    )
    gender = fields.Selection(
        [
            ("male", "Male"),
            ("female", "Female"),
        ],
        string="Gender",
    )
    min_years_of_service = fields.Integer(
        string="From Years of Service",
        required=True,
        default=0,
    )
    max_years_of_service = fields.Integer(
        string="To Years of Service",
        help="Leave empty when the rule has no upper limit.",
    )
    allocated_days = fields.Float(
        string="Allocated Days",
        required=True,
        default=0.0,
    )
    auto_allocation = fields.Boolean(
        string="Auto Allocation",
        help="Automatically create an allocation when the employee matches this rule.",
    )
    active = fields.Boolean(string="Active", default=True)

    _sql_constraints = [
        (
            "check_allocated_days_positive",
            "CHECK(allocated_days > 0)",
            "Allocated days must be greater than zero.",
        ),
        (
            "check_min_years_non_negative",
            "CHECK(min_years_of_service >= 0)",
            "Minimum years of service must be zero or greater.",
        ),
    ]

    @api.constrains("min_years_of_service", "max_years_of_service", "leave_type_id", "company_id", "active")
    def _check_year_range(self):
        """Validate rule range integrity and prevent overlapping active rules."""
        for rule in self:
            if rule.rule_scope != "service_years":
                continue
            if rule.max_years_of_service and rule.max_years_of_service <= rule.min_years_of_service:
                raise ValidationError(_("The maximum years of service must be greater than the minimum years of service."))

            overlapping_rules = self.search(
                [
                    ("id", "!=", rule.id),
                    ("company_id", "=", rule.company_id.id),
                    ("leave_type_id", "=", rule.leave_type_id.id),
                    ("active", "=", True),
                ]
            )
            for candidate in overlapping_rules:
                candidate_max = candidate.max_years_of_service or float("inf")
                rule_max = rule.max_years_of_service or float("inf")
                if rule.min_years_of_service < candidate_max and candidate.min_years_of_service < rule_max:
                    raise ValidationError(
                        _(
                            "Active leave allowance rules cannot overlap for the same leave type and company."
                        )
                    )

    @api.constrains("rule_scope", "gender", "leave_type_id", "company_id", "active")
    def _check_employee_condition_uniqueness(self):
        """Prevent duplicate active employee-condition rules for the same leave type and company."""
        for rule in self.filtered(lambda current_rule: current_rule.rule_scope == "employee_condition" and current_rule.active):
            duplicate_rules = self.search(
                [
                    ("id", "!=", rule.id),
                    ("rule_scope", "=", "employee_condition"),
                    ("company_id", "=", rule.company_id.id),
                    ("leave_type_id", "=", rule.leave_type_id.id),
                    ("gender", "=", rule.gender),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if duplicate_rules:
                raise ValidationError(
                    _("Only one active employee-condition rule is allowed for the same leave type, company, and gender.")
                )

    def _matches_service_years(self, service_years):
        """Return whether the rule covers the given completed years of service."""
        self.ensure_one()
        if self.rule_scope != "service_years":
            return False
        if service_years < self.min_years_of_service:
            return False
        if not self.max_years_of_service:
            return True
        return service_years < self.max_years_of_service

    @api.model
    def _get_matching_rule(self, employee, service_years):
        """Return the active rule that matches the employee service duration."""
        return self.search(
            [
                ("company_id", "=", employee.company_id.id),
                ("active", "=", True),
                ("rule_scope", "=", "service_years"),
            ],
            order="min_years_of_service desc, id desc",
        ).filtered(lambda rule: rule._matches_service_years(service_years))[:1]

    @api.model
    def _get_matching_employee_rules(self, employee):
        """Return the active auto-allocation rules that match the employee attributes."""
        gender = employee.gender or False
        return self.search(
            [
                ("company_id", "=", employee.company_id.id),
                ("active", "=", True),
                ("auto_allocation", "=", True),
                ("rule_scope", "=", "employee_condition"),
                "|",
                ("gender", "=", False),
                ("gender", "=", gender),
            ],
            order="id desc",
        )

    @api.model
    def _get_next_due_anniversary_payload(self, employee, today):
        """Build the next due service-anniversary payload for the employee.

        The scheduler should create at most one pending annual allowance per run
        for each employee. This keeps the process reviewable and avoids bulk
        backfilling multiple historical allocations in one execution. For older
        employees, the scheduler targets the current completed service year.
        """
        service_start_date = employee._get_leave_allowance_service_start_date()
        if not service_start_date:
            return False

        completed_service_years = employee._get_completed_service_years(today)
        if completed_service_years < 1:
            return False

        last_generated_allocation = self.env["hr.leave.allocation"].search(
            [
                ("employee_id", "=", employee.id),
                ("based_on_years_of_service", "=", True),
            ],
            order="service_year_number desc, service_anniversary_date desc",
            limit=1,
        )
        next_service_year = completed_service_years
        if last_generated_allocation and last_generated_allocation.service_year_number >= completed_service_years:
            return False

        anniversary_date = service_start_date + relativedelta(years=next_service_year)
        if not anniversary_date or anniversary_date > today:
            return False

        return {
            "service_year_number": next_service_year,
            "service_anniversary_date": anniversary_date,
            "completed_years": next_service_year,
        }

    @api.model
    def _prepare_leave_allocation_values(self, employee, rule, payload):
        """Prepare a draftable allocation payload based on a matched leave allowance rule."""
        return {
            "name": _("%(leave_type)s Allowance - Years of Service", leave_type=rule.leave_type_id.name),
            "employee_id": employee.id,
            "holiday_status_id": rule.leave_type_id.id,
            "date_from": payload["service_anniversary_date"],
            "date_to": False,
            "number_of_days": rule.allocated_days,
            "number_of_days_display": rule.allocated_days,
            "policy_generation_type": "service_years",
            "based_on_years_of_service": True,
            "leave_allowance_rule_id": rule.id,
            "service_anniversary_date": payload["service_anniversary_date"],
            "service_year_number": payload["service_year_number"],
            "notes": _(
                "Automatically generated from the leave allowance rule for %(years)s completed year(s) of service.",
                years=payload["completed_years"],
            ),
        }

    @api.model
    def _prepare_employee_rule_allocation_values(self, employee, rule):
        """Prepare allocation values for one-time auto-allocation employee rules."""
        return {
            "name": _("%(leave_type)s Allowance - Employee Policy", leave_type=rule.leave_type_id.name),
            "employee_id": employee.id,
            "holiday_status_id": rule.leave_type_id.id,
            "date_from": fields.Date.context_today(self),
            "date_to": False,
            "number_of_days": rule.allocated_days,
            "number_of_days_display": rule.allocated_days,
            "policy_generation_type": "employee_rule",
            "leave_allowance_rule_id": rule.id,
            "notes": _("Automatically generated from the employee policy rule."),
        }

    @api.model
    def _allocation_exists(self, employee, payload, leave_type):
        """Check whether an allocation already exists for this employee service year."""
        return bool(
            self.env["hr.leave.allocation"].search_count(
                [
                    ("employee_id", "=", employee.id),
                    ("holiday_status_id", "=", leave_type.id),
                    ("based_on_years_of_service", "=", True),
                    ("service_year_number", "=", payload["service_year_number"]),
                ]
            )
        )

    @api.model
    def _employee_rule_allocation_exists(self, employee, rule):
        """Check whether an employee rule allocation already exists for the employee and leave type."""
        return bool(
            self.env["hr.leave.allocation"].search_count(
                [
                    ("employee_id", "=", employee.id),
                    ("holiday_status_id", "=", rule.leave_type_id.id),
                    ("leave_allowance_rule_id", "=", rule.id),
                ]
            )
        )

    @api.model
    def _ensure_employee_rule_allocation(self, employee):
        """Create a one-time auto-allocation when the employee matches an employee rule."""
        allocations = self.env["hr.leave.allocation"]
        for rule in self._get_matching_employee_rules(employee):
            if rule.gender and employee.gender != rule.gender:
                continue
            if self._employee_rule_allocation_exists(employee, rule):
                continue
            allocations |= self.env["hr.leave.allocation"].create(
                self._prepare_employee_rule_allocation_values(employee, rule)
            )
        return allocations

    @api.model
    def _eligible_employees_for_scheduler(self):
        """Return employees with active contracts in companies where the scheduler is enabled."""
        companies = self.env["res.company"].search(
            [
                ("leave_allowance_scheduler_enabled", "=", True),
                ("leave_allowance_scheduler_start_date", "!=", False),
            ]
        )
        if not companies:
            return self.env["hr.employee"]

        return self.env["hr.employee"].search(
            [
                ("company_id", "in", companies.ids),
                ("contract_id.state", "=", "open"),
            ]
        )

    @api.model
    def _cron_generate_leave_allowances(self):
        """Create time-off allocations from years-of-service rules for due employees."""
        today = fields.Date.context_today(self)
        allocation_model = self.env["hr.leave.allocation"]

        for employee in self._eligible_employees_for_scheduler():
            company = employee.company_id
            if not company.leave_allowance_scheduler_enabled:
                continue
            if not company.leave_allowance_scheduler_start_date or company.leave_allowance_scheduler_start_date > today:
                continue

            active_contract = employee._get_leave_allowance_active_contract()
            if not active_contract:
                continue

            payload = self._get_next_due_anniversary_payload(employee, today)
            if not payload:
                continue

            rule = self._get_matching_rule(employee, payload["completed_years"])
            if not rule:
                _logger.warning(
                    "No leave allowance rule matched employee %s for service year %s.",
                    employee.display_name,
                    payload["completed_years"],
                )
                continue
            if self._allocation_exists(employee, payload, rule.leave_type_id):
                continue

            allocation_model.create(
                self._prepare_leave_allocation_values(employee, rule, payload)
            )
