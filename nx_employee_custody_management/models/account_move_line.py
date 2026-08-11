# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    """ Extend account.move.line to open the originating payment of a custody
    journal item straight from the custody request form. """

    _inherit = "account.move.line"

    nx_payment_journal_id = fields.Many2one(
        'account.journal',
        string="Payment Journal",
        compute='_compute_nx_payment_journal_id',
        help="The journal the originating payment was created from; "
             "falls back to this item's own journal when there is no payment.",
    )

    @api.depends('move_id.custody_request_id.payment_journal_id',
                 'payment_id.journal_id', 'journal_id')
    def _compute_nx_payment_journal_id(self):
        for line in self:
            # Prefer the funding journal chosen on the custody request that
            # created this entry (e.g. Bank), then the originating payment's
            # journal, and finally the line's own journal (e.g. cash returns).
            line.nx_payment_journal_id = (
                line.move_id.custody_request_id.payment_journal_id
                or line.payment_id.journal_id
                or line.journal_id
            )

    def action_open_custody_payment(self):
        """Open the vendor payment that created this journal item."""
        self.ensure_one()

        if not self.payment_id:
            raise UserError(_("This journal item is not linked to a payment."))

        return {
            'name': _("Payment"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'res_id': self.payment_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref('account.view_account_payment_form').id, 'form')],
            'target': 'current',
        }
