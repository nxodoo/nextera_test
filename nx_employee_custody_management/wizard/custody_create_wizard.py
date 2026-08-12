# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class CustodyCreateWizard(models.TransientModel):
    """Popup shown when creating a new custody request (money or asset)."""

    _name = "custody.create.wizard"
    _description = "Create Custody Request Wizard"

    employee_id = fields.Many2one('hr.employee', string="Employee", required=True)
    custody_type = fields.Selection([
        ('money', 'Money Custody'),
        ('asset', 'Asset Custody'),
    ], string="Custody Type", default='money', required=True)
    date = fields.Date(string="Request Date", default=fields.Date.context_today, required=True)
    is_temporary = fields.Boolean(string="Temporary Custody")

    def action_create_request(self):
        self.ensure_one()
        request = self.env['custody.request'].create({
            'employee_id': self.employee_id.id,
            'custody_type': self.custody_type,
            'date': self.date,
            'is_temporary': self.is_temporary,
        })
        return {
            'name': _('Custody Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'custody.request',
            'res_id': request.id,
            'view_mode': 'form',
            'target': 'current',
        }
