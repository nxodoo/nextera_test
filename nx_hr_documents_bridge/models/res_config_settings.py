# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    nx_hr_documents_folder_id = fields.Many2one(
        "documents.document",
        string="HR Documents Folder",
        domain="[('type', '=', 'folder')]",
        config_parameter="nx_hr_documents_bridge.documents_folder_id",
        help="Default Documents-app folder for employee documents uploaded "
             "on the HR document checklist.",
    )
