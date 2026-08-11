# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class CustodyProductReturnWizard(models.TransientModel):
    """Return products held under custody.

    If a returned line has NOT yet expired, its value is charged back to the
    employee as a money *deduction* (a journal entry). Expired lines are
    returned with no financial impact.
    """

    _name = "custody.product.return.wizard"
    _description = "Return Product Custody Wizard"

    custody_id = fields.Many2one(
        'custody.request', string="Custody Request", required=True, readonly=True,
    )
    company_currency_id = fields.Many2one(
        'res.currency', related='custody_id.company_currency_id',
    )
    date = fields.Date(string="Return Date", default=fields.Date.context_today, required=True)
    line_ids = fields.One2many(
        'custody.product.return.wizard.line', 'wizard_id', string="Products to Return",
    )
    deduction_total = fields.Monetary(
        string="Total Deduction",
        compute="_compute_deduction_total",
        currency_field='company_currency_id',
        help="Value of still-valid products, charged back to the employee.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        custody = self.env['custody.request'].browse(res.get('custody_id') or self.env.context.get('default_custody_id'))
        if custody:
            res['custody_id'] = custody.id
            lines = []
            for line in custody.product_line_ids.filtered(lambda l: l.state == 'confirmed'):
                deduction = 0.0 if line.is_expired else line.quantity * line.unit_cost
                lines.append((0, 0, {
                    'product_line_id': line.id,
                    'to_return': True,
                    'return_qty': line.quantity,
                    'line_deduction': deduction,
                }))
            res['line_ids'] = lines
        return res

    @api.depends('line_ids.to_return', 'line_ids.is_expired', 'line_ids.line_deduction')
    def _compute_deduction_total(self):
        for wiz in self:
            wiz.deduction_total = sum(
                l.line_deduction
                for l in wiz.line_ids
                if l.to_return and not l.is_expired
            )

    def action_confirm_return(self):
        self.ensure_one()
        to_return = self.line_ids.filtered('to_return')
        if not to_return:
            raise UserError(_("Select at least one product line to return."))

        deduction_lines = to_return.filtered(lambda l: not l.is_expired)
        if deduction_lines:
            self._create_deduction_entry(deduction_lines)

        # Mark the original custody product lines as returned.
        to_return.mapped('product_line_id').write({'state': 'returned'})

        custody = self.custody_id
        if all(l.state == 'returned' for l in custody.product_line_ids):
            custody.state = 'entry_cancelled'

        return {'type': 'ir.actions.act_window_close'}

    def _create_deduction_entry(self, deduction_lines):
        """Post a journal entry charging the employee for still-valid returns."""
        param = self.env['ir.config_parameter'].sudo()
        journal_id = param.get_param('nx_employee_custody_management.custody_product_journal_id')
        product_account_id = param.get_param('nx_employee_custody_management.custody_product_account_id')
        deduction_account_id = param.get_param('nx_employee_custody_management.custody_deduction_account_id')

        if not (journal_id and product_account_id and deduction_account_id):
            raise UserError(_(
                "Please configure the Product Custody Journal, Product Custody "
                "Account and Custody Deduction Account in Settings."))

        custody = self.custody_id
        partner = custody.employee_id.work_contact_id
        move_lines = []
        for line in deduction_lines:
            value = line.line_deduction
            if not value:
                continue
            label = _("Custody Deduction - %s") % (line.product_line_id.product_id.display_name)
            # Debit: employee owes the value (deduction / receivable)
            move_lines.append((0, 0, {
                'name': label,
                'account_id': int(deduction_account_id),
                'partner_id': partner.id if partner else False,
                'debit': value,
                'credit': 0.0,
            }))
            # Credit: release the product custody asset
            move_lines.append((0, 0, {
                'name': label,
                'account_id': int(product_account_id),
                'partner_id': partner.id if partner else False,
                'debit': 0.0,
                'credit': value,
            }))

        if not move_lines:
            return

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': int(journal_id),
            'date': self.date,
            'ref': _('Product Custody Deduction - %s') % custody.name,
            'custody_request_id': custody.id,
            'line_ids': move_lines,
        })
        move.action_post()
        custody.entry_ids = [(4, move.id)]
        return move


class CustodyProductReturnWizardLine(models.TransientModel):
    _name = "custody.product.return.wizard.line"
    _description = "Return Product Custody Wizard Line"

    wizard_id = fields.Many2one('custody.product.return.wizard', required=True, ondelete='cascade')
    company_currency_id = fields.Many2one('res.currency', related='wizard_id.company_currency_id')
    product_line_id = fields.Many2one('custody.product.line', string="Custody Line", required=True)
    product_id = fields.Many2one(related='product_line_id.product_id', string="Product")
    lot_id = fields.Many2one(related='product_line_id.lot_id', string="Lot / Serial")
    expiry_date = fields.Date(related='product_line_id.expiry_date', string="Expiry Date")
    is_expired = fields.Boolean(related='product_line_id.is_expired', string="Expired")
    remaining_period = fields.Char(related='product_line_id.remaining_period', string="Remaining")
    unit_cost = fields.Monetary(related='product_line_id.unit_cost', currency_field='company_currency_id')
    return_qty = fields.Float(string="Return Qty", default=1.0)
    to_return = fields.Boolean(string="Return", default=True)
    line_deduction = fields.Monetary(
        string="Deduction",
        currency_field='company_currency_id',
        help="Amount charged back to the employee. Auto-filled from "
             "Return Qty x Unit Cost, but you can edit it manually.",
    )

    @api.onchange('to_return', 'return_qty', 'unit_cost')
    def _onchange_suggest_deduction(self):
        """Suggest a deduction; the user may override it afterwards."""
        for line in self:
            if line.to_return and not line.is_expired:
                line.line_deduction = line.return_qty * line.unit_cost
            else:
                line.line_deduction = 0.0

    @api.constrains('return_qty', 'to_return')
    def _check_return_qty(self):
        for line in self:
            if line.to_return and line.return_qty <= 0:
                raise ValidationError(_("Return quantity must be greater than zero."))
            if line.to_return and line.return_qty > line.product_line_id.quantity:
                raise ValidationError(_("Return quantity cannot exceed the custody quantity."))
