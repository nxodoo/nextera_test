# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    """ Extend account.move to link with custody requests. """

    _inherit = "account.move"

    # Add a Many2one field to link to the custody request

    custody_request_id = fields.Many2one(
        'custody.request',
        string="Custody Request",
        ondelete='set null',
        index=True,
    )

    def action_open_custody_payment_wizard(self):
        """ Open the custody payment wizard for the current bill. """
        self.ensure_one()

        return {
            'name': "Custody Payment",
            'type': 'ir.actions.act_window',
            'res_model': 'custody.bill.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bill_id': self.id,
            }
        }
