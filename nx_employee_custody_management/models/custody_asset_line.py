# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class CustodyAssetLine(models.Model):
    """A single accounting asset handed over to an employee under custody.

    The line pulls everything it needs from ``account.asset`` (original value,
    current book value, depreciation board) so the custody record never
    duplicates accounting data.  It only adds the custody-specific
    information: when the asset was handed over, for how long, and what its
    value was at hand-over versus at return.
    """

    _name = "custody.asset.line"
    _description = "Custody Asset Line"
    _order = "custody_id, id"

    custody_id = fields.Many2one(
        'custody.request',
        string="Custody Request",
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='custody_id.company_id',
        store=True,
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='custody_id.company_currency_id',
        string="Currency",
    )
    employee_id = fields.Many2one(
        'hr.employee',
        related='custody_id.employee_id',
        string="Custody Holder",
        store=True,
    )

    # -------------------------------------------------------------------------
    # THE ASSET
    # -------------------------------------------------------------------------
    asset_id = fields.Many2one(
        'account.asset',
        string="Asset",
        required=True,
        domain="[('state', 'in', ('open', 'paused')), "
               "('parent_id', '=', False), "
               "('company_id', '=', company_id)]",
        help="Fixed asset from Accounting that is handed over to the employee.",
    )
    asset_state = fields.Selection(related='asset_id.state', string="Asset Status")
    asset_group_id = fields.Many2one(related='asset_id.asset_group_id', string="Asset Group")
    asset_account_id = fields.Many2one(
        related='asset_id.account_asset_id',
        string="Fixed Asset Account",
    )
    asset_journal_id = fields.Many2one(related='asset_id.journal_id', string="Asset Journal")
    acquisition_date = fields.Date(related='asset_id.acquisition_date', string="Acquisition Date")
    original_value = fields.Monetary(
        related='asset_id.original_value',
        string="Original Value",
        currency_field='company_currency_id',
    )
    current_book_value = fields.Monetary(
        related='asset_id.book_value',
        string="Current Book Value",
        currency_field='company_currency_id',
    )
    depreciable_value = fields.Monetary(
        related='asset_id.value_residual',
        string="Depreciable Value",
        currency_field='company_currency_id',
    )
    salvage_value = fields.Monetary(
        related='asset_id.salvage_value',
        string="Not Depreciable Value",
        currency_field='company_currency_id',
    )
    depreciation_method = fields.Selection(related='asset_id.method', string="Depreciation Method")
    asset_duration = fields.Integer(
        related='asset_id.method_number',
        string="Asset Duration",
        help="Number of depreciation periods defined on the asset.",
    )
    asset_period = fields.Selection(
        related='asset_id.method_period',
        string="Period",
    )
    depreciation_start_date = fields.Date(
        related='asset_id.prorata_date',
        string="Depreciation Start",
    )
    asset_end_date = fields.Date(
        string="Asset End Date",
        compute="_compute_asset_end_date",
        help="End of the asset depreciation, derived from its own duration.",
    )

    # -------------------------------------------------------------------------
    # CUSTODY PERIOD
    # -------------------------------------------------------------------------
    handover_date = fields.Date(
        string="Hand-over Date",
        default=fields.Date.context_today,
        required=True,
    )
    expiration_date = fields.Date(
        string="Expiration Date",
        compute="_compute_expiration_date",
        store=True,
        readonly=False,
        help="Date the asset is expected back: the end of its depreciation, "
             "derived from the duration defined on the asset itself. "
             "You can still override it.",
    )
    is_expired = fields.Boolean(string="Overdue", compute="_compute_remaining_period")
    remaining_period = fields.Char(
        string="Remaining Period",
        compute="_compute_remaining_period",
    )

    # -------------------------------------------------------------------------
    # VALUE SNAPSHOTS
    # -------------------------------------------------------------------------
    book_value_at_handover = fields.Monetary(
        string="Book Value at Hand-over",
        currency_field='company_currency_id',
        readonly=True,
        copy=False,
        help="Book value of the asset frozen at the moment the custody was confirmed.",
    )
    return_date = fields.Date(string="Return Date", readonly=True, copy=False)
    book_value_at_return = fields.Monetary(
        string="Book Value at Return",
        currency_field='company_currency_id',
        readonly=True,
        copy=False,
    )
    depreciation_during_custody = fields.Monetary(
        string="Depreciated During Custody",
        compute="_compute_depreciation_during_custody",
        currency_field='company_currency_id',
        help="Posted depreciation between the hand-over date and the return "
             "date (or today while the asset is still out).",
    )
    deduction_amount = fields.Monetary(
        string="Deduction Charged",
        currency_field='company_currency_id',
        readonly=True,
        copy=False,
        help="Amount charged back to the employee when the asset was returned.",
    )

    # -------------------------------------------------------------------------
    # DEPRECIATION BOARD
    # -------------------------------------------------------------------------
    depreciation_move_ids = fields.One2many(
        related='asset_id.depreciation_move_ids',
        string="Depreciation Entries",
    )
    posted_depreciation_count = fields.Integer(
        string="Posted Entries",
        compute="_compute_depreciation_during_custody",
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'In Custody'),
        ('returned', 'Returned'),
    ], string="Status", default='draft', copy=False)

    note = fields.Char(string="Note")

    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    @api.depends('asset_id.method_number', 'asset_id.method_period',
                 'asset_id.prorata_date', 'asset_id.acquisition_date')
    def _compute_asset_end_date(self):
        """End of the asset's own depreciation schedule."""
        for line in self:
            asset = line.asset_id
            start = asset.prorata_date or asset.acquisition_date
            if not asset or not start or not asset.method_number:
                line.asset_end_date = False
                continue
            line.asset_end_date = start + relativedelta(
                months=asset.method_number * int(asset.method_period or 1)
            )

    @api.depends('asset_end_date', 'handover_date')
    def _compute_expiration_date(self):
        """The asset is expected back when its own duration runs out."""
        for line in self:
            end = line.asset_end_date
            if end and line.handover_date and end < line.handover_date:
                end = line.handover_date
            line.expiration_date = end or False

    @api.depends('expiration_date', 'state', 'return_date')
    def _compute_remaining_period(self):
        today = fields.Date.context_today(self)
        for line in self:
            if line.state == 'returned':
                line.is_expired = False
                line.remaining_period = _("Returned")
                continue
            if not line.expiration_date:
                line.is_expired = False
                line.remaining_period = _("No deadline")
                continue
            delta = (line.expiration_date - today).days
            if delta < 0:
                line.is_expired = True
                line.remaining_period = _("Overdue by %s day(s)") % abs(delta)
            else:
                line.is_expired = False
                years, days = divmod(delta, 365)
                months, days = divmod(days, 30)
                if years:
                    line.remaining_period = _("%(y)s year(s) %(m)s month(s) left") % {'y': years, 'm': months}
                elif months:
                    line.remaining_period = _("%(m)s month(s) %(d)s day(s) left") % {'m': months, 'd': days}
                else:
                    line.remaining_period = _("%s day(s) left") % days

    @api.depends('asset_id.depreciation_move_ids.state',
                 'asset_id.depreciation_move_ids.depreciation_value',
                 'handover_date', 'return_date')
    def _compute_depreciation_during_custody(self):
        for line in self:
            moves = line._get_custody_depreciation_moves()
            line.posted_depreciation_count = len(moves)
            line.depreciation_during_custody = sum(moves.mapped('depreciation_value'))

    def _get_custody_depreciation_moves(self):
        """Posted depreciation entries that fall inside the custody period."""
        self.ensure_one()
        if not self.asset_id or not self.handover_date:
            return self.env['account.move']
        end = self.return_date or fields.Date.context_today(self)
        return self.asset_id.depreciation_move_ids.filtered(
            lambda m: m.state == 'posted'
            and m.date
            and self.handover_date <= m.date <= end
        )

    # -------------------------------------------------------------------------
    # ONCHANGE / CONSTRAINTS
    # -------------------------------------------------------------------------
    @api.onchange('custody_id')
    def _onchange_custody_id(self):
        for line in self:
            if line.custody_id.date and not line.handover_date:
                line.handover_date = line.custody_id.date

    @api.constrains('asset_id', 'state')
    def _check_asset_not_already_in_custody(self):
        for line in self:
            if line.state == 'returned' or not line.asset_id:
                continue
            other = self.sudo().search([
                ('asset_id', '=', line.asset_id.id),
                ('state', '=', 'confirmed'),
                ('id', '!=', line.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "Asset %(asset)s is already under custody of %(employee)s (%(ref)s).",
                    asset=line.asset_id.display_name,
                    employee=other.employee_id.display_name,
                    ref=other.custody_id.name,
                ))

    @api.constrains('expiration_date', 'handover_date')
    def _check_dates(self):
        for line in self:
            if line.expiration_date and line.handover_date and line.expiration_date < line.handover_date:
                raise ValidationError(_("The expiration date cannot be before the hand-over date."))

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    def action_open_asset(self):
        self.ensure_one()
        if not self.asset_id:
            raise UserError(_("No asset linked to this line."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.asset_id.display_name,
            'res_model': 'account.asset',
            'res_id': self.asset_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_depreciation_entries(self):
        """Show the posted depreciation entries booked during the custody."""
        self.ensure_one()
        moves = self._get_custody_depreciation_moves()
        if not moves:
            raise UserError(_("No posted depreciation entry for this asset during the custody period."))
        action = self.env['ir.actions.actions']._for_xml_id('account.action_move_journal_line')
        action['domain'] = [('id', 'in', moves.ids)]
        action['context'] = {'create': False}
        action['target'] = 'current'
        return action
