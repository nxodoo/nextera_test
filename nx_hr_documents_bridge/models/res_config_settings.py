# -*- coding: utf-8 -*-
from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    nx_hr_documents_folder_id = fields.Many2one(
        "documents.document",
        string="HR Documents Folder",
        domain="[('type', '=', 'folder')]",
        config_parameter="nx_hr_documents_bridge.documents_folder_id",
        help="Default Documents-app folder for employee documents uploaded "
             "on the HR document checklist. Leave empty to use the company's "
             "standard HR workspace.",
    )

    def action_nx_file_existing_documents(self):
        """Back-fill: file documents that were uploaded before this module.

        The sync normally runs on create/write, so files uploaded earlier have
        no Documents entry. This sweeps them in one pass; already-filed
        documents are refreshed rather than duplicated.
        """
        self.ensure_one()
        pending = self.env["hr.employee.document"].search([
            ("document_file", "!=", False),
        ])
        pending._nx_sync_documents()
        filed = len(pending.filtered("documents_document_id"))
        skipped = len(pending) - filed
        message = _("%(filed)s document(s) filed into Documents.", filed=filed)
        if skipped:
            message += _(
                " %(skipped)s skipped — no folder could be resolved "
                "(set one above, or configure the company's HR workspace).",
                skipped=skipped,
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("HR Documents"),
                "message": message,
                "type": "success" if filed else "warning",
                "sticky": False,
            },
        }
