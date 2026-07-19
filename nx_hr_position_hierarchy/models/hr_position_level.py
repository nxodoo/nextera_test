# -*- coding: utf-8 -*-

from odoo import fields, models


class HrPositionLevel(models.Model):
    _name = 'hr.position.level'
    _description = 'HR Position Level'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10, required=True)
    is_assistant = fields.Boolean(
        string='Assistant Level',
        help='Use this level for assistant positions that appear beside the main reporting line.',
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'code_unique',
            'UNIQUE(code)',
            'Position level code must be unique.',
        ),
    ]
