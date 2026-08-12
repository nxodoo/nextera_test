# -*- coding: utf-8 -*-
from odoo import api, fields, models

FOLDER_PARAM = "nx_hr_documents_bridge.documents_folder_id"


class HrEmployeeDocument(models.Model):
    """File the uploaded HR document into a Documents workspace folder.

    The binary field on hr.employee.document stores its file as a private
    ir.attachment (res_field is set), which is why nothing appears in the
    Documents app. Here we mirror the file into a real documents.document
    record so it becomes browsable, searchable and shareable.
    """

    _inherit = "hr.employee.document"

    documents_document_id = fields.Many2one(
        "documents.document",
        string="Documents Entry",
        copy=False,
        readonly=True,
        help="The copy of this file filed in the Documents app.",
    )

    # ------------------------------------------------------------------
    # Folder resolution
    # ------------------------------------------------------------------
    def _nx_target_folder(self):
        """Per-type folder wins; otherwise the global default from Settings."""
        self.ensure_one()
        folder = self.document_type_id.documents_folder_id
        if folder:
            return folder
        raw = self.env["ir.config_parameter"].sudo().get_param(FOLDER_PARAM)
        if not raw:
            return self.env["documents.document"]
        return self.env["documents.document"].browse(int(raw)).exists()

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------
    def _nx_sync_documents(self):
        """Create, update or remove the Documents entry to match the file."""
        Document = self.env["documents.document"].sudo()
        for rec in self:
            # File cleared → drop the Documents entry rather than leaving a
            # stale copy behind.
            if not rec.document_file:
                if rec.documents_document_id:
                    rec.documents_document_id.sudo().unlink()
                    rec.documents_document_id = False
                continue

            folder = rec._nx_target_folder()
            if not folder:
                # No folder configured yet — nothing to file into. The upload
                # itself is unaffected.
                continue

            employee = rec.employee_id
            name = rec.document_filename or "%s - %s" % (
                rec.document_type_id.name or "Document",
                employee.name or "",
            )
            vals = {
                "name": name,
                "datas": rec.document_file,
                "folder_id": folder.id,
                "partner_id": employee.work_contact_id.id or False,
                "res_model": "hr.employee.document",
                "res_id": rec.id,
            }
            if rec.documents_document_id:
                rec.documents_document_id.sudo().write(vals)
            else:
                rec.documents_document_id = Document.create(vals)

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered("document_file")._nx_sync_documents()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Only touch Documents when something it mirrors actually changed.
        if {"document_file", "document_filename", "document_type_id",
                "employee_id"} & set(vals):
            self._nx_sync_documents()
        return res

    def unlink(self):
        documents = self.mapped("documents_document_id")
        res = super().unlink()
        if documents:
            documents.sudo().unlink()
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_open_documents_entry(self):
        self.ensure_one()
        if not self.documents_document_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.documents_document_id.name,
            "res_model": "documents.document",
            "res_id": self.documents_document_id.id,
            "view_mode": "form",
            "target": "current",
        }
