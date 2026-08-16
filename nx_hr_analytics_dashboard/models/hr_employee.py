# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    document_ids = fields.One2many(
        "hr.employee.document", "employee_id", string="Documents")

    document_count = fields.Integer(
        compute="_compute_document_stats", string="Documents")
    document_required_count = fields.Integer(
        compute="_compute_document_stats", string="Required Documents")
    document_complete_count = fields.Integer(
        compute="_compute_document_stats", string="Complete Documents")
    document_missing_count = fields.Integer(
        compute="_compute_document_stats", string="Missing Documents")
    document_expired_count = fields.Integer(
        compute="_compute_document_stats", string="Expired Documents")
    document_compliance_rate = fields.Float(
        compute="_compute_document_stats", string="Document Compliance %")
    document_status = fields.Selection(
        [("complete", "Complete"),
         ("incomplete", "Incomplete"),
         ("expired", "Expired")],
        compute="_compute_document_stats", string="File Status", store=True)

    @api.depends("document_ids.state", "document_ids.mandatory")
    def _compute_document_stats(self):
        for emp in self:
            docs = emp.document_ids
            mandatory = docs.filtered("mandatory")
            required = len(mandatory)
            complete = len(mandatory.filtered(lambda d: d.state in ("complete", "expiring")))
            missing = len(mandatory.filtered(lambda d: d.state == "missing"))
            expired = len(mandatory.filtered(lambda d: d.state == "expired"))
            emp.document_count = len(docs)
            emp.document_required_count = required
            emp.document_complete_count = complete
            emp.document_missing_count = missing
            emp.document_expired_count = expired
            emp.document_compliance_rate = (
                (complete / required) * 100.0 if required else 100.0)
            if expired:
                emp.document_status = "expired"
            elif missing:
                emp.document_status = "incomplete"
            else:
                emp.document_status = "complete"

    def _sync_required_documents(self):
        """Ensure a document line exists for each applicable document type."""
        DocType = self.env["hr.employee.document.type"]
        Document = self.env["hr.employee.document"]
        for emp in self:
            applicable = DocType._types_for_employee(emp)
            existing = emp.document_ids.mapped("document_type_id")
            missing_types = applicable - existing
            for dtype in missing_types:
                Document.create({
                    "employee_id": emp.id,
                    "document_type_id": dtype.id,
                })
        return True

    def action_sync_required_documents(self):
        """Button: (re)generate the required-document checklist."""
        self._sync_required_documents()
        return True

    @api.model
    def action_generate_all_documents(self):
        """Backfill the checklist for every employee (server-action target).

        Lives here rather than in the server action's inline code so its
        notification text goes through the translation export.
        """
        employees = self.with_context(active_test=False).search([])
        employees._sync_required_documents()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Employee Documents"),
                "message": _("%s employees processed.") % len(employees),
                "type": "success",
                "sticky": False,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._sync_required_documents()
        return employees

    def write(self, vals):
        res = super().write(vals)
        # Re-evaluate applicability when a driver of the rules changes.
        if {"gender", "department_id", "job_id", "company_id"} & set(vals):
            self._sync_required_documents()
        return res
