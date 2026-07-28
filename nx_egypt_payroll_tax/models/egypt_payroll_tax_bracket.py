# -*- coding: utf-8 -*-
from odoo import fields, models


class NxEgyptPayrollTaxBracket(models.Model):
    _name = 'nx.egypt.payroll.tax.bracket'
    _description = 'Egyptian Tax Bracket Line'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'nx.egypt.payroll.tax', string='Category',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    rate = fields.Float(string='Rate %', default=0.0)

    # Numeric bounds used by the progressive computation.
    amount_from = fields.Float(string='From', default=0.0)
    amount_to = fields.Float(
        string='To', default=0.0,
        help='Upper bound of the bracket. Leave 0 for an open-ended top bracket.',
    )

    notes = fields.Char(string='Notes')
