from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .hr_iqama_type import TYPE_DURATION_SELECTION


STATE_SELECTION = [
    ('new', 'New'),
    ('under_review', 'Under Review'),
    ('under_processing', 'Under Processing'),
    ('active', 'Active'),
    ('cancelled', 'Cancelled'),
    ('rejected', 'Rejected'),
    ('expired', 'Expired'),
]

PROCESSING_STAGE_SELECTION = [
    ('submission', 'Request Submission'),
    ('iqama_details', 'Iqama Details'),
    ('fees', 'Fees'),
    ('security_review', 'Security Review'),
    ('completed', 'Completed'),
]
PROCESSING_STAGE_ORDER = {
    'submission': 0,
    'iqama_details': 1,
    'fees': 2,
    'security_review': 3,
    'completed': 4,
}

LOCKED_STATES = {'active', 'cancelled', 'rejected', 'expired'}
MAIL_WRITE_FIELDS = {
    'message_follower_ids',
    'message_partner_ids',
    'message_main_attachment_id',
    'message_ids',
    'activity_ids',
    'activity_state',
    'activity_type_icon',
    'activity_exception_decoration',
    'message_attachment_count',
    'message_needaction',
    'message_has_error',
    'message_has_error_counter',
    'message_needaction_counter',
    'message_has_sms_error',
}
HISTORY_WRITE_EXCLUDED_FIELDS = MAIL_WRITE_FIELDS | {
    'write_uid',
    'write_date',
    '__last_update',
    'message_is_follower',
    'message_needaction',
    'message_needaction_counter',
    'message_has_error',
    'message_has_error_counter',
    'message_has_sms_error',
}
ACTIVE_ALLOWED_WRITE_FIELDS = {'fee_line_ids', 'timeline_ids'}


HIJRI_MONTHS_EN = {
    1: 'Muharram',
    2: 'Safar',
    3: 'Rabi al-Awwal',
    4: 'Rabi al-Thani',
    5: 'Jumada al-Ula',
    6: 'Jumada al-Akhirah',
    7: 'Rajab',
    8: "Sha'ban",
    9: 'Ramadan',
    10: 'Shawwal',
    11: "Dhu al-Qi'dah",
    12: 'Dhu al-Hijjah',
}

HIJRI_MONTHS_AR = {
    1: 'محرم',
    2: 'صفر',
    3: 'ربيع الأول',
    4: 'ربيع الآخر',
    5: 'جمادى الأولى',
    6: 'جمادى الآخرة',
    7: 'رجب',
    8: 'شعبان',
    9: 'رمضان',
    10: 'شوال',
    11: 'ذو القعدة',
    12: 'ذو الحجة',
}


class HrIqama(models.Model):
    _name = 'hr.iqama'
    _description = 'Residency/Visa Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expiry_date asc, id desc'
    _rec_name = 'request_number'

    request_number = fields.Char(string='Request Number', readonly=True, copy=False, index=True)
    created_on = fields.Datetime(string='Created Date', related='create_date', readonly=True)
    last_updated_on = fields.Datetime(string='Last Updated Date', related='write_date', readonly=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
    )
    employee_name = fields.Char(string='Employee Name', related='employee_id.name', readonly=True)
    request_country_id = fields.Many2one(
        'res.country',
        string='Country',
        tracking=True,
    )
    iqama_type_id = fields.Many2one(
        'hr.iqama.type',
        string='Residency/Visa Type',
        domain="[('country_id', '=', request_country_id), ('active', '=', True)]",
        tracking=True,
    )
    iqama_type_country_id = fields.Many2one(
        'res.country',
        string='Country',
        related='iqama_type_id.country_id',
        store=True,
        readonly=True,
    )
    iqama_type_duration = fields.Selection(
        TYPE_DURATION_SELECTION,
        string='Duration',
        related='iqama_type_id.duration',
        store=True,
        readonly=True,
    )
    application_date = fields.Date(string='Application Date', tracking=True, default=fields.Date.context_today)
    job_title = fields.Char(string='Job Title', tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    passport_number = fields.Char(
        string='Passport Number',
        related='employee_id.passport_id',
        store=True,
        readonly=True,
    )
    passport_name_english = fields.Char(string='Passport Name (EN)', tracking=True)
    passport_name_arabic = fields.Char(string='Passport Name (AR)', tracking=True)
    nationality_id = fields.Many2one('res.country', string='Nationality', tracking=True)
    religion = fields.Char(string='Religion', tracking=True)
    date_of_birth = fields.Date(string='Date of Birth', tracking=True)
    passport_profession = fields.Char(string='Passport Profession', tracking=True)

    iqama_number = fields.Char(string='Visa/Residency Number', tracking=True)
    serial_number = fields.Char(string='Serial Number', tracking=True)
    issue_place = fields.Char(string='Issue Place', tracking=True)
    issue_date = fields.Date(string='Issue Date', tracking=True)
    expiry_date = fields.Date(string='Expiry Date', tracking=True)
    hijri_expiry_date = fields.Date(string='Hijri Expiry Date', tracking=True)
    hijri_expiry_date_display = fields.Char(
        string='Hijri Expiry Date',
        compute='_compute_hijri_expiry_date_display',
    )
    arrival_date = fields.Date(string='Entry Date', tracking=True)
    currently_in_kingdom = fields.Boolean(string='Currently Inside Country', tracking=True)
    includes_family = fields.Boolean(string='Includes Family', tracking=True)
    requires_travel = fields.Boolean(string='Requires Travel', tracking=True)
    multiple_entry_exit = fields.Boolean(string='Multiple Entry Exit', tracking=True)
    iqama_cost = fields.Monetary(string='Iqama Cost', currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    state = fields.Selection(
        STATE_SELECTION,
        string='Status',
        default='new',
        tracking=True,
    )
    processing_stage = fields.Selection(
        PROCESSING_STAGE_SELECTION,
        string='Processing Stage',
        default='submission',
        tracking=True,
    )
    furthest_processing_stage = fields.Selection(
        PROCESSING_STAGE_SELECTION,
        string='Furthest Processing Stage',
        default='submission',
        tracking=False,
    )
    attachment_ids = fields.One2many(
        'hr.iqama.attachment',
        'iqama_id',
        string='Required Attachments',
    )
    detail_line_ids = fields.One2many(
        'hr.iqama.detail.line',
        'iqama_id',
        string='IQAMA Details Lines',
    )
    family_member_ids = fields.One2many(
        'hr.iqama.family.member',
        'iqama_id',
        string='Family Members',
    )
    family_document_ids = fields.One2many(
        'hr.iqama.family.document',
        'iqama_id',
        string='Family Member Documents',
    )
    approval_line_ids = fields.One2many(
        'hr.iqama.approval',
        'iqama_id',
        string='Approvals',
    )
    fee_line_ids = fields.One2many(
        'hr.iqama.fee.line',
        'iqama_id',
        string='Fees',
    )
    timeline_ids = fields.One2many(
        'hr.iqama.timeline',
        'iqama_id',
        string='Request Timeline',
    )
    history_ids = fields.One2many(
        'hr.iqama.history',
        'iqama_id',
        string='History',
        readonly=True,
    )
    travel_expense_ids = fields.One2many(
        'hr.expense',
        'iqama_request_id',
        string='Travel Requests',
    )
    travel_request_count = fields.Integer(
        string='Travel Requests',
        compute='_compute_travel_request_count',
    )
    attachment_count = fields.Integer(string='Attachment Count', compute='_compute_attachment_count')
    approval_required = fields.Boolean(
        string='Approval Required',
        compute='_compute_approval_state',
    )
    current_user_can_approve = fields.Boolean(
        string='Current User Can Approve',
        compute='_compute_approval_state',
    )
    current_user_can_reject = fields.Boolean(
        string='Current User Can Reject',
        compute='_compute_approval_state',
    )

    def action_open_add_fees_wizard(self):
        """Open a fee-entry wizard from the Fees tab."""
        self.ensure_one()
        wizard = self.env['hr.iqama.fee.add.wizard'].create({
            'iqama_id': self.id,
            'claim_date': fields.Date.context_today(self),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Fees'),
            'res_model': 'hr.iqama.fee.add.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wizard.id,
        }
    pending_approval_count = fields.Integer(
        string='Pending Approval Count',
        compute='_compute_approval_state',
    )
    approved_approval_count = fields.Integer(
        string='Approved Approval Count',
        compute='_compute_approval_state',
    )
    submission_form_ready = fields.Boolean(
        string='Submission Form Ready',
        compute='_compute_submission_form_ready',
    )
    is_expiring_soon = fields.Boolean(
        string='Expiring Soon',
        compute='_compute_is_expiring_soon',
        search='_search_is_expiring_soon',
    )
    security_question_identity_verified = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Identity documents verified',
        tracking=True,
    )
    security_question_employee_clear = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Employee passed internal security review',
        tracking=True,
    )
    security_question_no_restrictions = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='No travel or residency restrictions found',
        tracking=True,
    )
    security_review_notes = fields.Text(string='Security Review Notes', tracking=True)

    _sql_constraints = [
        ('request_number_company_uniq', 'unique(request_number, company_id)', 'The request number must be unique per company.'),
        ('iqama_number_company_uniq', 'unique(iqama_number, company_id)', 'The iqama number must be unique per company.'),
    ]

    @api.depends('attachment_ids', 'family_member_ids.document_ids')
    def _compute_attachment_count(self):
        for record in self:
            record.attachment_count = len(record.attachment_ids) + sum(len(member.document_ids) for member in record.family_member_ids)

    def _compute_travel_request_count(self):
        for record in self:
            record.travel_request_count = len(record.travel_expense_ids)

    @api.constrains('issue_date', 'expiry_date')
    def _check_expiry_date_not_before_issue_date(self):
        """Ensure the expiry date is never earlier than the issue date."""
        for record in self:
            if record.issue_date and record.expiry_date and record.expiry_date < record.issue_date:
                raise ValidationError(_('Expiry Date cannot be earlier than Issue Date.'))

    @api.depends(
        'state',
        'employee_id.residency_approver_ids',
        'approval_line_ids.approver_id',
        'approval_line_ids.status',
    )
    def _compute_approval_state(self):
        """Compute request approval helpers for the current user and UI state."""
        current_user = self.env.user
        for record in self:
            pending_lines = record.approval_line_ids.filtered(lambda line: line.status == 'pending')
            approved_lines = record.approval_line_ids.filtered(lambda line: line.status == 'approved')
            approval_required = bool(record.employee_id.residency_approver_ids)
            current_user_pending = any(
                line.approver_id == current_user and line.status == 'pending'
                for line in record.approval_line_ids
            )
            record.approval_required = approval_required
            record.pending_approval_count = len(pending_lines)
            record.approved_approval_count = len(approved_lines)
            record.current_user_can_approve = record.state == 'under_review' and (
                current_user_pending or not approval_required
            )
            record.current_user_can_reject = record.state == 'under_review' and (
                current_user_pending or not approval_required
            )

    def _get_status_label(self):
        self.ensure_one()
        return dict(self._fields['state']._description_selection(self.env)).get(self.state, self.state)

    def _value_to_history_text(self, field_name):
        """Convert a field value into readable text for the history tab.

        :param str field_name: Technical field name on ``hr.iqama``.
        :return: Readable text value or ``False`` when empty.
        :rtype: str | bool
        """
        self.ensure_one()
        field = self._fields.get(field_name)
        if not field:
            return False

        value = self[field_name]
        if field.type == 'many2one':
            return value.display_name if value else False
        if field.type in ('many2many', 'one2many'):
            return ", ".join(value.mapped('display_name')) if value else False
        if field.type == 'selection':
            selection_values = dict(field._description_selection(self.env))
            return selection_values.get(value, value) if value else False
        if field.type == 'boolean':
            return 'True' if value else 'False'
        return str(value) if value not in (False, None, '') else False

    def _tracked_history_field_names(self, vals):
        """Return writable request fields from ``vals`` that should be logged.

        :param dict vals: Values passed to ``write``.
        :return: Filtered field names that should create history rows.
        :rtype: list[str]
        """
        return [
            field_name
            for field_name in vals
            if field_name in self._fields
            and field_name not in HISTORY_WRITE_EXCLUDED_FIELDS
            and not self._fields[field_name].compute
            and self._fields[field_name].store
        ]

    @api.depends('expiry_date')
    def _compute_hijri_expiry_date_display(self):
        """Render the Gregorian expiry date as a Hijri date with month names."""
        for record in self:
            record.hijri_expiry_date_display = record._format_hijri_date(record.expiry_date)

    @api.depends('expiry_date')
    def _compute_is_expiring_soon(self):
        notification_days = self._get_notification_days()
        today = fields.Date.context_today(self)
        limit_date = today + timedelta(days=notification_days)
        for record in self:
            record.is_expiring_soon = bool(record.expiry_date and today <= record.expiry_date <= limit_date)

    @api.depends('employee_id', 'iqama_type_id')
    def _compute_submission_form_ready(self):
        """Show the full submission form only after the basic request inputs are selected."""
        for record in self:
            record.submission_form_ready = bool(record.employee_id and record.iqama_type_id)

    @api.model
    def _prepare_employee_profile_vals(self, employee):
        """Collect residency request profile fields from the selected employee."""
        if not employee:
            return {}

        return {
            'job_title': employee.job_title or '',
            'department_id': employee.department_id.id or False,
            'company_id': employee.company_id.id or self.env.company.id,
            'passport_name_english': employee.passport_name_english or employee.name or '',
            'passport_name_arabic': employee.passport_name_arabic or '',
            'nationality_id': employee.country_id.id if employee.country_id else False,
            'religion': employee.religion or '',
            'date_of_birth': employee.birthday if 'birthday' in employee._fields else False,
            'passport_profession': employee.passport_profession or '',
        }

    def _sync_employee_profile_from_employee(self):
        """Refresh mirrored employee profile fields on linked requests.

        This keeps the request's employee data snapshot aligned with the
        current employee record even after the request has been created.
        """
        for record in self.filtered('employee_id'):
            profile_vals = record._prepare_employee_profile_vals(record.employee_id)
            if profile_vals:
                record.with_context(
                    bypass_iqama_lock=True,
                    skip_iqama_history=True,
                ).write(profile_vals)

    @api.onchange('request_country_id')
    def _onchange_request_country_id(self):
        """Reset the visa type when the selected country changes."""
        for record in self:
            if record.iqama_type_id and record.iqama_type_id.country_id != record.request_country_id:
                record.iqama_type_id = False
                record.attachment_ids = [(5, 0, 0)]

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Copy the available employee details into the iqama record."""
        for record in self:
            employee = record.employee_id
            if not employee:
                continue
            record.update(record._prepare_employee_profile_vals(employee))

    @api.model
    def _generate_request_number(self, country):
        """Generate the next request number for the given country and year."""
        country_code = (country.code or 'XX').upper()
        current_year = fields.Date.context_today(self).year
        prefix = f'{country_code}{current_year}'
        last_request = self.search(
            [('request_number', '=like', f'{prefix}%')],
            order='request_number desc, id desc',
            limit=1,
        )
        last_sequence = int(last_request.request_number[-3:]) if last_request and last_request.request_number else 0
        return f'{prefix}{last_sequence + 1:03d}'

    def _ensure_request_number(self):
        """Assign a request number when the residency/visa type country is available."""
        for record in self.filtered(lambda request: not request.request_number and request.iqama_type_id.country_id):
            record.request_number = record._generate_request_number(record.iqama_type_id.country_id)

    def _set_processing_stage(self, stage):
        """Update the internal request step without triggering locked-state issues."""
        valid_stages = {key for key, _label in PROCESSING_STAGE_SELECTION}
        if stage not in valid_stages:
            raise ValidationError(_('Unsupported processing stage: %s') % stage)
        for record in self:
            current_furthest = record.furthest_processing_stage or 'submission'
            values = {'processing_stage': stage}
            if PROCESSING_STAGE_ORDER.get(stage, 0) > PROCESSING_STAGE_ORDER.get(current_furthest, 0):
                values['furthest_processing_stage'] = stage
            record.with_context(bypass_iqama_lock=True).write(values)

    @api.onchange('iqama_type_id')
    def _onchange_iqama_type_id(self):
        """Refresh the required document checklist when the residency/visa type changes."""
        for record in self:
            if record.iqama_type_id:
                record.request_country_id = record.iqama_type_id.country_id
            if record.id:
                record._sync_required_attachment_lines()
                continue
            required_lines = []
            for required_document in record.iqama_type_id.required_document_ids:
                required_lines.append((0, 0, {
                    'required_document_id': required_document.id,
                    'document_name': required_document.name,
                    'description': required_document.description,
                    'mandatory': required_document.mandatory,
                    'expiry_date_mandatory': required_document.expiry_date_mandatory,
                }))
            record.attachment_ids = [(5, 0, 0)] + required_lines

    @api.onchange('includes_family')
    def _onchange_includes_family(self):
        """Refresh family document checklist rows when family inclusion changes."""
        for record in self:
            if not record.includes_family:
                record.family_member_ids = [(5, 0, 0)]
                continue

    @api.model_create_multi
    def create(self, vals_list):
        """Create the iqama records and preload their required attachment checklist."""
        for vals in vals_list:
            employee_id = vals.get('employee_id')
            if employee_id:
                employee_profile_vals = self._prepare_employee_profile_vals(self.env['hr.employee'].browse(employee_id))
                for field_name, field_value in employee_profile_vals.items():
                    vals.setdefault(field_name, field_value)
        records = super().create(vals_list)
        records._ensure_request_number()
        records._sync_required_attachment_lines()
        records._sync_detail_lines()
        records._sync_approval_lines()
        processing_records = records.filtered(lambda request: request.state == 'under_processing')
        if processing_records:
            processing_records.with_context(bypass_iqama_lock=True).write({
                'furthest_processing_stage': 'iqama_details',
            })
        return records

    def write(self, vals):
        tracked_fields = self._tracked_history_field_names(vals)
        previous_values = {}
        if tracked_fields and not self.env.context.get('skip_iqama_history'):
            for record in self:
                previous_values[record.id] = {
                    field_name: record._value_to_history_text(field_name)
                    for field_name in tracked_fields
                }
        previous_states = {record.id: record.state for record in self}
        previous_processing_stages = {record.id: record.processing_stage for record in self}
        self._check_locked_state_write(vals)
        if 'employee_id' in vals and vals['employee_id']:
            employee_profile_vals = self._prepare_employee_profile_vals(self.env['hr.employee'].browse(vals['employee_id']))
            for field_name, field_value in employee_profile_vals.items():
                vals.setdefault(field_name, field_value)
        if 'processing_stage' in vals and not self.env.context.get('bypass_iqama_lock'):
            for record in self:
                previous_stage = previous_processing_stages.get(record.id)
                next_stage = vals.get('processing_stage')
                if (
                    record.state == 'under_processing'
                    and previous_stage == 'iqama_details'
                    and next_stage
                    and next_stage != 'iqama_details'
                ):
                    record._validate_iqama_details_before_fees()
                    record._validate_attachments_for_stage(next_stage)
                    record._validate_family_documents_for_stage(next_stage)
        result = super().write(vals)
        self._ensure_request_number()
        if 'employee_id' in vals or 'iqama_type_id' in vals or 'includes_family' in vals:
            self._sync_required_attachment_lines()
        if not self.env.context.get('skip_iqama_detail_line_sync') and {
            'employee_id',
            'iqama_number',
            'serial_number',
            'issue_place',
            'issue_date',
            'expiry_date',
            'arrival_date',
            'currently_in_kingdom',
            'requires_travel',
            'multiple_entry_exit',
            'iqama_cost',
            'currency_id',
        } & set(vals):
            self._sync_detail_lines()
        if 'employee_id' in vals:
            self.filtered(lambda request: request.state == 'new')._sync_approval_lines()
        if 'state' in vals:
            self._notify_status_changes(previous_states)
        if 'state' in vals:
            processing_records = self.filtered(lambda request: request.state == 'under_processing')
            if processing_records:
                processing_records.with_context(bypass_iqama_lock=True).write({
                    'furthest_processing_stage': 'iqama_details',
                })
            active_records = self.filtered(lambda request: request.state == 'active')
            if active_records:
                active_records.with_context(bypass_iqama_lock=True).write({
                    'furthest_processing_stage': 'completed',
                })
        if previous_values and not self.env.context.get('skip_iqama_history'):
            history_vals = []
            for record in self:
                record_previous_values = previous_values.get(record.id, {})
                for field_name in tracked_fields:
                    old_value = record_previous_values.get(field_name)
                    new_value = record._value_to_history_text(field_name)
                    if old_value != new_value:
                        history_vals.append({
                            'iqama_id': record.id,
                            'changed_by_id': self.env.user.id,
                            'field_name': self._fields[field_name].string or field_name,
                            'from_value': old_value,
                            'to_value': new_value,
                        })
            if history_vals:
                self.env['hr.iqama.history'].sudo().create(history_vals)
        return result

    @api.model
    def _locked_states(self):
        """Return the residency/visa request states that forbid further edits."""
        return LOCKED_STATES

    def _check_locked_state_write(self, vals):
        """Prevent edits on final states unless the write is explicitly bypassed."""
        if self.env.context.get('bypass_iqama_lock'):
            return
        non_mail_fields = set(vals) - MAIL_WRITE_FIELDS
        if not non_mail_fields:
            return
        locked_records = self.filtered(lambda record: record.state in LOCKED_STATES)
        if locked_records:
            active_records = locked_records.filtered(lambda record: record.state == 'active')
            non_active_locked_records = locked_records - active_records
            if active_records and not non_active_locked_records and non_mail_fields.issubset(ACTIVE_ALLOWED_WRITE_FIELDS):
                return
            raise ValidationError(_('Locked requests cannot be edited in Active, Cancelled, Rejected, or Expired status.'))

    def name_get(self):
        result = []
        for record in self:
            label = record.request_number or _('New')
            result.append((record.id, label))
        return result

    def _sync_required_attachment_lines(self):
        """Sync the checklist rows with the selected residency/visa type configuration."""
        for record in self:
            if not record.iqama_type_id:
                continue
            valid_required_documents = record.iqama_type_id.required_document_ids
            legacy_lines = record.attachment_ids.filtered(lambda line: not line.required_document_id)
            for legacy_line in legacy_lines:
                if legacy_line.attachment:
                    legacy_line.write({
                        'document_name': legacy_line.document_name or legacy_line.attachment_filename or _('Legacy Attachment'),
                        'mandatory': False,
                    })
                    continue
                legacy_line.unlink()
            obsolete_required_lines = record.attachment_ids.filtered(
                lambda line: line.required_document_id and line.required_document_id not in valid_required_documents
            )
            for obsolete_line in obsolete_required_lines:
                if obsolete_line.attachment:
                    obsolete_line.write({
                        'required_document_id': False,
                        'mandatory': False,
                        'document_name': obsolete_line.document_name or obsolete_line.attachment_filename or _('Legacy Attachment'),
                    })
                    continue
                obsolete_line.unlink()
            existing_document_ids = {
                line.required_document_id.id: line
                for line in record.attachment_ids.filtered('required_document_id')
            }
            lines_to_create = []
            for required_document in valid_required_documents:
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
                    'iqama_id': record.id,
                    'required_document_id': required_document.id,
                    'is_manual_line': False,
                    **values,
                })
            if lines_to_create:
                self.env['hr.iqama.attachment'].create(lines_to_create)
            record.family_member_ids._sync_required_document_lines()

    def _prepare_detail_line_vals(self, line_type, family_member=None):
        """Build the synchronized detail-line values for the employee or a family member."""
        self.ensure_one()
        if line_type == 'employee':
            return {
                'line_type': 'employee',
                'employee_id': self.employee_id.id,
                'family_member_id': False,
                'iqama_number': self.iqama_number,
                'serial_number': self.serial_number,
                'issue_place': self.issue_place,
                'issue_date': self.issue_date,
                'expiry_date': self.expiry_date,
                'arrival_date': self.arrival_date,
                'currently_in_kingdom': self.currently_in_kingdom,
                'requires_travel': self.requires_travel,
                'multiple_entry_exit': self.multiple_entry_exit,
                'iqama_cost': self.iqama_cost,
                'currency_id': self.currency_id.id,
            }
        return {
            'line_type': 'family',
            'employee_id': False,
            'family_member_id': family_member.id,
            'currency_id': self.currency_id.id,
        }

    def _sync_detail_lines(self):
        """Keep the IQAMA detail lines aligned with the employee and family roster."""
        detail_line_model = self.env['hr.iqama.detail.line']
        for record in self:
            employee_line = record.detail_line_ids.filtered(lambda line: line.line_type == 'employee')[:1]
            if record.employee_id:
                employee_values = record._prepare_detail_line_vals('employee')
                if employee_line:
                    employee_line.with_context(skip_iqama_parent_sync=True).write(employee_values)
                else:
                    detail_line_model.with_context(skip_iqama_parent_sync=True).create({
                        'iqama_id': record.id,
                        **employee_values,
                    })

            family_lines = record.detail_line_ids.filtered(lambda line: line.line_type == 'family')
            family_lines_by_member = {
                line.family_member_id.id: line
                for line in family_lines.filtered('family_member_id')
            }
            active_family_member_ids = set(record.family_member_ids.ids)
            obsolete_family_lines = family_lines.filtered(
                lambda line: line.family_member_id.id not in active_family_member_ids
            )
            if obsolete_family_lines:
                obsolete_family_lines.with_context(allow_iqama_detail_line_unlink=True).unlink()

            for family_member in record.family_member_ids:
                family_values = record._prepare_detail_line_vals('family', family_member=family_member)
                existing_family_line = family_lines_by_member.get(family_member.id)
                if existing_family_line:
                    existing_family_line.with_context(skip_iqama_parent_sync=True).write(family_values)
                    continue
                detail_line_model.with_context(skip_iqama_parent_sync=True).create({
                    'iqama_id': record.id,
                    **family_values,
                })

    def _validate_iqama_detail_lines(self):
        """Ensure the synced IQAMA detail line for every person is complete."""
        for record in self:
            expected_line_count = 1 + len(record.family_member_ids)
            if len(record.detail_line_ids) != expected_line_count:
                record._sync_detail_lines()
            detail_lines = record.detail_line_ids
            if len(detail_lines) != expected_line_count:
                raise ValidationError(_('The IQAMA detail lines are not fully synchronized yet.'))
            detail_lines._validate_required_details()

    def _sync_approval_lines(self):
        """Sync approval lines from the employee configured residency approvers."""
        approval_model = self.env['hr.iqama.approval']
        for record in self:
            approvers = record.employee_id.residency_approver_ids
            existing_lines = {
                line.approver_id.id: line
                for line in record.approval_line_ids
            }
            lines_to_create = []
            for approver in approvers:
                if approver.id in existing_lines:
                    continue
                lines_to_create.append({
                    'iqama_id': record.id,
                    'approver_id': approver.id,
                })
            if lines_to_create:
                approval_model.create(lines_to_create)
            if record.state == 'new':
                obsolete_lines = record.approval_line_ids.filtered(
                    lambda line: line.approver_id not in approvers
                )
                if obsolete_lines:
                    obsolete_lines.unlink()

    def _get_current_user_pending_approval_line(self):
        """Return the current user's pending approval line for this request."""
        self.ensure_one()
        return self.approval_line_ids.filtered(
            lambda line: line.approver_id == self.env.user and line.status == 'pending'
        )[:1]

    def _validate_current_user_can_review(self, action_label):
        """Ensure the current user is one of the pending approvers when approvals are required."""
        for record in self:
            if not record.approval_required:
                continue
            pending_line = record._get_current_user_pending_approval_line()
            if not pending_line:
                raise UserError(
                    _('You cannot %(action)s this request because you are not one of the pending approvers.')
                    % {'action': action_label}
                )

    def _move_to_under_processing_if_ready(self):
        """Move approved requests to Under Processing once all approvals are completed."""
        for record in self:
            pending_count = len(record.approval_line_ids.filtered(lambda line: line.status == 'pending'))
            approved_count = len(record.approval_line_ids.filtered(lambda line: line.status == 'approved'))
            if record.approval_required and pending_count:
                record.message_post(
                    body=_(
                        '%(approved)s approver(s) approved this request. %(pending)s approval(s) are still pending.'
                    ) % {
                        'approved': approved_count,
                        'pending': pending_count,
                    }
                )
                continue
            record._validate_attachments_for_stage('under_processing')
            record.write({
                'state': 'under_processing',
                'processing_stage': 'iqama_details',
            })

    def _get_stage_label(self, stage):
        selection_labels = dict(self._fields['state']._description_selection(self.env))
        return selection_labels.get(stage, stage)

    def _gregorian_to_jd(self, year, month, day):
        """Convert a Gregorian date to Julian day number."""
        a = (14 - month) // 12
        y = year + 4800 - a
        m = month + 12 * a - 3
        return day + ((153 * m + 2) // 5) + (365 * y) + (y // 4) - (y // 100) + (y // 400) - 32045

    def _jd_to_hijri(self, julian_day):
        """Convert a Julian day number to an Islamic civil calendar date."""
        l = julian_day - 1948440 + 10632
        n = (l - 1) // 10631
        l = l - 10631 * n + 354
        j = (
            ((10985 - l) // 5316)
            * ((50 * l) // 17719)
            + (l // 5670)
            * ((43 * l) // 15238)
        )
        l = l - (((30 - j) // 15) * ((17719 * j) // 50)) - ((j // 16) * ((15238 * j) // 43)) + 29
        month = (24 * l) // 709
        day = l - (709 * month) // 24
        year = 30 * n + j - 30
        return year, month, day

    def _format_hijri_date(self, date_value):
        """Return a human-readable Hijri date string such as '10 Ramadan 1447'."""
        if not date_value:
            return False
        if isinstance(date_value, str):
            date_value = fields.Date.from_string(date_value)
        julian_day = self._gregorian_to_jd(date_value.year, date_value.month, date_value.day)
        year, month, day = self._jd_to_hijri(julian_day)
        month_map = HIJRI_MONTHS_AR if self.env.lang and self.env.lang.startswith('ar') else HIJRI_MONTHS_EN
        month_name = month_map.get(month, str(month))
        return '%s %s %s' % (day, month_name, year)

    def _get_missing_attachments(self):
        """Return the missing mandatory document labels for the selected residency/visa type."""
        self.ensure_one()
        return self.attachment_ids.filtered(
            lambda line: line.mandatory and line.status != 'uploaded'
        ).mapped('document_name')

    def _validate_attachments_for_stage(self, target_state):
        """Block a stage transition when one or more mandatory documents are still missing."""
        for record in self:
            if not record.iqama_type_id:
                raise ValidationError(
                    _('Please select a residency/visa type before moving this record to %s.')
                    % record._get_stage_label(target_state)
                )
            missing_documents = record._get_missing_attachments()
            if missing_documents:
                raise ValidationError(_(
                    'You cannot move %(employee)s to %(stage)s because the following mandatory documents are missing:\n- %(documents)s'
                ) % {
                    'employee': record.employee_id.name,
                    'stage': record._get_stage_label(target_state),
                    'documents': '\n- '.join(missing_documents),
                })

    def _validate_family_documents_for_stage(self, target_stage):
        """Ensure each family member has its required documents uploaded before stage transitions."""
        for record in self:
            if not record.includes_family:
                continue
            for family_member in record.family_member_ids:
                if not family_member.name or not family_member.passport_number:
                    raise ValidationError(_(
                        'Each family member must include both Family Member and Passport Number before moving to %s.'
                    ) % record._get_stage_label(target_stage))
                missing_documents = family_member.document_ids.filtered(
                    lambda line: line.mandatory and line.status != 'uploaded'
                ).mapped('document_name')
                if missing_documents:
                    raise ValidationError(_(
                        'You cannot move this request to %(stage)s because %(family_member)s is still missing these required documents:\n- %(documents)s'
                    ) % {
                        'stage': record._get_stage_label(target_stage),
                        'family_member': family_member.name,
                        'documents': '\n- '.join(missing_documents),
                    })

    def _validate_family_documents_before_review(self):
        """Ensure each family member has its required documents uploaded before review."""
        for record in self:
            if not record.includes_family:
                continue
            if not record.family_member_ids:
                raise ValidationError(_(
                    'You cannot submit this request because at least one family member line is required.'
                ))
            for family_member in record.family_member_ids:
                if not family_member.name or not family_member.passport_number:
                    raise ValidationError(_(
                        'Each family member must include both Family Member and Passport Number before submission.'
                    ))
                missing_documents = family_member.document_ids.filtered(
                    lambda line: line.mandatory and line.status != 'uploaded'
                ).mapped('document_name')
                if missing_documents:
                    raise ValidationError(_(
                        'You cannot submit this request because %(family_member)s is still missing these required documents:\n- %(documents)s'
                    ) % {
                        'family_member': family_member.name,
                        'documents': '\n- '.join(missing_documents),
                    })

    def _validate_required_fields_for_active(self):
        """Ensure the request has all core values before activation."""
        required_fields = {
            'request_number': _('Request Number'),
            'employee_id': _('Employee'),
            'iqama_type_id': _('Residency/Visa Type'),
            'application_date': _('Application Date'),
            'iqama_number': _('Visa/Residency Number'),
            'serial_number': _('Serial Number'),
            'issue_date': _('Issue Date'),
            'issue_place': _('Issue Place'),
            'expiry_date': _('Expiry Date'),
        }
        for record in self:
            missing_labels = [label for field_name, label in required_fields.items() if not record[field_name]]
            if missing_labels:
                raise ValidationError(
                    _('You cannot activate this request until all required fields are completed:\n- %s')
                    % '\n- '.join(missing_labels)
                )

    def _validate_iqama_details_before_fees(self):
        """Ensure the iqama details step is complete before moving to fees."""
        self._validate_iqama_detail_lines()

    def _validate_fees_before_active(self):
        """Ensure fee lines are complete before activating the request."""
        required_fee_fields = {
            'expense_type_id': _('Expense Type'),
            'claim_date': _('Claim Date'),
            'amount': _('Amount'),
            'currency_id': _('Currency'),
        }
        for record in self:
            if not record.fee_line_ids:
                raise ValidationError(_('You cannot activate this request until at least one fee line is added.'))
            for fee_line in record.fee_line_ids:
                missing_labels = []
                for field_name, label in required_fee_fields.items():
                    field_value = fee_line[field_name]
                    if field_name == 'amount':
                        if not field_value or field_value <= 0:
                            missing_labels.append(label)
                    elif not field_value:
                        missing_labels.append(label)
                if missing_labels:
                    raise ValidationError(_(
                        'You cannot activate this request until all fee lines are completed.\n'
                        'Missing fields on one fee line:\n- %s'
                    ) % '\n- '.join(missing_labels))

    def _validate_security_review_for_active(self):
        """Ensure the security review questionnaire is answered before activation."""
        question_labels = {
            'security_question_identity_verified': _('Identity documents verified'),
            'security_question_employee_clear': _('Employee passed internal security review'),
            'security_question_no_restrictions': _('No travel or residency restrictions found'),
        }
        for record in self:
            missing_labels = [
                label for field_name, label in question_labels.items() if not record[field_name]
            ]
            if missing_labels:
                raise ValidationError(
                    _('You cannot activate this request until all security review questions are answered:\n- %s')
                    % '\n- '.join(missing_labels)
                )

    def action_go_to_iqama_details(self):
        """Open the iqama details step once the request enters processing."""
        self.filtered(lambda record: record.state == 'under_processing')._set_processing_stage('iqama_details')
        return self._open_current_form()

    def action_go_to_fees(self):
        """Move the UI to the fees step after iqama details are ready."""
        for record in self:
            if record.state != 'under_processing':
                continue
            record._validate_iqama_details_before_fees()
            record._validate_attachments_for_stage('fees')
            record._validate_family_documents_for_stage('fees')
        self.filtered(lambda record: record.state == 'under_processing')._set_processing_stage('fees')
        return self._open_current_form()

    def action_go_to_security_review(self):
        """Move the UI to the security review step after fees are prepared."""
        self.filtered(lambda record: record.state == 'under_processing')._set_processing_stage('security_review')
        return self._open_current_form()

    def _open_current_form(self):
        """Reload the current form without opening a nested breadcrumb entry."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_submit_for_review(self):
        self._validate_family_documents_before_review()
        self._set_processing_stage('submission')
        self._sync_approval_lines()
        self.write({'state': 'under_review'})
        for record in self.filtered('approval_required'):
            approver_names = ', '.join(record.approval_line_ids.mapped('approver_id.name'))
            record.message_post(
                body=_('Approval routing started. Waiting for: %s') % approver_names
            )

    def action_approve(self):
        self._validate_current_user_can_review(_('approve'))
        for record in self:
            pending_line = record._get_current_user_pending_approval_line()
            if pending_line:
                pending_line.action_mark_approved()
        self._move_to_under_processing_if_ready()

    def action_mark_under_processing(self):
        self._validate_attachments_for_stage('under_processing')
        self.write({
            'state': 'under_processing',
            'processing_stage': 'iqama_details',
        })

    def action_activate(self):
        self._validate_attachments_for_stage('active')
        self._validate_iqama_detail_lines()
        self._validate_security_review_for_active()
        self.with_context(bypass_iqama_lock=True).write({
            'state': 'active',
            'processing_stage': 'completed',
        })

    def action_reject(self):
        self.filtered(lambda request: request.state == 'under_review')._validate_current_user_can_review(_('reject'))
        for record in self.filtered(lambda request: request.state == 'under_review'):
            pending_line = record._get_current_user_pending_approval_line()
            if pending_line:
                pending_line.action_mark_rejected()
        self.with_context(bypass_iqama_lock=True).write({
            'state': 'rejected',
            'processing_stage': 'submission',
        })

    def action_cancel(self):
        self.with_context(bypass_iqama_lock=True).write({
            'state': 'cancelled',
            'processing_stage': 'submission',
        })

    def action_view_attachments(self):
        """Open the related attachments for the current iqama."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Residency/Visa Attachments'),
            'res_model': 'hr.iqama.attachment',
            'view_mode': 'list,form',
            'domain': [('iqama_id', '=', self.id)],
            'context': {'default_iqama_id': self.id},
        }

    def action_create_travel_request(self):
        """Create a travel request in the expenses module using request details."""
        self.ensure_one()
        if not self.requires_travel:
            raise UserError(_('Travel request creation is only available when Requires Travel is enabled.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Travel Request'),
            'res_model': 'hr.expense',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_iqama_request_id': self.id,
                'default_name': _('%s Travel Request') % (self.request_number or self.employee_id.name or _('Residency/Visa')),
                'default_employee_id': self.employee_id.id,
                'default_date': self.application_date or fields.Date.context_today(self),
                'default_currency_id': self.currency_id.id,
                'default_total_amount': self.iqama_cost or 0.0,
            },
        }

    def action_view_travel_request(self):
        """Open the linked travel request."""
        self.ensure_one()
        if not self.travel_expense_ids:
            raise UserError(_('There is no linked travel request yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Travel Requests'),
            'res_model': 'hr.expense',
            'view_mode': 'list,form',
            'domain': [('iqama_request_id', '=', self.id)],
            'context': {'default_iqama_request_id': self.id},
        }

    def _notify_status_changes(self, previous_states):
        """Notify the employee by email and system message whenever the status changes."""
        mail_model = self.env['mail.mail'].sudo()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', default='')
        for record in self:
            previous_state = previous_states.get(record.id)
            if not previous_state or previous_state == record.state:
                continue
            employee_partner = record.employee_id.user_id.partner_id
            old_label = dict(self._fields['state']._description_selection(self.env)).get(previous_state, previous_state)
            new_label = record._get_status_label()
            message_body = _(
                'Request %(request)s for %(employee)s changed from %(old_status)s to %(new_status)s.'
            ) % {
                'request': record.request_number or record.display_name,
                'employee': record.employee_id.name,
                'old_status': old_label,
                'new_status': new_label,
            }
            record.message_post(
                body=message_body,
                partner_ids=[employee_partner.id] if employee_partner else [],
            )
            if employee_partner and employee_partner.email:
                body_html = _(
                    '<p>Your residency/visa request <strong>%(request)s</strong> status changed from '
                    '<strong>%(old_status)s</strong> to <strong>%(new_status)s</strong>.</p>'
                    '<p><a href="%(url)s">Open Request</a></p>'
                ) % {
                    'request': record.request_number or record.display_name,
                    'old_status': old_label,
                    'new_status': new_label,
                    'url': '%s/web#id=%s&model=hr.iqama&view_type=form' % (base_url, record.id),
                }
                mail_model.create({
                    'subject': _('Residency/Visa Request Status Updated: %s') % (record.request_number or record.display_name),
                    'body_html': body_html,
                    'email_to': employee_partner.email,
                    'auto_delete': True,
                    'model': 'hr.iqama',
                    'res_id': record.id,
                }).send()

    @api.model
    def _get_notification_days(self):
        """Return the configured number of days before expiry for reminders."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'hr_iqama.notification_days_before_expiry',
            default='30',
        )
        try:
            notification_days = int(value)
        except (TypeError, ValueError):
            notification_days = 30
        return max(notification_days, 0)

    def _get_expiry_notification_days(self):
        """Return type-specific expiry notification days, falling back to the global setting."""
        self.ensure_one()
        if self.iqama_type_id and self.iqama_type_id.expiry_notification_days is not None:
            return max(self.iqama_type_id.expiry_notification_days, 0)
        return self._get_notification_days()

    @api.model
    def _search_is_expiring_soon(self, operator, value):
        """Search iqamas that fall within the configured reminder window."""
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('The "Expiring Soon" filter only supports boolean checks.'))
        notification_days = self._get_notification_days()
        today = fields.Date.context_today(self)
        limit_date = today + timedelta(days=notification_days)
        positive_domain = [
            ('expiry_date', '!=', False),
            ('expiry_date', '>=', today),
            ('expiry_date', '<=', limit_date),
        ]
        negative_domain = [
            '|',
            ('expiry_date', '=', False),
            '|',
            ('expiry_date', '<', today),
            ('expiry_date', '>', limit_date),
        ]
        return negative_domain if (operator == '=' and not value) or (operator == '!=' and value) else positive_domain

    def _get_notification_partners(self):
        """Collect employee, direct manager, and HR manager partners for reminders."""
        self.ensure_one()
        partners = self.env['res.partner']
        if self.employee_id.user_id.partner_id:
            partners |= self.employee_id.user_id.partner_id
        if self.employee_id.parent_id.user_id.partner_id:
            partners |= self.employee_id.parent_id.user_id.partner_id
        hr_manager_group = self.env.ref('hr.group_hr_manager', raise_if_not_found=False)
        if hr_manager_group:
            partners |= hr_manager_group.users.mapped('partner_id')
        return partners.filtered(lambda partner: partner.email)

    def _send_expiry_notification_email(self):
        """Send a direct email to all reminder recipients for an expiring iqama."""
        mail_model = self.env['mail.mail'].sudo()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', default='')
        for record in self:
            partners = record._get_notification_partners()
            if not partners:
                continue
            subject = _('Iqama expiry reminder for %s') % record.employee_id.name
            body_html = _(
                '<p>The iqama <strong>%(iqama)s</strong> for <strong>%(employee)s</strong> is expiring on '
                '<strong>%(expiry)s</strong>.</p>'
                '<p>Please review and renew the required documents.</p>'
                '<p><a href="%(url)s">Open Iqama Record</a></p>'
            ) % {
                'iqama': record.iqama_number,
                'employee': record.employee_id.name,
                'expiry': record.expiry_date or '',
                'url': '%s/web#id=%s&model=hr.iqama&view_type=form' % (base_url, record.id),
            }
            mail_values = {
                'subject': subject,
                'body_html': body_html,
                'email_to': ','.join(partners.mapped('email')),
                'auto_delete': True,
                'model': 'hr.iqama',
                'res_id': record.id,
            }
            mail_model.create(mail_values).send()
            record.message_post(
                body=_(
                    'Expiry reminder sent for request %(request)s with expiry date %(expiry)s.'
                ) % {
                    'request': record.request_number or record.display_name,
                    'expiry': record.expiry_date or '',
                },
                partner_ids=partners.ids,
            )

    def _schedule_expiry_activity(self):
        """Create one todo activity per iqama to keep HR follow-up visible."""
        todo_type = self.env.ref('mail.mail_activity_data_todo')
        for record in self:
            existing_activity = self.env['mail.activity'].search([
                ('res_model', '=', 'hr.iqama'),
                ('res_id', '=', record.id),
                ('activity_type_id', '=', todo_type.id),
                ('summary', '=', _('Iqama Expiry Follow-up')),
                ('date_deadline', '=', record.expiry_date),
            ], limit=1)
            if existing_activity:
                continue
            user = record.employee_id.parent_id.user_id or self.env.user
            record.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                summary=_('Iqama Expiry Follow-up'),
                note=_('The iqama for %s is approaching its expiry date.') % record.employee_id.name,
                date_deadline=record.expiry_date,
            )

    @api.model
    def _cron_notify_expiring_iqamas(self):
        """Find iqamas nearing expiry and trigger emails plus activity reminders."""
        self._cron_mark_expired_requests()
        today = fields.Date.context_today(self)
        iqamas = self.search([
            ('state', 'in', ['under_processing', 'active']),
            ('expiry_date', '!=', False),
            ('expiry_date', '>=', today),
        ]).filtered(
            lambda record: record.expiry_date <= today + timedelta(days=record._get_expiry_notification_days())
        )
        iqamas._send_expiry_notification_email()
        iqamas._schedule_expiry_activity()

    @api.model
    def _cron_mark_expired_requests(self):
        """Automatically set expired requests when the expiry date is in the past."""
        today = fields.Date.context_today(self)
        expired_requests = self.search([
            ('state', 'not in', ['cancelled', 'rejected', 'expired']),
            ('expiry_date', '!=', False),
            ('expiry_date', '<', today),
        ])
        if expired_requests:
            expired_requests.with_context(bypass_iqama_lock=True).write({'state': 'expired'})
