from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class CustodyReturnWizard(models.TransientModel):
    _name = 'custody.return.wizard'
    _description = 'Return Custody Wizard'

    custody_id = fields.Many2one(
        'custody.request',
        string="Custody Request",
        required=True,
        readonly=True
    )

    balance = fields.Float(
        string="Available Balance",
        readonly=True
    )

    amount = fields.Float(
        string="Return Amount",
        required=True
    )

    journal_id = fields.Many2one(
        'account.journal',
        string="Journal",
        required=True,
        domain="[('type', 'in', ('cash', 'bank'))]"
    )

    journal_ids = fields.Many2many(
        "account.journal",
        string="Available Custody Journals",
    )

    @api.constrains('amount')
    def _check_amount(self):
        """Validate the return amount."""
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Return amount must be greater than zero."))
            if rec.amount > rec.balance:
                raise ValidationError(_("Return amount cannot exceed the available balance."))

    def action_confirm_return(self):
        """Confirm the return of custody and create accounting entries."""
        self.ensure_one()
        custody = self.custody_id

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': f'Return Custody - {custody.name}',
            'line_ids': [
                (0, 0, {
                    'name': 'Custody Return',
                    'account_id': custody.custody_account_id.id,
                    'credit': self.amount,
                    'partner_id': custody.employee_id.work_contact_id.id,
                }),
                (0, 0, {
                    'name': 'Custody Return',
                    'account_id': self.journal_id.default_account_id.id,
                    'debit': self.amount,
                }),
            ]
        })

        custody.entry_ids = [(4, move.id)]

        return {'type': 'ir.actions.act_window_close'}

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Force compute journal_ids
        param = self.env['ir.config_parameter'].sudo()
        temporary_id = param.get_param('nx_employee_custody_management.custody_journal_temporary_id')
        permanent_id = param.get_param('nx_employee_custody_management.custody_journal_permanent_id')
        journal_ids = [int(x) for x in [temporary_id, permanent_id] if
                       x and self.env['account.journal'].browse(int(x)).exists()]
        res['journal_ids'] = [(6, 0, journal_ids)]
        return res
