# -*- coding: utf-8 -*-
from odoo import models, fields, _, api
from odoo.exceptions import ValidationError


class ProjectProject(models.Model):
    _inherit = "project.project"

    restricted_internal_entries = fields.Boolean(
        string="Restricted Internal Entries",
        help=(
            "When enabled, only users with the Manage Internal Project Entries "
            "permission can create, edit, delete, or mass-allocate timesheets "
            "on this project."
        ),
    )

    def action_open_internal_mass_allocation_wizard(self):
        self.ensure_one()
        return {
            "name": _("Internal Project Mass Allocation"),
            "type": "ir.actions.act_window",
            "res_model": "nx.internal.project.mass.allocation.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_project_id": self.id,
            },
        }

