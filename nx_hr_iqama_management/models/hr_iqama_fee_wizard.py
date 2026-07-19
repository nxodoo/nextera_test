from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrIqamaFeeAddWizard(models.TransientModel):
    _name = 'hr.iqama.fee.add.wizard'
    _description = 'Add Residency/Visa Fees'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='iqama_id.employee_id',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='iqama_id.company_id',
        readonly=True,
    )
    claim_date = fields.Date(
        string='Claim Date',
        required=True,
        default=fields.Date.context_today,
    )
    line_ids = fields.One2many(
        'hr.iqama.fee.add.wizard.line',
        'wizard_id',
        string='Fee Lines',
    )

    def action_add_fees(self):
        """Create IQAMA fee lines from the wizard rows.

        A brand-new hr.expense is always created for each wizard session so
        that repeated "Add Fees" calls each produce their own travel request,
        regardless of whether a previous editable expense still exists.
        """
        self.ensure_one()
        if not self.line_ids:
            raise ValidationError(_('Add at least one fee line before saving.'))

        iqama = self.iqama_id
        request_label = iqama.request_number or iqama.display_name or _('Residency/Visa Request')
        first_line = self.line_ids[0]
        batch_total = sum(self.line_ids.mapped('amount'))
        claim_date = self.claim_date or fields.Date.context_today(self)

        # Always create a fresh expense so this batch gets its own travel request.
        new_expense = self.env['hr.expense'].create({
            'name': _('Residency/Visa Fees - %s') % request_label,
            'product_id': first_line.expense_type_id.id,
            'date': claim_date,
            'currency_id': first_line.currency_id.id,
            'total_amount': batch_total,
            'total_amount_currency': batch_total,
            'price_unit': batch_total,
            'quantity': 1.0,
            'employee_id': iqama.employee_id.id,
            'company_id': iqama.company_id.id,
            'iqama_request_id': iqama.id,
        })

        fee_commands = []
        for line in self.line_ids:
            fee_commands.append((0, 0, {
                'expense_type_id': line.expense_type_id.id,
                'claim_date': line.claim_date or claim_date,
                'amount': line.amount,
                'currency_id': line.currency_id.id,
                # Pre-assign to the new expense so _sync_linked_expense()
                # groups all lines from this session into it, not an old one.
                'expense_id': new_expense.id,
            }))

        iqama.write({'fee_line_ids': fee_commands})
        return {'type': 'ir.actions.act_window_close'}


class HrIqamaFeeAddWizardLine(models.TransientModel):
    _name = 'hr.iqama.fee.add.wizard.line'
    _description = 'Add Residency/Visa Fee Wizard Line'

    wizard_id = fields.Many2one(
        'hr.iqama.fee.add.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    expense_type_id = fields.Many2one(
        'product.product',
        string='Expense Type',
        required=True,
        domain="[('can_be_expensed', '=', True)]",
    )
    name = fields.Char(
        string='Description',
        related='expense_type_id.display_name',
        readonly=True,
    )
    claim_date = fields.Date(
        string='Expense Date',
        default=lambda self: self.wizard_id.claim_date or fields.Date.context_today(self),
    )
    amount = fields.Monetary(
        string='Total',
        required=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

