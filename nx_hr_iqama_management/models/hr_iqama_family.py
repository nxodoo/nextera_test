from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


LOCKED_REQUEST_STATES = {'active', 'cancelled', 'rejected', 'expired'}


class HrIqama(models.Model):
    _inherit = 'hr.iqama'

    def action_open_family_member_create_wizard(self):
        """Open the family member creation wizard from the iqama form."""
        self.ensure_one()
        if not self.id:
            raise ValidationError(_('Please save the residency/visa request before adding family members.'))
        wizard = self.env['hr.iqama.family.member.create.wizard'].create({
            'iqama_id': self.id,
        })
        wizard._load_required_documents()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Family Member'),
            'res_model': 'hr.iqama.family.member.create.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }


class HrIqamaFamilyMember(models.Model):
    _name = 'hr.iqama.family.member'
    _description = 'Residency/Visa Family Member'
    _order = 'id'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(string='Family Member', required=True)
    job_title = fields.Char(string='Job Title')
    department_id = fields.Many2one('hr.department', string='Department')
    company_id = fields.Many2one('res.company', string='Company')
    passport_number = fields.Char(string='Passport Number', required=True)
    nationality_id = fields.Many2one('res.country', string='Nationality')
    religion = fields.Char(string='Religion')
    passport_name = fields.Char(string='Passport Name')
    arabic_name = fields.Char(string='Arabic Name')
    date_of_birth = fields.Date(string='Date of Birth')
    passport_profession = fields.Char(string='Passport Profession')
    document_ids = fields.One2many(
        'hr.iqama.family.document',
        'family_member_id',
        string='Documents',
    )
    required_document_count = fields.Integer(
        string='Required Document Count',
        compute='_compute_document_progress',
    )
    uploaded_document_count = fields.Integer(
        string='Uploaded Document Count',
        compute='_compute_document_progress',
    )
    document_progress_display = fields.Char(
        string='Document Progress',
        compute='_compute_document_progress',
    )

    @api.model
    def action_open_family_member_create_wizard(self, *args):
        """Open the family member creation wizard from the one2many control row."""
        iqama_id = self.env.context.get('default_iqama_id')
        if not iqama_id:
            raise ValidationError(_('Please save the residency/visa request before adding family members.'))
        iqama = self.env['hr.iqama'].browse(iqama_id)
        if not iqama.exists():
            raise ValidationError(_('Please save the residency/visa request before adding family members.'))
        return iqama.action_open_family_member_create_wizard()

    @api.depends('document_ids.status', 'iqama_id.iqama_type_id.required_document_ids')
    def _compute_document_progress(self):
        for record in self:
            required_count = len(record.iqama_id.iqama_type_id.required_document_ids)
            uploaded_count = len(record.document_ids.filtered(lambda line: line.status == 'uploaded'))
            record.required_document_count = required_count
            record.uploaded_document_count = uploaded_count
            record.document_progress_display = _('%(uploaded)s / %(required)s uploaded') % {
                'uploaded': uploaded_count,
                'required': required_count,
            }

    def action_open_required_documents_wizard(self):
        """Open the family member document wizard prefilled with the required documents."""
        self.ensure_one()
        if not self.iqama_id.iqama_type_id:
            raise ValidationError(_('Please select a residency/visa type before adding family documents.'))
        wizard = self.env['hr.iqama.family.document.wizard'].create({
            'family_member_id': self.id,
        })
        wizard._load_required_documents()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Family Required Documents'),
            'res_model': 'hr.iqama.family.document.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            iqama = self.env['hr.iqama'].browse(vals.get('iqama_id'))
            if iqama and iqama.state in LOCKED_REQUEST_STATES:
                raise ValidationError(_('You cannot modify family members for a locked residency/visa request.'))
        records = super().create(vals_list)
        records._sync_required_document_lines()
        records.mapped('iqama_id')._sync_detail_lines()
        return records

    def write(self, vals):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify family members for a locked residency/visa request.'))
        result = super().write(vals)
        if 'name' in vals:
            self.mapped('document_ids').write({'family_member_name': vals.get('name') or False})
        if 'passport_number' in vals:
            self.mapped('document_ids').write({'passport_number': vals.get('passport_number') or False})
        if 'iqama_id' in vals:
            self._sync_required_document_lines()
        self.mapped('iqama_id')._sync_detail_lines()
        return result

    def unlink(self):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify family members for a locked residency/visa request.'))
        iqama_records = self.mapped('iqama_id')
        result = super().unlink()
        iqama_records._sync_detail_lines()
        return result

    def _sync_required_document_lines(self):
        """Keep family member document lines aligned with the request type requirements."""
        for record in self:
            required_documents = record.iqama_id.iqama_type_id.required_document_ids
            existing_document_ids = {
                line.required_document_id.id: line
                for line in record.document_ids.filtered('required_document_id')
            }
            lines_to_create = []
            for required_document in required_documents:
                existing_line = existing_document_ids.get(required_document.id)
                values = {
                    'document_name': required_document.name,
                    'description': required_document.description,
                    'mandatory': required_document.mandatory,
                    'is_manual_line': False,
                    'expiry_date_mandatory': required_document.expiry_date_mandatory,
                }
                if existing_line:
                    existing_line.write(values)
                    continue
                lines_to_create.append({
                    'iqama_id': record.iqama_id.id,
                    'family_member_id': record.id,
                    'family_member_name': record.name,
                    'passport_number': record.passport_number,
                    'required_document_id': required_document.id,
                    'is_manual_line': False,
                    **values,
                })
            if lines_to_create:
                self.env['hr.iqama.family.document'].create(lines_to_create)


class HrIqamaFamilyMemberCreateWizard(models.TransientModel):
    _name = 'hr.iqama.family.member.create.wizard'
    _description = 'Family Member Creation Wizard'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
    )
    name = fields.Char(string='Family Member')
    passport_number = fields.Char(string='Passport Number')
    passport_name = fields.Char(string='Passport Name')
    arabic_name = fields.Char(string='Arabic Name')
    nationality_id = fields.Many2one('res.country', string='Nationality')
    religion = fields.Char(string='Religion')
    date_of_birth = fields.Date(string='Date of Birth')
    passport_profession = fields.Char(string='Passport Profession')
    line_ids = fields.One2many(
        'hr.iqama.family.member.create.wizard.line',
        'wizard_id',
        string='Required Documents',
    )

    def _validate_family_member_details(self):
        """Ensure the wizard contains all mandatory family member details before saving."""
        self.ensure_one()
        required_field_labels = {
            'passport_number': _('Passport Number'),
            'passport_name': _('Passport Name (EN)'),
            'arabic_name': _('Passport Name (AR)'),
            'passport_profession': _('Profession'),
            'name': _('Relation'),
            'nationality_id': _('Nationality'),
            'date_of_birth': _('Date of Birth'),
            'religion': _('Religion'),
        }
        missing_labels = [
            label for field_name, label in required_field_labels.items()
            if not self[field_name]
        ]
        if missing_labels:
            raise ValidationError(
                _('Please complete all mandatory family member details before saving: %s')
                % ', '.join(missing_labels)
            )

    def _load_required_documents(self):
        """Prefill the wizard with all required documents for the selected iqama type."""
        for wizard in self:
            required_documents = wizard.iqama_id.iqama_type_id.required_document_ids
            wizard.line_ids = [(5, 0, 0)]
            wizard.line_ids = [(0, 0, {
                'required_document_id': required_document.id,
                'document_name': required_document.name,
                'description': required_document.description,
                'mandatory': required_document.mandatory,
                'is_manual_line': False,
                'expiry_date_mandatory': required_document.expiry_date_mandatory,
                'upload_date': fields.Date.context_today(self),
            }) for required_document in required_documents]

    def _validate_required_documents_before_save(self):
        """Prevent closing the wizard while required document lines are incomplete."""
        self.ensure_one()
        for line in self.line_ids:
            if line.mandatory and not line.attachment:
                raise ValidationError(
                    _('Please upload the required document "%s" before saving the family member.')
                    % (line.document_name or line.required_document_id.name)
                )
            if line.attachment and line.expiry_date_mandatory and not line.expiry_date:
                raise ValidationError(
                    _('Please set an expiry date for "%s" before saving the family member.')
                    % (line.document_name or line.required_document_id.name)
                )

    def _create_family_member_with_documents(self):
        """Create the family member and persist all wizard document lines."""
        self.ensure_one()
        self._validate_family_member_details()
        family_member = self.env['hr.iqama.family.member'].create({
            'iqama_id': self.iqama_id.id,
            'name': self.name,
            'passport_number': self.passport_number,
            'passport_name': self.passport_name,
            'arabic_name': self.arabic_name,
            'nationality_id': self.nationality_id.id,
            'religion': self.religion,
            'date_of_birth': self.date_of_birth,
            'passport_profession': self.passport_profession,
        })
        existing_lines = {
            line.required_document_id.id: line
            for line in family_member.document_ids.filtered('required_document_id')
        }
        for wizard_line in self.line_ids:
            values = {
                'iqama_id': family_member.iqama_id.id,
                'family_member_id': family_member.id,
                'family_member_name': family_member.name,
                'passport_number': family_member.passport_number,
                'required_document_id': wizard_line.required_document_id.id,
                'document_name': wizard_line.document_name,
                'description': wizard_line.description,
                'mandatory': wizard_line.mandatory,
                'is_manual_line': wizard_line.is_manual_line,
                'expiry_date_mandatory': wizard_line.expiry_date_mandatory,
                'expiry_date': wizard_line.expiry_date,
                'attachment': wizard_line.attachment,
                'attachment_filename': wizard_line.attachment_filename,
                'upload_date': wizard_line.upload_date,
            }
            existing_line = existing_lines.get(wizard_line.required_document_id.id)
            if existing_line:
                existing_line.write(values)
            else:
                self.env['hr.iqama.family.document'].create(values)
        return family_member

    def action_save_and_close(self):
        """Save the family member and close the wizard after document validation."""
        self.ensure_one()
        self._validate_required_documents_before_save()
        self._create_family_member_with_documents()
        return {'type': 'ir.actions.act_window_close'}

    def action_save_and_new(self):
        """Save the family member and reopen a fresh wizard."""
        self.ensure_one()
        self._validate_required_documents_before_save()
        self._create_family_member_with_documents()
        new_wizard = self.env['hr.iqama.family.member.create.wizard'].create({
            'iqama_id': self.iqama_id.id,
        })
        new_wizard._load_required_documents()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Family Member'),
            'res_model': 'hr.iqama.family.member.create.wizard',
            'view_mode': 'form',
            'res_id': new_wizard.id,
            'target': 'new',
        }


class HrIqamaFamilyMemberCreateWizardLine(models.TransientModel):
    _name = 'hr.iqama.family.member.create.wizard.line'
    _description = 'Family Member Create Wizard Line'
    _order = 'mandatory desc, id'

    wizard_id = fields.Many2one(
        'hr.iqama.family.member.create.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    required_document_id = fields.Many2one(
        'hr.iqama.type.document',
        string='Required Document',
        required=True,
        readonly=True,
    )
    document_name = fields.Char(string='Document Name', required=True)
    description = fields.Text(string='Description')
    mandatory = fields.Boolean(string='Mandatory', readonly=True)
    is_manual_line = fields.Boolean(string='Manual Line', default=True)
    expiry_date_mandatory = fields.Boolean(string='Expiry Date Mandatory', readonly=True)
    attachment = fields.Binary(string='Attachment', attachment=True)
    attachment_filename = fields.Char(string='Attachment Filename')
    expiry_date = fields.Date(string='Expiry Date')
    upload_date = fields.Date(string='Upload Date', default=fields.Date.context_today)
    status = fields.Selection(
        [('pending', 'Pending'), ('uploaded', 'Uploaded')],
        string='Status',
        compute='_compute_status',
        store=True,
    )

    @api.depends('attachment')
    def _compute_status(self):
        for record in self:
            record.status = 'uploaded' if record.attachment else 'pending'

    def action_remove_manual_line(self):
        """Delete a manually added wizard line while protecting preloaded required rows."""
        self.ensure_one()
        if not self.is_manual_line:
            raise ValidationError(_('Only manually added document lines can be deleted.'))
        self.unlink()


class HrIqamaFamilyDocument(models.Model):
    _name = 'hr.iqama.family.document'
    _description = 'Residency/Visa Family Document'
    _order = 'mandatory desc, id'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        ondelete='cascade',
        index=True,
    )
    family_member_id = fields.Many2one(
        'hr.iqama.family.member',
        string='Family Member',
        ondelete='cascade',
    )
    family_member_name = fields.Char(string='Family Member')
    passport_number = fields.Char(string='Passport Number')
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
    attachment = fields.Binary(string='Attachment', attachment=True)
    attachment_filename = fields.Char(string='Attachment Filename')
    expiry_date = fields.Date(string='Expiry Date')
    upload_date = fields.Date(string='Upload Date', default=fields.Date.context_today)
    status = fields.Selection(
        [('pending', 'Pending'), ('uploaded', 'Uploaded')],
        string='Status',
        compute='_compute_status',
        store=True,
    )

    @api.depends('attachment')
    def _compute_status(self):
        for record in self:
            record.status = 'uploaded' if record.attachment else 'pending'

    def _validate_expiry_date_requirement(self, vals=None):
        """Ensure expiry date is filled when the family document requires it."""
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
            family_member = self.env['hr.iqama.family.member'].browse(vals.get('family_member_id'))
            iqama = family_member.iqama_id or self.env['hr.iqama'].browse(vals.get('iqama_id'))
            if family_member:
                vals.setdefault('iqama_id', family_member.iqama_id.id)
                vals.setdefault('family_member_name', family_member.name)
                vals.setdefault('passport_number', family_member.passport_number)
            if iqama and iqama.state in LOCKED_REQUEST_STATES:
                raise ValidationError(_('You cannot modify family documents for a locked residency/visa request.'))
        records = super().create(vals_list)
        records._validate_expiry_date_requirement()
        return records

    def write(self, vals):
        if any((record.iqama_id or record.family_member_id.iqama_id).state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify family documents for a locked residency/visa request.'))
        result = super().write(vals)
        self._validate_expiry_date_requirement(vals)
        return result

    def unlink(self):
        if any((record.iqama_id or record.family_member_id.iqama_id).state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify family documents for a locked residency/visa request.'))
        non_manual_lines = self.filtered(lambda record: not record.is_manual_line)
        if non_manual_lines:
            raise ValidationError(_('Only manually added document lines can be deleted.'))
        return super().unlink()

    def action_remove_manual_line(self):
        """Delete a manually added family document line from the editable checklist."""
        self.ensure_one()
        if not self.is_manual_line:
            raise ValidationError(_('Only manually added document lines can be deleted.'))
        self.unlink()


class HrIqamaFamilyDocumentWizard(models.TransientModel):
    _name = 'hr.iqama.family.document.wizard'
    _description = 'Family Required Documents Wizard'

    family_member_id = fields.Many2one(
        'hr.iqama.family.member',
        string='Family Member',
        required=True,
    )
    passport_number = fields.Char(
        string='Passport Number',
        related='family_member_id.passport_number',
        readonly=True,
    )
    line_ids = fields.One2many(
        'hr.iqama.family.document.wizard.line',
        'wizard_id',
        string='Required Documents',
    )

    def _load_required_documents(self):
        """Prefill the wizard with the required family documents and uploaded files."""
        for wizard in self:
            required_documents = wizard.family_member_id.iqama_id.iqama_type_id.required_document_ids
            existing_lines = {
                line.required_document_id.id: line
                for line in wizard.family_member_id.document_ids.filtered('required_document_id')
            }
            wizard.line_ids = [(5, 0, 0)]
            new_lines = []
            for required_document in required_documents:
                existing_line = existing_lines.get(required_document.id)
                new_lines.append((0, 0, {
                    'required_document_id': required_document.id,
                    'description': existing_line.description if existing_line else required_document.description,
                    'mandatory': required_document.mandatory,
                    'is_manual_line': False,
                    'expiry_date_mandatory': required_document.expiry_date_mandatory,
                    'expiry_date': existing_line.expiry_date if existing_line else False,
                    'attachment': existing_line.attachment if existing_line else False,
                    'attachment_filename': existing_line.attachment_filename if existing_line else False,
                    'upload_date': existing_line.upload_date if existing_line else fields.Date.context_today(self),
                }))
            wizard.line_ids = new_lines

    def action_save_documents(self):
        """Persist the wizard uploads back to the family member document rows."""
        document_model = self.env['hr.iqama.family.document']
        for wizard in self:
            family_member = wizard.family_member_id
            existing_lines = {
                line.required_document_id.id: line
                for line in family_member.document_ids.filtered('required_document_id')
            }
            for wizard_line in wizard.line_ids:
                values = {
                    'iqama_id': family_member.iqama_id.id,
                    'family_member_id': family_member.id,
                    'family_member_name': family_member.name,
                    'passport_number': family_member.passport_number,
                    'required_document_id': wizard_line.required_document_id.id,
                    'document_name': wizard_line.required_document_id.name,
                    'description': wizard_line.description,
                    'mandatory': wizard_line.mandatory,
                    'is_manual_line': wizard_line.is_manual_line,
                    'expiry_date_mandatory': wizard_line.expiry_date_mandatory,
                    'expiry_date': wizard_line.expiry_date,
                    'attachment': wizard_line.attachment,
                    'attachment_filename': wizard_line.attachment_filename,
                    'upload_date': wizard_line.upload_date,
                }
                existing_line = existing_lines.get(wizard_line.required_document_id.id)
                if existing_line:
                    existing_line.write(values)
                    continue
                document_model.create(values)
        return {'type': 'ir.actions.act_window_close'}


class HrIqamaFamilyDocumentWizardLine(models.TransientModel):
    _name = 'hr.iqama.family.document.wizard.line'
    _description = 'Family Required Documents Wizard Line'
    _order = 'mandatory desc, id'

    wizard_id = fields.Many2one(
        'hr.iqama.family.document.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    required_document_id = fields.Many2one(
        'hr.iqama.type.document',
        string='Required Document',
        required=True,
        readonly=True,
    )
    description = fields.Text(string='Description')
    mandatory = fields.Boolean(string='Mandatory', readonly=True)
    is_manual_line = fields.Boolean(string='Manual Line', default=True)
    expiry_date_mandatory = fields.Boolean(string='Expiry Date Mandatory', readonly=True)
    attachment = fields.Binary(string='Attachment', attachment=True)
    attachment_filename = fields.Char(string='Attachment Filename')
    expiry_date = fields.Date(string='Expiry Date')
    upload_date = fields.Date(string='Upload Date', default=fields.Date.context_today)

    def action_remove_manual_line(self):
        """Delete a manually added family document wizard line only."""
        self.ensure_one()
        if not self.is_manual_line:
            raise ValidationError(_('Only manually added document lines can be deleted.'))
        self.unlink()
