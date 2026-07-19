# -*- coding: utf-8 -*-
from odoo import fields, models


class NxEgyptPayrollTaxBracket(models.Model):
    _name = 'nx.egypt.payroll.tax.bracket'
    _description = 'Egyptian Tax Brackets Matrix (Annual)'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'nx.egypt.payroll.tax', string='Tax Configuration',
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

    # Manually-entered range text per net-income category (matrix columns).
    col_600k = fields.Char(string='Net Income ≤ 600K', default='-')
    col_700k = fields.Char(string='600K < Net ≤ 700K', default='-')
    col_800k = fields.Char(string='700K < Net ≤ 800K', default='-')
    col_900k = fields.Char(string='800K < Net ≤ 900K', default='-')
    col_1200k = fields.Char(string='900K < Net ≤ 1.2M', default='-')
    col_above = fields.Char(string='Net > 1.2M', default='-')

    is_active = fields.Boolean(string='Active', default=True)
    notes = fields.Char(string='Notes')
