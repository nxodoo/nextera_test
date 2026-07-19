from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


LOCKED_REQUEST_STATES = {'active', 'cancelled', 'rejected', 'expired'}


class HrIqamaAttachment(models.Model):
    _name = 'hr.iqama.attachment'
    _description = 'Residency and Visa Attachment'
    _order = 'mandatory desc, id'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Record',
        required=True,
        ondelete='cascade',
    )
    required_document_id = fields.Many2one(
        'hr.iqama.type.document',
        string='Required Document',
        ondelete='set null',
    )
    document_name = fields.Char(string='Document Name', required=True)
    description = fields.Text(string='Description')
    mandatory = fields.Boolean(string='Mandatory', default=True)
    is_manual_line = fields.Boolean(string='Manual Line', default=True)
    expiry_date_mandatory = fields.Boolean(string='Expiry Date Mandatory', default=False)
    attachment = fields.Binary(
        string='Attachment',
        attachment=True,
    )
    attachment_filename = fields.Char(string='Attachment Filename')
    expiry_date = fields.Date(string='Expiry Date')
    upload_date = fields.Date(
        string='Upload Date',
        default=fields.Date.context_today,
    )
    status = fields.Selection(
        [('pending', 'Pending'), ('uploaded', 'Uploaded')],
        string='Status',
        compute='_compute_status',
        store=True,
    )
    name = fields.Char(
        string='Description',
        compute='_compute_name',
        store=True,
    )

    @api.depends('attachment')
    def _compute_status(self):
        for record in self:
            record.status = 'uploaded' if record.attachment else 'pending'

    @api.depends('document_name')
    def _compute_name(self):
        for record in self:
            record.name = record.document_name

    def _validate_expiry_date_requirement(self, vals=None):
        """Ensure expiry date is filled when the document requires it."""
        vals = vals or {}
        for record in self:
            attachment = vals.get('attachment', record.attachment)
            expiry_date = vals.get('expiry_date', record.expiry_date)
            expiry_required = vals.get('expiry_date_mandatory', record.expiry_date_mandatory)
            document_name = vals.get('document_name', record.document_name) or _('This document')
            if attachment and expiry_required and not expiry_date:
                raise ValidationError(
                    _('You must set an expiry date for %s before saving the document.')
                    % document_name
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            iqama = self.env['hr.iqama'].browse(vals.get('iqama_id'))
            if iqama and iqama.state in LOCKED_REQUEST_STATES:
                raise ValidationError(_('You cannot modify documents for a locked residency/visa request.'))
        records = super().create(vals_list)
        records._validate_expiry_date_requirement()
        return records

    def write(self, vals):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify documents for a locked residency/visa request.'))
        result = super().write(vals)
        self._validate_expiry_date_requirement(vals)
        return result

    def unlink(self):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify documents for a locked residency/visa request.'))
        non_manual_lines = self.filtered(lambda record: not record.is_manual_line)
        if non_manual_lines:
            raise ValidationError(_('Only manually added document lines can be deleted.'))
        return super().unlink()

    def action_remove_manual_line(self):
        """Delete a manually added document line from the editable checklist."""
        self.ensure_one()
        if not self.is_manual_line:
            raise ValidationError(_('Only manually added document lines can be deleted.'))
        self.unlink()
