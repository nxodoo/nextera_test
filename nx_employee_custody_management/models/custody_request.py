import calendar

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CustodyRequest(models.Model):
    """Model for managing employee custody requests."""

    _name = "custody.request"
    _description = "Custody Request"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = "name"

    #-------------------------------------------
    # Fields
    #-------------------------------------------
    active = fields.Boolean(string="Active",default=True)
    custody_type = fields.Selection([
        ('money', 'Money Custody'),
        ('asset', 'Asset Custody'),
    ], string="Custody Type", default='money', required=True, tracking=True)
    name = fields.Char(string="Sequence", required=True, copy=False, readonly=True, default="New")
    name_rec = fields.Char(string="Custody Name", compute="_computed_name")
    date = fields.Date(string="Request Date", default=fields.Date.context_today)
    employee_id = fields.Many2one('hr.employee', string="Custody Holder", required=True)
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    amount = fields.Float(string="Amount")

    # -- Asset custody --
    asset_line_ids = fields.One2many(
        'custody.asset.line',
        'custody_id',
        string="Custody Asset Lines",
        copy=False,
    )
    asset_line_count = fields.Integer(
        string="Assets",
        compute="_compute_asset_totals",
    )
    asset_total_original_value = fields.Monetary(
        string="Total Original Value",
        compute="_compute_asset_totals",
        currency_field='company_currency_id',
    )
    asset_total_book_value = fields.Monetary(
        string="Total Book Value",
        compute="_compute_asset_totals",
        currency_field='company_currency_id',
    )
    asset_total_depreciation = fields.Monetary(
        string="Depreciated During Custody",
        compute="_compute_asset_totals",
        currency_field='company_currency_id',
    )
    entry_id = fields.Many2one('account.move', string="Accounting Entry", copy=False)
    entry_state = fields.Selection(related='entry_id.state', string="Entry State", store=True)
    entry_ids = fields.One2many(
        'account.move',
        'custody_request_id',
        string="Accounting Entries",
        copy=False,
    )
    amount_manager = fields.Float(string="Amount Approved")
    total_taken = fields.Float(
        string="Total Custody",
        compute="_compute_total_taken",
    )
    total_payment = fields.Float(
        string="Total Payment",
        compute="_compute_total_payment",
    )

    balance = fields.Float(compute="_computed_balance", string="Balance")
    custody_account_id = fields.Many2one(
        'account.account',
        string="Custody Account",
        compute="_compute_custody_account_id",
        store=True,
    )
    is_temporary = fields.Boolean(
        string="Temporary Custody",
        help="Check this if the custody is temporary",
        default=False
    )

    is_refill = fields.Boolean(
        string="Is Refill",
        help="Check this if the custody is a refill",
        default=False
    )

    payment_journal_id = fields.Many2one('account.journal', string="Payment Journal",
                                         domain="[('type', 'in', ('cash', 'bank'))]")
    journal_ids = fields.Many2many(
        'account.journal',
        string="Available Journals",
        compute='_compute_journal_ids',
    )
    approve_by = fields.Many2one('res.users', string="Approved By")
    approve_date = fields.Datetime(string="Approval Date")
    refused_by = fields.Many2one('res.users', string="Refused By")
    refused_date = fields.Datetime(string="Refused Date")
    move_line_ids = fields.One2many(
        'account.move.line',
        compute='_compute_move_line_ids',
        string="Custody Journal Items",
    )
    txn_date_from = fields.Date(string="From", copy=False)
    txn_date_to = fields.Date(string="To", copy=False)
    total_debit = fields.Monetary(
        string="Total Debit",
        compute='_compute_txn_totals',
        currency_field='company_currency_id',
    )
    total_credit = fields.Monetary(
        string="Total Credit",
        compute='_compute_txn_totals',
        currency_field='company_currency_id',
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        string="Company Currency",
        related='company_id.currency_id',
        store=True,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('refill', 'Refill'),
        ('to_approve', 'Sent to Approve'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('entry_created', 'Entry Created'),
        ('entry_cancelled', 'Entry Cancelled'),
    ], string="Status", default='draft', tracking=True)

    note = fields.Text(string="Note")

    #-------------------------------------------
    # Action Methods
    #-------------------------------------------
    def action_submit_to_approve(self):
        for rec in self:
            rec.state = 'to_approve'
            group = self.env.ref('nx_employee_custody_management.group_custody_approval')
            if group:
                users = group.users
                for user in users:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=user.id,
                        note="Custody request submitted for approval"
                    )

    def action_approve(self):
        for rec in self:
            rec.state = 'approved'
            rec.approve_by = self.env.user
            rec.approve_date = fields.Datetime.now()
            if rec.create_uid:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=rec.create_uid.id,
                    note=f"Your custody request {rec.name} has been approved."
                )

    def action_refuse(self):
        for rec in self:
            rec.state = 'refused'
            rec.refused_by = self.env.user
            rec.refused_date = fields.Datetime.now()
            if rec.create_uid:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=rec.create_uid.id,
                    note=f"Your custody request {rec.name} has been refused."
                )

    def action_refill(self):
        for rec in self:
            rec.state = 'refill'
            rec.amount = 0.0

    def action_return_custody(self):
        """Open wizard to return custody amount (money) or assets."""
        self.ensure_one()
        if self.custody_type == 'asset':
            return {
                'name': _('Return Asset Custody'),
                'type': 'ir.actions.act_window',
                'res_model': 'custody.asset.return.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_custody_id': self.id},
            }
        return {
            'name': 'Return Custody',
            'type': 'ir.actions.act_window',
            'res_model': 'custody.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_custody_id': self.id,
                'default_balance': self.balance,
            }
        }

    def action_create_entry(self):
        """Create accounting entry for the custody request."""

        for rec in self:
            if rec.state not in ['draft','refill']:
                raise UserError("Only Draft or Refill requests can create accounting entries.")

            # --- Asset custody: transfer the asset value to the custody account ---
            if rec.custody_type == 'asset':
                rec._confirm_asset_custody()
                continue

            param = self.env['ir.config_parameter'].sudo()

            if self.is_temporary:
                custody_journal = param.get_param(
                    'nx_employee_custody_management.custody_journal_temporary_id'
                )
            else:
                custody_journal = param.get_param(
                    'nx_employee_custody_management.custody_journal_permanent_id'
                )

            custody_journal_id = int(custody_journal) if custody_journal else False

            if not custody_journal_id:
                raise UserError("Please configure Custody Journal in Settings.")

            move = self.env['account.move'].create({
                'journal_id': custody_journal_id,
                'date': rec.date,
                'ref': rec.name,
                'custody_request_id': rec.id,
                'line_ids': [
                    (0, 0, {
                        'account_id': rec.custody_account_id.id,
                        'partner_id': rec.employee_id.work_contact_id.id if rec.employee_id.work_contact_id else False,
                        'debit': (rec.amount),
                        'credit': 0,
                        'name': 'Custody Payment',
                    }),
                    (0, 0, {
                        'account_id': rec.payment_journal_id.default_account_id.id if rec.payment_journal_id else False,
                        'partner_id': False,
                        'debit': 0,
                        'credit': (rec.amount),
                        'name': 'Custody Payment',
                    })
                ]
            })
            move.action_post()
            rec.entry_id = move
            rec.state = 'entry_created'

    #-------------------------------------------
    # Asset Custody
    #-------------------------------------------
    @api.model
    def _get_asset_custody_settings(self):
        """Read (and validate) the asset custody accounting configuration."""
        param = self.env['ir.config_parameter'].sudo()
        journal_id = param.get_param('nx_employee_custody_management.custody_asset_journal_id')
        custody_account_id = param.get_param('nx_employee_custody_management.custody_asset_account_id')
        deduction_account_id = param.get_param('nx_employee_custody_management.custody_deduction_account_id')
        recovery_account_id = param.get_param('nx_employee_custody_management.custody_asset_recovery_account_id')

        if not (journal_id and custody_account_id):
            raise UserError(_(
                "Please configure the Asset Custody Journal and the Assets Under "
                "Custody Account in Settings > Custody."))

        return {
            'journal_id': int(journal_id),
            'custody_account_id': int(custody_account_id),
            'deduction_account_id': int(deduction_account_id) if deduction_account_id else False,
            'recovery_account_id': int(recovery_account_id) if recovery_account_id else False,
        }

    def _confirm_asset_custody(self):
        """Freeze the book value of each asset and post the custody transfer.

        Dr  Assets Under Employee Custody   (book value at hand-over)
        Cr  Fixed Asset Account of the asset
        """
        self.ensure_one()

        lines = self.asset_line_ids.filtered(lambda l: l.state == 'draft')
        if not lines:
            raise UserError(_("Add at least one asset line before confirming."))

        missing = lines.filtered(lambda l: not l.asset_account_id)
        if missing:
            raise UserError(_(
                "The following assets have no fixed asset account: %s",
                ", ".join(missing.mapped('asset_id.display_name'))))

        config = self._get_asset_custody_settings()
        partner = self.employee_id.work_contact_id
        move_lines = []

        for line in lines:
            book_value = line.asset_id.book_value
            line.write({
                'book_value_at_handover': book_value,
                'state': 'confirmed',
            })
            if self.company_currency_id.is_zero(book_value):
                continue
            label = _("Custody hand-over - %s") % line.asset_id.display_name
            move_lines += [
                (0, 0, {
                    'name': label,
                    'account_id': config['custody_account_id'],
                    'partner_id': partner.id if partner else False,
                    'debit': book_value,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': label,
                    'account_id': line.asset_account_id.id,
                    'partner_id': partner.id if partner else False,
                    'debit': 0.0,
                    'credit': book_value,
                }),
            ]

        if move_lines:
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': config['journal_id'],
                'date': self.date or fields.Date.context_today(self),
                'ref': _("Asset Custody Hand-over - %s") % self.name,
                'custody_request_id': self.id,
                'line_ids': move_lines,
            })
            move.action_post()
            self.entry_id = move

        self.state = 'entry_created'
        self.message_post(body=_(
            "%s asset(s) handed over to %s.",
            len(lines), self.employee_id.display_name))

    def action_open_asset_depreciation_entries(self):
        """All posted depreciation entries booked while the assets were out."""
        self.ensure_one()
        moves = self.env['account.move']
        for line in self.asset_line_ids:
            moves |= line._get_custody_depreciation_moves()
        if not moves:
            raise UserError(_("No posted depreciation entry found for the custody period."))
        action = self.env['ir.actions.actions']._for_xml_id('account.action_move_journal_line')
        action['domain'] = [('id', 'in', moves.ids)]
        action['context'] = {'create': False}
        action['target'] = 'current'
        return action

    def action_reverse_entry(self):
        self.ensure_one()

        if not self.entry_id:
            raise UserError(_("No accounting entry to reverse."))

        if self.entry_id.state != 'posted':
            raise UserError(_("Only posted entries can be reversed."))

        reversal = self.entry_id._reverse_moves(
            default_values_list=[{
                'date': fields.Date.context_today(self),
                'ref': _('Reversal of %s') % self.entry_id.name,
                'custody_request_id': self.id,
            }],
            cancel=False
        )
        if reversal:
            self.entry_ids = [(4, reversal.id)]
            self.entry_id = reversal
            self.state = 'entry_cancelled'

    def action_open_entry(self):
        entries = self.entry_ids

        if not entries:
            raise UserError(_("No Accounting Entry linked to this custody request."))

        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_journal_line")

        if len(entries) == 1:
            action['res_id'] = entries.id
            action['views'] = [[self.env.ref('account.view_move_form').id, 'form']]
        else:
            action['domain'] = [('id', 'in', entries.ids)]
            action['views'] = [
                [self.env.ref('account.view_move_tree').id, 'list'],
                [self.env.ref('account.view_move_form').id, 'form']
            ]

        action['target'] = 'current'
        return action

    def action_open_journal_items(self):
        self.ensure_one()

        if not self.custody_account_id or not self.employee_id.work_contact_id:
            raise UserError(_("No custody account or employee partner found."))

        lines = self.move_line_ids

        if not lines:
            raise UserError(_("No journal items found for this custody."))

        action = self.env['ir.actions.actions']._for_xml_id(
            'account.action_account_moves_all'
        )

        if len(lines) == 1:
            action.update({
                'res_id': lines.id,
                'views': [(self.env.ref('account.view_move_line_form').id, 'form')],
            })
        else:
            action.update({
                'domain': [('id', 'in', lines.ids)],
                'views': [
                    (self.env.ref('account.view_move_line_tree').id, 'list'),
                    (self.env.ref('account.view_move_line_form').id, 'form'),
                ],
            })

        return action

    #-------------------------------------------
    # Constraints
    #-------------------------------------------

    @api.constrains('employee_id', 'custody_account_id')
    def _check_employee_custody_account(self):
        """Ensure that the combination of employee and custody account is unique."""

        for rec in self:
            if rec.custody_type == 'asset':
                continue
            custody_account = rec.env['custody.request'].sudo().search([
                ('employee_id', '=', rec.employee_id.id),
                ('custody_account_id', '=', rec.custody_account_id.id),
                ('custody_type', '=', 'money'),
                ('id', '!=', rec.id)
            ], limit=1)
            if custody_account:
                raise UserError(
                    _("The selected employee and custody account is already linked in another custody record."))

    @api.constrains('amount')
    def _check_amount(self):
        """Ensure that the requested amount is greater than zero when sent for approval."""
        for rec in self:
            if rec.custody_type == 'asset':
                continue
            if rec.amount <= 0 and rec.state == 'draft':
                raise UserError(_("Requested amount must be greater than zero."))

    # @api.constrains('amount_manager', 'state')
    # def _check_amount_manager(self):
    #     """Ensure that the approved amount is greater than zero when approved."""
    #     for rec in self:
    #         if rec.amount_manager <= 0 and rec.state == 'approved':
    #             raise UserError(_("Approved amount must be greater than zero."))

    #-------------------------------------------
    # Compute Methods
    #-------------------------------------------
    @api.depends('employee_id', 'custody_account_id')
    def _computed_balance(self):
        """Compute the balance of the custody account for the employee."""
        for rec in self:
            lines = rec.env['account.move.line'].sudo().search([
                ('account_id', '=', rec.custody_account_id.id),
                ('partner_id', '=', rec.employee_id.work_contact_id.id),
                ("parent_state", "=", "posted")])
            if lines:
                rec.balance = sum(lines.mapped('debit')) - sum(lines.mapped('credit'))
            else:
                rec.balance = 0.0

    @api.depends('is_temporary')
    def _compute_custody_account_id(self):
        """Compute custody account based on the type of custody."""

        for rec in self:
            param = self.env['ir.config_parameter'].sudo()
            if rec.is_temporary:
                custody_journal = param.get_param(
                    'nx_employee_custody_management.custody_journal_temporary_id'
                )
            else:
                custody_journal = param.get_param(
                    'nx_employee_custody_management.custody_journal_permanent_id'
                )

            custody_journal_id = int(custody_journal) if custody_journal else False

            if custody_journal_id:
                journal = self.env['account.journal'].browse(custody_journal_id)
                rec.custody_account_id = journal.default_account_id.id
            else:
                rec.custody_account_id = False

    @api.depends('custody_account_id', 'employee_id', 'txn_date_from', 'txn_date_to')
    def _compute_move_line_ids(self):
        """Compute journal items related to the custody account and employee."""
        for rec in self:
            if not rec.custody_account_id or not rec.employee_id.work_contact_id:
                rec.move_line_ids = False
                continue

            domain = [
                ('account_id', '=', rec.custody_account_id.id),
                ('partner_id', '=', rec.employee_id.work_contact_id.id),
                ('parent_state', '=', 'posted'),
            ]
            if rec.txn_date_from:
                domain.append(('date', '>=', rec.txn_date_from))
            if rec.txn_date_to:
                domain.append(('date', '<=', rec.txn_date_to))

            rec.move_line_ids = self.env['account.move.line'].search(domain)

    @api.depends('move_line_ids.debit', 'move_line_ids.credit')
    def _compute_txn_totals(self):
        """Sum the debit and credit of the displayed custody journal items."""
        for rec in self:
            rec.total_debit = sum(rec.move_line_ids.mapped('debit'))
            rec.total_credit = sum(rec.move_line_ids.mapped('credit'))

    def action_txn_filter_this_month(self):
        """Preset the date filter to the current calendar month."""
        today = fields.Date.context_today(self)
        last_day = calendar.monthrange(today.year, today.month)[1]
        for rec in self:
            rec.txn_date_from = today.replace(day=1)
            rec.txn_date_to = today.replace(day=last_day)
        return False

    def action_txn_filter_this_year(self):
        """Preset the date filter to the current calendar year."""
        today = fields.Date.context_today(self)
        for rec in self:
            rec.txn_date_from = today.replace(month=1, day=1)
            rec.txn_date_to = today.replace(month=12, day=31)
        return False

    def action_txn_filter_clear(self):
        """Clear the date filter so every custody journal item shows again."""
        for rec in self:
            rec.txn_date_from = False
            rec.txn_date_to = False
        return False

    @api.depends('employee_id')
    def _compute_journal_ids(self):
        """Compute available journals for custody requests."""
        self.ensure_one()

        param = self.env['ir.config_parameter'].sudo()
        custody_journal_temporary_id = param.get_param(
            'nx_employee_custody_management.custody_journal_temporary_id'
        )
        custody_journal_permanent_id = param.get_param(
            'nx_employee_custody_management.custody_journal_permanent_id'
        )
        journal_ids = [int(x) for x in [custody_journal_temporary_id, custody_journal_permanent_id] if
                       x and self.env['account.journal'].browse(int(x)).exists()]
        self.journal_ids = [(6, 0, journal_ids)]
            
    @api.depends('is_temporary')
    def _computed_name(self):
        """Compute custody name based on its type."""
        for rec in self:
            if rec.is_temporary:
                rec.name_rec = f"Temporary"
            else:
                rec.name_rec = f"Permanent"

    @api.depends('custody_account_id', 'employee_id')
    def _compute_total_taken(self):
        """Compute total amount taken from custody."""
        for rec in self:
            total = 0.0

            if not rec.custody_account_id or not rec.employee_id.work_contact_id:
                rec.total_taken = 0.0
                continue

            lines = self.env['account.move.line'].sudo().search([
                ('account_id', '=', rec.custody_account_id.id),
                ('partner_id', '=', rec.employee_id.work_contact_id.id),
                ('parent_state', '=', 'posted'),
                ('name', '=', 'Custody Payment'),
            ])

            for line in lines:
                total += (line.debit - line.credit)

            rec.total_taken = total

    @api.depends('asset_line_ids.original_value',
                 'asset_line_ids.current_book_value',
                 'asset_line_ids.depreciation_during_custody',
                 'asset_line_ids.state')
    def _compute_asset_totals(self):
        """Summarise the asset custody lines (count / original / book value)."""
        for rec in self:
            lines = rec.asset_line_ids
            rec.asset_line_count = len(lines)
            rec.asset_total_original_value = sum(lines.mapped('original_value'))
            rec.asset_total_book_value = sum(lines.mapped('current_book_value'))
            rec.asset_total_depreciation = sum(lines.mapped('depreciation_during_custody'))

    @api.depends('total_taken', 'balance')
    def _compute_total_payment(self):
        """Compute total payment made from custody."""
        for rec in self:
            rec.total_payment = rec.total_taken - rec.balance

    #-------------------------------------------
    # Override Methods
    #-------------------------------------------
    @api.model
    def create(self, vals):
        """Override create method to set sequence for custody request."""
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('custody.request') or 'New'
        return super(CustodyRequest, self).create(vals)

    def unlink(self):
        """Override unlink method to prevent deletion if there are accounting entries."""
        for record in self:
            if record.entry_id:
                raise UserError(_(
                    "You cannot delete this custody request because it has an accounting entry."
                ))
            if record.entry_ids:
                raise UserError(_(
                    "You cannot delete this custody request because it has accounting entries."
                ))

        return super(CustodyRequest, self).unlink()
