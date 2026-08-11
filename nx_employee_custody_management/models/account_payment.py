# -*- coding: utf-8 -*-
from email.policy import default

from odoo import api, models, fields

class AccountPayment(models.Model):
    """ Extend account.payment to handle payments made using employee custody. """

    _inherit = "account.payment"

    # Add fields to handle custody payments

    employee_id = fields.Many2one(
        'hr.employee',
        string="Custody Holder",
        help="Employee who owns the custody used for this payment."
    )

    custody_account_id = fields.Many2one(
        'account.account',
        string="Custody Account",
        help="Custody account used when paying vendor bills via custody."
    )

    is_custody_payment = fields.Boolean(
        string="Pay from Custody",
        help="Enable this if the payment is made using employee custody."
    )

    custody_account_ids = fields.Many2many(
        'account.account',
        string="Allowed Custody Accounts",
        compute="_compute_custody_account_ids",
        help="Accounts of the journals flagged as custody; used to filter "
             "the custody account selection.",
    )

    @api.depends('is_custody_payment')
    def _compute_custody_account_ids(self):
        custody_journals = self.env['account.journal'].search([
            ('is_custody', '=', True),
        ])
        accounts = custody_journals.default_account_id
        for payment in self:
            payment.custody_account_ids = accounts

    @api.onchange('journal_id')
    def _onchange_custody_journal_id(self):
        """ When a custody journal is picked, fill the custody account from it. """
        if self.is_custody_payment and self.journal_id.is_custody:
            self.custody_account_id = self.journal_id.default_account_id

    @api.onchange('custody_account_id')
    def _onchange_custody_account_id(self):
        """ When a custody account is picked, fill the journal that uses it. """
        if self.is_custody_payment and self.custody_account_id:
            journal = self.env['account.journal'].search([
                ('is_custody', '=', True),
                ('default_account_id', '=', self.custody_account_id.id),
            ], limit=1)
            if journal:
                self.journal_id = journal

    def _prepare_move_line_default_vals(self, write_off_line_vals=None, force_balance=None):
        """ Prepare the default values for the move lines of the payment's journal entry.
        If the payment is made using custody, create specific move lines for custody payment.
        """
        self.ensure_one()

        if self.is_custody_payment:
            write_off_line_vals = write_off_line_vals or []

            liquidity_amount_currency = -self.amount if self.payment_type == 'outbound' else self.amount
            liquidity_balance = self.currency_id._convert(
                liquidity_amount_currency,
                self.company_id.currency_id,
                self.company_id,
                self.date,
            )

            line_vals_list = [
                {
                    'name': self._get_aml_default_display_name_list()[0][1],
                    'date_maturity': self.date,
                    'amount_currency': liquidity_amount_currency,
                    'currency_id': self.currency_id.id,
                    'debit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                    'credit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                    'partner_id': self.employee_id.work_contact_id.id if self.employee_id else self.partner_id.id,
                    'account_id': self.custody_account_id.id,
                },
                {
                    'name': "Payment from Custody",
                    'date_maturity': self.date,
                    'amount_currency': -liquidity_amount_currency,
                    'currency_id': self.currency_id.id,
                    'debit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                    'credit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                    'partner_id': self.partner_id.id,
                    'account_id': self.destination_account_id.id,
                }
            ]

            return line_vals_list + write_off_line_vals

        return super(AccountPayment, self)._prepare_move_line_default_vals(write_off_line_vals, force_balance)