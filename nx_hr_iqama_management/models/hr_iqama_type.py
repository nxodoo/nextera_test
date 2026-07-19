from odoo import api, fields, models


TYPE_DURATION_SELECTION = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('semi_annual', 'Semi-Annual'),
    ('annual', 'Annual'),
    ('extended', 'Extended'),
]


class HrIqamaType(models.Model):
    _name = 'hr.iqama.type'
    _description = 'Residency and Visa Type'
    _order = 'name, country_id, id'

    reference = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New')
    name = fields.Char(string='Type Name', required=True, translate=True)
    country_id = fields.Many2one('res.country', string='Country', required=True)
    duration = fields.Selection(
        TYPE_DURATION_SELECTION,
        string='Duration',
        required=True,
        default='annual',
    )
    description = fields.Text(string='Description', translate=True)
    notes = fields.Text(string='Notes', translate=True)
    active = fields.Boolean(string='Active', default=True)
    expiry_notification_days = fields.Integer(string='Expiry Notification Days', default=30)
    renewable = fields.Boolean(string='Renewable', default=True)
    estimated_cost_usd = fields.Float(string='Estimated Cost (USD)')
    required_document_ids = fields.One2many(
        'hr.iqama.type.document',
        'iqama_type_id',
        string='Required Documents',
    )

    _sql_constraints = [
        (
            'hr_iqama_type_unique_name_country_duration',
            'unique(name, country_id, duration)',
            'The residency/visa type must be unique for the selected country and duration.',
        ),
        (
            'hr_iqama_type_unique_reference',
            'unique(reference)',
            'The reference must be unique.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records.filtered(lambda rec: not rec.reference or rec.reference == 'New'):
            record.reference = f'TYPE{record.id:05d}'
        return records


class HrIqamaTypeDocument(models.Model):
    _name = 'hr.iqama.type.document'
    _description = 'Residency and Visa Type Document'
    _order = 'iqama_type_id, id'

    iqama_type_id = fields.Many2one(
        'hr.iqama.type',
        string='Residency/Visa Type',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(string='Document Name', required=True, translate=True)
    reference = fields.Char(string='Reference', translate=True)
    description = fields.Text(string='Description', translate=True)
    mandatory = fields.Boolean(string='Mandatory', default=True)
    expiry_date_mandatory = fields.Boolean(string='Is Expiry Date', default=False)

    _sql_constraints = [
        (
            'hr_iqama_type_document_unique_name_per_type',
            'unique(iqama_type_id, name)',
            'The document name must be unique per residency/visa type.',
        ),
    ]
