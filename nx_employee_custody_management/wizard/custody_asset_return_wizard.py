# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang


class CustodyAssetReturnWizard(models.TransientModel):
    """Return assets held under an employee custody.

    For every returned asset the wizard shows what the asset actually cost
    (original value), what it was worth when it was handed over, what it is
    worth now (current book value) and how much depreciation was posted while
    it was out. A deduction can be charged back to the employee - by default
    when the asset comes back after its expiration date, or whenever it is
    flagged as lost / damaged.
    """

    _name = "custody.asset.return.wizard"
    _description = "Return Asset Custody Wizard"

    custody_id = fields.Many2one(
        'custody.request', string="Custody Request", required=True, readonly=True,
    )
    company_currency_id = fields.Many2one(
        'res.currency', related='custody_id.company_currency_id',
    )
    date = fields.Date(string="Return Date", default=fields.Date.context_today, required=True)
    line_ids = fields.One2many(
        'custody.asset.return.wizard.line', 'wizard_id', string="Assets to Return",
    )
    total_original_value = fields.Monetary(
        string="Total Original Value",
        compute="_compute_totals",
        currency_field='company_currency_id',
    )
    total_book_value = fields.Monetary(
        string="Total Book Value Now",
        compute="_compute_totals",
        currency_field='company_currency_id',
    )
    total_depreciation = fields.Monetary(
        string="Total Depreciated in Custody",
        compute="_compute_totals",
        currency_field='company_currency_id',
    )
    deduction_total = fields.Monetary(
        string="Total Deduction",
        compute="_compute_totals",
        currency_field='company_currency_id',
        help="Amount charged back to the employee.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        custody = self.env['custody.request'].browse(
            res.get('custody_id') or self.env.context.get('default_custody_id')
        )
        if custody:
            res['custody_id'] = custody.id
            lines = []
            for line in custody.asset_line_ids.filtered(lambda l: l.state == 'confirmed'):
                lines.append((0, 0, {
                    'asset_line_id': line.id,
                    'to_return': True,
                    'line_deduction': line.asset_id.book_value if line.is_expired else 0.0,
                }))
            res['line_ids'] = lines
        return res

    @api.depends('line_ids.to_return', 'line_ids.line_deduction',
                 'line_ids.original_value', 'line_ids.current_book_value',
                 'line_ids.depreciation_during_custody')
    def _compute_totals(self):
        for wiz in self:
            returned = wiz.line_ids.filtered('to_return')
            wiz.total_original_value = sum(returned.mapped('original_value'))
            wiz.total_book_value = sum(returned.mapped('current_book_value'))
            wiz.total_depreciation = sum(returned.mapped('depreciation_during_custody'))
            wiz.deduction_total = sum(returned.mapped('line_deduction'))

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    def action_confirm_return(self):
        self.ensure_one()
        to_return = self.line_ids.filtered('to_return')
        if not to_return:
            raise UserError(_("Select at least one asset to return."))

        early = to_return.filtered(
            lambda l: l.asset_line_id.handover_date and self.date < l.asset_line_id.handover_date
        )
        if early:
            raise UserError(_("The return date cannot be before the hand-over date."))

        move = self._create_return_entry(to_return)

        for line in to_return:
            line.asset_line_id.write({
                'state': 'returned',
                'return_date': self.date,
                'book_value_at_return': line.current_book_value,
                'deduction_amount': line.line_deduction,
            })

        custody = self.custody_id
        if all(l.state == 'returned' for l in custody.asset_line_ids):
            custody.state = 'entry_cancelled'

        custody.message_post(body=_(
            "%(count)s asset(s) returned on %(date)s. Deduction charged: %(amount)s.",
            count=len(to_return),
            date=self.date,
            amount=formatLang(
                self.env, self.deduction_total, currency_obj=self.company_currency_id
            ),
        ))

        if move:
            return {
                'type': 'ir.actions.act_window',
                'name': _("Custody Return Entry"),
                'res_model': 'account.move',
                'res_id': move.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {'type': 'ir.actions.act_window_close'}

    def _create_return_entry(self, return_lines):
        """Post the return entry.

        Per asset, the hand-over transfer is reversed at its original amount:
            Dr  Fixed Asset Account          (book value at hand-over)
            Cr  Assets Under Custody Account

        When a deduction is charged to the employee, it is booked on top:
            Dr  Custody Deduction Account    (deduction)
            Cr  Custody Recovery Account
        """
        config = self.custody_id._get_asset_custody_settings()
        currency = self.company_currency_id
        partner = self.custody_id.employee_id.work_contact_id
        move_lines = []

        for line in return_lines:
            asset_line = line.asset_line_id
            handover_value = asset_line.book_value_at_handover
            if not currency.is_zero(handover_value):
                label = _("Custody return - %s") % asset_line.asset_id.display_name
                move_lines += [
                    (0, 0, {
                        'name': label,
                        'account_id': asset_line.asset_account_id.id,
                        'partner_id': partner.id if partner else False,
                        'debit': handover_value,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': label,
                        'account_id': config['custody_account_id'],
                        'partner_id': partner.id if partner else False,
                        'debit': 0.0,
                        'credit': handover_value,
                    }),
                ]

            deduction = line.line_deduction
            if currency.is_zero(deduction):
                continue
            if not (config['deduction_account_id'] and config['recovery_account_id']):
                raise UserError(_(
                    "A deduction is charged but the Custody Deduction Account and/or "
                    "the Custody Recovery Account are not configured in Settings > Custody."))
            label = _("Custody deduction - %s") % asset_line.asset_id.display_name
            move_lines += [
                (0, 0, {
                    'name': label,
                    'account_id': config['deduction_account_id'],
                    'partner_id': partner.id if partner else False,
                    'debit': deduction,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': label,
                    'account_id': config['recovery_account_id'],
                    'partner_id': partner.id if partner else False,
                    'debit': 0.0,
                    'credit': deduction,
                }),
            ]

        if not move_lines:
            return self.env['account.move']

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': config['journal_id'],
            'date': self.date,
            'ref': _("Asset Custody Return - %s") % self.custody_id.name,
            'custody_request_id': self.custody_id.id,
            'line_ids': move_lines,
        })
        move.action_post()
        return move


class CustodyAssetReturnWizardLine(models.TransientModel):
    _name = "custody.asset.return.wizard.line"
    _description = "Return Asset Custody Wizard Line"

    wizard_id = fields.Many2one(
        'custody.asset.return.wizard', required=True, ondelete='cascade',
    )
    company_currency_id = fields.Many2one('res.currency', related='wizard_id.company_currency_id')
    asset_line_id = fields.Many2one(
        'custody.asset.line', string="Custody Line", required=True,
    )
    asset_id = fields.Many2one(related='asset_line_id.asset_id', string="Asset")
    acquisition_date = fields.Date(related='asset_line_id.acquisition_date', string="Acquisition Date")
    handover_date = fields.Date(related='asset_line_id.handover_date', string="Hand-over Date")
    expiration_date = fields.Date(related='asset_line_id.expiration_date', string="Expiration Date")
    is_expired = fields.Boolean(related='asset_line_id.is_expired', string="Overdue")
    remaining_period = fields.Char(related='asset_line_id.remaining_period', string="Remaining")

    original_value = fields.Monetary(
        related='asset_line_id.original_value',
        string="Original Value",
        currency_field='company_currency_id',
    )
    book_value_at_handover = fields.Monetary(
        related='asset_line_id.book_value_at_handover',
        string="Book Value at Hand-over",
        currency_field='company_currency_id',
    )
    current_book_value = fields.Monetary(
        related='asset_line_id.current_book_value',
        string="Book Value Now",
        currency_field='company_currency_id',
    )
    depreciation_during_custody = fields.Monetary(
        related='asset_line_id.depreciation_during_custody',
        string="Depreciated in Custody",
        currency_field='company_currency_id',
    )
    posted_depreciation_count = fields.Integer(
        related='asset_line_id.posted_depreciation_count',
        string="Posted Entries",
    )
    value_lost = fields.Monetary(
        string="Value Drop",
        compute="_compute_value_lost",
        currency_field='company_currency_id',
        help="Book value at hand-over minus book value now.",
    )

    to_return = fields.Boolean(string="Return", default=True)
    lost_or_damaged = fields.Boolean(
        string="Lost / Damaged",
        help="Charge the current book value back to the employee.",
    )
    line_deduction = fields.Monetary(
        string="Deduction",
        currency_field='company_currency_id',
        help="Amount charged back to the employee. Suggested when the asset is "
             "returned late or flagged as lost / damaged - editable.",
    )

    @api.depends('book_value_at_handover', 'current_book_value')
    def _compute_value_lost(self):
        for line in self:
            line.value_lost = line.book_value_at_handover - line.current_book_value

    @api.onchange('to_return', 'lost_or_damaged')
    def _onchange_suggest_deduction(self):
        for line in self:
            if not line.to_return:
                line.line_deduction = 0.0
            elif line.lost_or_damaged or line.is_expired:
                line.line_deduction = line.current_book_value
            else:
                line.line_deduction = 0.0

    @api.constrains('line_deduction')
    def _check_deduction(self):
        for line in self:
            if line.line_deduction < 0:
                raise ValidationError(_("The deduction cannot be negative."))

    def action_open_depreciation_entries(self):
        self.ensure_one()
        return self.asset_line_id.action_open_depreciation_entries()
