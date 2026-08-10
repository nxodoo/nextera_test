# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployeeDocumentType(models.Model):
    """Catalog of employee document types managed by HR in Configuration.

    Each type can carry applicability rules (gender / department / job / company)
    so the required-document checklist generated on each employee only contains
    the documents that actually apply to that employee.
    """
    _name = "hr.employee.document.type"
    _description = "Employee Document Type"
    _order = "sequence, name"

    name = fields.Char(string="Document Type", required=True, translate=True)
    code = fields.Char(string="Code")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Company",
        default=lambda self: self.env.company)

    mandatory = fields.Boolean(
        string="Mandatory", default=True,
        help="Mandatory documents are counted towards compliance and generate "
             "'missing' alerts when not uploaded.")
    expiry_required = fields.Boolean(
        string="Has Expiry Date",
        help="If enabled, the document is considered expired once the expiry "
             "date is reached.")
    expiry_alert_days = fields.Integer(
        string="Expiry Alert (days)", default=30,
        help="A document is flagged as 'Expiring Soon' this many days before "
             "its expiry date.")

    # ── Applicability rules ────────────────────────────────────────────────
    applies_to_gender = fields.Selection(
        [("all", "All"), ("male", "Male"), ("female", "Female")],
        string="Applies To (Gender)", default="all", required=True)
    department_ids = fields.Many2many(
        "hr.department", string="Departments",
        help="Leave empty to apply to every department.")
    job_ids = fields.Many2many(
        "hr.job", string="Job Positions",
        help="Leave empty to apply to every job position.")

    description = fields.Text(string="Description")

    def _is_applicable_to(self, employee):
        """Return True if this document type is required for ``employee``."""
        self.ensure_one()
        if self.applies_to_gender != "all" and employee.gender != self.applies_to_gender:
            return False
        if self.department_ids and employee.department_id not in self.department_ids:
            return False
        if self.job_ids and employee.job_id not in self.job_ids:
            return False
        if self.company_id and employee.company_id and self.company_id != employee.company_id:
            return False
        return True

    @api.model
    def _types_for_employee(self, employee):
        """Return the recordset of document types applicable to ``employee``."""
        types = self.search([])
        return types.filtered(lambda t: t._is_applicable_to(employee))
