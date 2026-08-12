# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployeeDocumentType(models.Model):
    """Optional per-type destination, e.g. contracts and IDs in separate folders."""

    _inherit = "hr.employee.document.type"

    documents_folder_id = fields.Many2one(
        "documents.document",
        string="Documents Folder",
        domain="[('type', '=', 'folder')]",
        help="Where files of this type are filed in the Documents app. "
             "Leave empty to use the default folder from Settings.",
    )
