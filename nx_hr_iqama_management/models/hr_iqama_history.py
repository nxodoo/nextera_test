from odoo import fields, models


class HrIqamaHistory(models.Model):
    _name = 'hr.iqama.history'
    _description = 'Residency/Visa Request History'
    _order = 'changed_on desc, id desc'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    changed_on = fields.Datetime(
        string='Changed On',
        default=lambda self: fields.Datetime.now(),
        required=True,
        readonly=True,
    )
    changed_by_id = fields.Many2one(
        'res.users',
        string='Changed By',
        required=True,
        readonly=True,
    )
    field_name = fields.Char(string='Field', required=True, readonly=True)
    from_value = fields.Char(string='From', readonly=True)
    to_value = fields.Char(string='To', readonly=True)
