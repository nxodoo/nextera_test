from odoo import _, api, fields, models
from odoo.fields import Command
from odoo.exceptions import ValidationError


LOCKED_REQUEST_STATES = {'cancelled', 'rejected', 'expired'}


class HrIqamaFeeLine(models.Model):
    _name = 'hr.iqama.fee.line'
    _description = 'Residency/Visa Fee Line'
    _order = 'claim_date desc, id desc'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
        ondelete='cascade',
    )
    expense_type_id = fields.Many2one(
        'product.product',
        string='Expense Type',
        domain="[('can_be_expensed', '=', True)]",
    )
    claim_date = fields.Date(string='Claim Date')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    payment_date = fields.Date(
        string='Payment Date',
        compute='_compute_payment_date',
        store=True,
        readonly=True,
    )
    expense_id = fields.Many2one(
        'hr.expense',
        string='Expense',
        ondelete='set null',
        readonly=True,
        domain="[('iqama_request_id', '=', iqama_id)]",
    )
    expense_status = fields.Selection(
        related='expense_id.state',
        string='Status',
        readonly=True,
    )
    expense_description = fields.Char(
        related='expense_id.name',
        string='Description',
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        related='expense_id.employee_id',
        string='Employee',
        readonly=True,
    )
    paid_by = fields.Selection(
        related='expense_id.payment_mode',
        string='Paid By',
        readonly=True,
    )
    activity_ids = fields.One2many(
        related='expense_id.activity_ids',
        string='Activities',
        readonly=True,
    )
    activity_state = fields.Selection(
        related='expense_id.activity_state',
        string='Activity State',
        readonly=True,
    )
    activity_type_icon = fields.Char(
        related='expense_id.activity_type_icon',
        string='Activity Type Icon',
        readonly=True,
    )
    activity_exception_decoration = fields.Selection(
        related='expense_id.activity_exception_decoration',
        string='Activity Exception Decoration',
        readonly=True,
    )
    activity_exception_icon = fields.Char(
        related='expense_id.activity_exception_icon',
        string='Activity Exception Icon',
        readonly=True,
    )
    activity_summary = fields.Char(
        related='expense_id.activity_summary',
        string='Activity Summary',
        readonly=True,
    )
    analytic_distribution = fields.Json(
        related='expense_id.analytic_distribution',
        string='Analytic Distribution',
        readonly=True,
    )
    total_amount = fields.Monetary(
        related='expense_id.total_amount',
        string='Total',
        readonly=True,
        currency_field='currency_id',
    )

    def action_open_add_fees_wizard(self, *args):
        """Open the parent residency/visa fee wizard from the one2many control row."""
        iqama = self[:1].iqama_id
        if not iqama:
            iqama_id = (
                self.env.context.get('default_iqama_id')
                or self.env.context.get('active_id')
                or self.env.context.get('id')
            )
            iqama = self.env['hr.iqama'].browse(iqama_id)
        if not iqama:
            raise ValidationError(_('Unable to determine the residency/visa request for this action.'))
        return iqama.action_open_add_fees_wizard()

    def action_open_expense(self):
        """Open the linked expense record for the selected fee line."""
        self.ensure_one()
        if not self.expense_id:
            raise ValidationError(_('There is no linked expense for this fee line yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Expense'),
            'res_model': 'hr.expense',
            'view_mode': 'form',
            'res_id': self.expense_id.id,
            'target': 'current',
        }

    @api.depends(
        'expense_id',
        'expense_id.state',
        'expense_id.sheet_id.state',
        'expense_id.sheet_id.payment_state',
        'expense_id.sheet_id.account_move_ids.state',
        'expense_id.sheet_id.account_move_ids.payment_state',
        'expense_id.sheet_id.account_move_ids.date',
        'expense_id.sheet_id.account_move_ids.origin_payment_id.date',
    )
    def _compute_payment_date(self):
        """Use the real expense payment/posting date instead of a manual fee-line date."""
        for line in self:
            expense = line.expense_id
            if not expense:
                line.payment_date = False
                continue
            sheet = expense.sheet_id
            if not sheet:
                line.payment_date = False
                continue

            posted_moves = sheet.account_move_ids.filtered(lambda move: move.state == 'posted')
            posted_move_dates = posted_moves.mapped('date')
            payment_dates = posted_moves.mapped('origin_payment_id.date')
            effective_payment_state = sheet.payment_state

            if payment_dates:
                line.payment_date = max(payment_dates)
            elif effective_payment_state in ('paid', 'in_payment', 'partial') or sheet.state == 'done' or expense.state == 'done':
                line.payment_date = max(posted_move_dates or [sheet.accounting_date or False])
            else:
                line.payment_date = False

    def _prepare_linked_expense_vals(self):
        """Build grouped expense values from the residency/visa fee line.

        When the fee line already has an expense pre-assigned (set by the
        wizard), only fees belonging to that same expense are summed so that
        each batch has its own correct total rather than a running total of
        all fees ever added to the iqama request.
        """
        self.ensure_one()
        request_label = self.iqama_id.request_number or self.iqama_id.display_name or _('Residency/Visa Request')
        if self.expense_id:
            # Isolate totals to lines that belong to this specific expense.
            fee_lines = self.iqama_id.fee_line_ids.filtered(
                lambda fl: fl.expense_id == self.expense_id
                and fl.expense_type_id and fl.amount
                and fl.currency_id == self.currency_id
            )
        else:
            fee_lines = self.iqama_id.fee_line_ids.filtered(
                lambda fee_line: fee_line.expense_type_id and fee_line.amount and fee_line.currency_id == self.currency_id
            )
        total_amount = sum(fee_lines.mapped('amount'))
        claim_dates = fee_lines.mapped('claim_date')
        return {
            'name': _('Residency/Visa Fees - %s') % request_label,
            'product_id': self.expense_type_id.id,
            'date': max(claim_dates) if claim_dates else (self.claim_date or fields.Date.context_today(self)),
            'currency_id': self.currency_id.id,
            'total_amount': total_amount,
            'total_amount_currency': total_amount,
            'price_unit': total_amount,
            'quantity': 1.0,
            'employee_id': self.iqama_id.employee_id.id,
            'company_id': self.iqama_id.company_id.id,
            'iqama_request_id': self.iqama_id.id,
        }

    def _get_expense_account(self):
        """Return the expense account used by the linked product."""
        self.ensure_one()
        product = self.expense_type_id
        account = product.property_account_expense_id or product.categ_id.property_account_expense_categ_id
        if not account:
            raise ValidationError(
                _(
                    "Expense type '%(type)s' must have an expense account before it can create a linked expense line.",
                    type=product.display_name,
                )
            )
        return account

    def _get_or_create_expense_line_type(self):
        """Reuse or create an expense line type that mirrors the fee product."""
        self.ensure_one()
        line_type_model = self.env['hr.expense.line.type']
        account = self._get_expense_account()
        line_type_name = self.expense_type_id.display_name or _('Residency/Visa Fee')

        line_type = line_type_model.search([
            ('name', '=', line_type_name),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.iqama_id.company_id.id),
        ], limit=1)
        if line_type:
            return line_type

        return line_type_model.create({
            'name': line_type_name,
            'account_id': account.id if account else False,
            'active': True,
            'company_id': self.iqama_id.company_id.id,
            'note': _('Auto-created from residency/visa fee type.'),
        })

    def _prepare_linked_expense_line_vals(self):
        """Build a single detailed expense line that mirrors the fee line."""
        self.ensure_one()
        return {
            'expense_line_type_id': self._get_or_create_expense_line_type().id,
            'name': self.expense_type_id.display_name or _('Residency/Visa Fee'),
            'unit_amount': self.amount,
            'currency_id': self.currency_id.id,
            'iqama_fee_line_id': self.id,
        }

    def _get_grouped_expense(self):
        """Return the editable grouped expense that should hold this fee line.

        When all existing expenses are locked/submitted a new expense will be
        created by the caller, so we intentionally return an empty recordset
        in that case instead of a non-editable expense.
        """
        self.ensure_one()
        request_expenses = self.iqama_id.travel_expense_ids
        editable_expenses = request_expenses.filtered(lambda expense: expense.state in ('draft', 'reported') and expense.is_editable)

        if self.expense_id and self.expense_id in editable_expenses:
            return self.expense_id
        if editable_expenses:
            return editable_expenses[0]
        # No editable expense exists — return empty so the caller creates a new one.
        return self.env['hr.expense']

    def _cleanup_empty_expenses(self, expenses):
        """Delete editable grouped expenses that no longer contain detail lines."""
        removable_expenses = expenses.filtered(
            lambda expense: expense.iqama_request_id and not expense.expense_line_ids and expense.state in ('draft', 'reported') and expense.is_editable
        )
        if removable_expenses:
            removable_expenses.unlink()

    def _sync_linked_expense(self):
        """Create or update a single grouped expense with matching detail lines."""
        expense_line_model = self.env['hr.expense.line']
        for line in self:
            if not line.iqama_id.employee_id or not line.expense_type_id or not line.amount:
                continue

            expense = line._get_grouped_expense()
            expense_vals = line._prepare_linked_expense_vals()
            expense_line_vals = line._prepare_linked_expense_line_vals()
            linked_expense_line = expense_line_model.search([
                ('iqama_fee_line_id', '=', line.id),
            ], limit=1)
            previous_expense = linked_expense_line.expense_id if linked_expense_line else line.expense_id

            if expense and (expense.state in ('draft', 'reported') and expense.is_editable):
                # Happy path: write into the existing editable expense.
                expense.write(expense_vals)
                if linked_expense_line:
                    linked_expense_line.write({
                        **expense_line_vals,
                        'expense_id': expense.id,
                    })
                else:
                    expense.write({
                        'expense_line_ids': [Command.create(expense_line_vals)],
                    })
                line.expense_id = expense
                line._cleanup_empty_expenses(previous_expense.filtered(lambda grouped_expense: grouped_expense != expense))
                continue

            # No editable expense found (either none exists or all are locked/submitted).
            # Create a brand-new expense so the user can add further fee batches
            # even after a previous expense has already been submitted/approved.
            expense_vals['expense_line_ids'] = [Command.create(expense_line_vals)]
            line.expense_id = self.env['hr.expense'].create(expense_vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            iqama = self.env['hr.iqama'].browse(vals.get('iqama_id'))
            if iqama and iqama.state in LOCKED_REQUEST_STATES:
                raise ValidationError(_('You cannot modify fees for a locked residency/visa request.'))
        records = super().create(vals_list)
        records._sync_linked_expense()
        return records

    def write(self, vals):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify fees for a locked residency/visa request.'))
        result = super().write(vals)
        if {'expense_type_id', 'claim_date', 'amount', 'currency_id', 'iqama_id'} & set(vals):
            self._sync_linked_expense()
        return result

    def unlink(self):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify fees for a locked residency/visa request.'))
        expense_line_model = self.env['hr.expense.line']
        linked_expense_lines = expense_line_model.search([('iqama_fee_line_id', 'in', self.ids)])
        linked_expenses = linked_expense_lines.mapped('expense_id')
        editable_expenses = linked_expenses.filtered(lambda expense: expense.state in ('draft', 'reported') and expense.is_editable)
        if linked_expense_lines:
            linked_expense_lines.unlink()
        self._cleanup_empty_expenses(editable_expenses)
        return super().unlink()


class HrIqamaTimeline(models.Model):
    _name = 'hr.iqama.timeline'
    _description = 'Residency/Visa Timeline'
    _order = 'date desc, id desc'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
        ondelete='cascade',
    )
    title = fields.Char(string='Title', required=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    details = fields.Text(string='Details')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            iqama = self.env['hr.iqama'].browse(vals.get('iqama_id'))
            if iqama and iqama.state in LOCKED_REQUEST_STATES:
                raise ValidationError(_('You cannot modify the timeline for a locked residency/visa request.'))
        records = super().create(vals_list)
        for record in records:
            record.iqama_id.message_post(
                body='%s - %s - %s' % (
                    record.title,
                    record.date or '',
                    record.details or '',
                )
            )
        return records

    def write(self, vals):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify the timeline for a locked residency/visa request.'))
        return super().write(vals)

    def unlink(self):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify the timeline for a locked residency/visa request.'))
        return super().unlink()


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    iqama_request_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        ondelete='set null',
    )
    iqama_fee_line_id = fields.Many2one(
        'hr.iqama.fee.line',
        string='Residency/Visa Fee Line',
        ondelete='set null',
        copy=False,
        index=True,
    )

    def action_open_iqama_expense(self):
        """Open the selected grouped residency/visa expense."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Expense'),
            'res_model': 'hr.expense',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_remove_iqama_expense(self):
        """Remove the grouped expense and its linked residency/visa fee lines."""
        fee_lines = self.env['hr.iqama.fee.line'].search([('expense_id', 'in', self.ids)])
        if fee_lines:
            fee_lines.unlink()
        removable_expenses = self.filtered(lambda expense: expense.iqama_request_id and expense.state in ('draft', 'reported') and expense.is_editable)
        if removable_expenses:
            return removable_expenses.unlink()
        return True


class HrExpenseLine(models.Model):
    _inherit = 'hr.expense.line'

    iqama_fee_line_id = fields.Many2one(
        'hr.iqama.fee.line',
        string='Residency/Visa Fee Line',
        ondelete='set null',
        copy=False,
        index=True,
    )
