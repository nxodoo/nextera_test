# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrEmployeeDocument(models.Model):
    """A single document instance attached to an employee.

    HR sees one line per required document type (auto-generated from the
    applicable types) and uploads the file for each. Extra ad-hoc documents
    can also be added manually.
    """
    _name = "hr.employee.document"
    _description = "Employee Document"
    _order = "sequence, document_type_id"
    _rec_name = "document_type_id"

    employee_id = fields.Many2one(
        "hr.employee", string="Employee", required=True,
        ondelete="cascade", index=True)
    document_type_id = fields.Many2one(
        "hr.employee.document.type", string="Document Type",
        required=True, ondelete="restrict")
    sequence = fields.Integer(related="document_type_id.sequence", store=True)

    company_id = fields.Many2one(
        related="employee_id.company_id", store=True, string="Company")
    department_id = fields.Many2one(
        related="employee_id.department_id", store=True, string="Department")

    mandatory = fields.Boolean(related="document_type_id.mandatory", store=True)
    expiry_required = fields.Boolean(related="document_type_id.expiry_required")

    document_file = fields.Binary(string="File", attachment=True)
    document_filename = fields.Char(string="File Name")
    reference = fields.Char(string="Reference / No.")
    issue_date = fields.Date(string="Issue Date")
    expiry_date = fields.Date(string="Expiry Date")
    notes = fields.Text(string="Notes")

    state = fields.Selection(
        [("missing", "Missing"),
         ("complete", "Complete"),
         ("expiring", "Expiring Soon"),
         ("expired", "Expired")],
        string="Status", compute="_compute_state", store=True)

    _sql_constraints = [
        ("uniq_employee_type",
         "unique(employee_id, document_type_id)",
         "This document type already exists for the employee."),
    ]

    @api.depends("document_file", "expiry_date", "expiry_required",
                 "document_type_id.expiry_required",
                 "document_type_id.expiry_alert_days")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.document_file:
                rec.state = "missing"
                continue
            expiry = rec.expiry_date
            if (rec.document_type_id.expiry_required or rec.expiry_required) and expiry:
                if expiry < today:
                    rec.state = "expired"
                    continue
                alert_days = rec.document_type_id.expiry_alert_days or 0
                if alert_days and (expiry - today).days <= alert_days:
                    rec.state = "expiring"
                    continue
            rec.state = "complete"

    @api.constrains("issue_date", "expiry_date")
    def _check_dates(self):
        for rec in self:
            if rec.issue_date and rec.expiry_date and rec.expiry_date < rec.issue_date:
                raise ValidationError(
                    "The expiry date cannot be earlier than the issue date.")
