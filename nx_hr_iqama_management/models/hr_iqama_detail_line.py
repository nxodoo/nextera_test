from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


LOCKED_REQUEST_STATES = {'active', 'cancelled', 'rejected', 'expired'}


class HrIqamaDetailLine(models.Model):
    _name = 'hr.iqama.detail.line'
    _description = 'Residency/Visa Detail Line'
    _order = 'line_type, id'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
        ondelete='cascade',
    )
    line_type = fields.Selection(
        [('employee', 'Employee'), ('family', 'Family Member')],
        string='Line Type',
        required=True,
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        readonly=True,
    )
    family_member_id = fields.Many2one(
        'hr.iqama.family.member',
        string='Family Member',
        ondelete='cascade',
        readonly=True,
    )
    person_name = fields.Char(
        string='Name',
        compute='_compute_person_labels',
        store=True,
    )
    type_label = fields.Char(
        string='Type',
        compute='_compute_person_labels',
        store=True,
    )
    iqama_number = fields.Char(string='Visa/Residency Number')
    serial_number = fields.Char(string='Serial Number')
    issue_place = fields.Char(string='Issue Place')
    issue_date = fields.Date(string='Issue Date')
    expiry_date = fields.Date(string='Expiry Date')
    hijri_expiry_date_display = fields.Char(
        string='Hijri Expiry Date',
        compute='_compute_hijri_expiry_date_display',
    )
    arrival_date = fields.Date(string='Entry Date')
    currently_in_kingdom = fields.Boolean(string='Currently Inside Country')
    requires_travel = fields.Boolean(string='Requires Travel')
    multiple_entry_exit = fields.Boolean(string='Multiple Entry Exit')
    iqama_cost = fields.Monetary(string='Iqama Cost', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    details_complete = fields.Boolean(
        string='Details Complete',
        compute='_compute_details_complete',
        store=True,
    )

    @api.depends('line_type', 'employee_id.name', 'family_member_id.name', 'family_member_id.passport_name')
    def _compute_person_labels(self):
        for record in self:
            if record.line_type == 'employee':
                record.person_name = record.employee_id.name or ''
                record.type_label = _('Employee')
                continue
            record.person_name = (
                record.family_member_id.passport_name
                or record.family_member_id.arabic_name
                or record.family_member_id.name
                or ''
            )
            record.type_label = record.family_member_id.name or _('Family Member')

    @api.depends('expiry_date')
    def _compute_hijri_expiry_date_display(self):
        for record in self:
            record.hijri_expiry_date_display = record.iqama_id._format_hijri_date(record.expiry_date)

    @api.depends('iqama_number', 'serial_number', 'issue_place', 'issue_date', 'expiry_date')
    def _compute_details_complete(self):
        required_fields = ('iqama_number', 'serial_number', 'issue_place', 'issue_date', 'expiry_date')
        for record in self:
            record.details_complete = all(record[field_name] for field_name in required_fields)

    @api.constrains('issue_date', 'expiry_date')
    def _check_expiry_date_not_before_issue_date(self):
        for record in self:
            if record.issue_date and record.expiry_date and record.expiry_date < record.issue_date:
                raise ValidationError(_('Expiry Date cannot be earlier than Issue Date.'))

    @api.onchange('issue_date', 'expiry_date')
    def _onchange_validate_issue_and_expiry_date(self):
        """Prevent keeping an expiry date earlier than the selected issue date."""
        for record in self:
            if record.issue_date and record.expiry_date and record.expiry_date < record.issue_date:
                record.expiry_date = False
                return {
                    'warning': {
                        'title': _('Invalid Date Range'),
                        'message': _('Expiry Date cannot be earlier than Issue Date.'),
                    }
                }

    def _validate_required_details(self):
        """Ensure each detail line contains the required iqama fields."""
        required_fields = {
            'iqama_number': _('Visa/Residency Number'),
            'serial_number': _('Serial Number'),
            'issue_place': _('Issue Place'),
            'issue_date': _('Issue Date'),
            'expiry_date': _('Expiry Date'),
        }
        for record in self:
            missing_labels = [label for field_name, label in required_fields.items() if not record[field_name]]
            if missing_labels:
                raise ValidationError(
                    _('You cannot continue until all iqama details are completed for %(name)s:\n- %(fields)s')
                    % {
                        'name': record.person_name or record.type_label,
                        'fields': '\n- '.join(missing_labels),
                    }
                )

    def _validate_details_before_save(self):
        """Block saving partial IQAMA details while the request is under processing."""
        processing_lines = self.filtered(lambda line: line.iqama_id.state == 'under_processing')
        if processing_lines:
            processing_lines._validate_required_details()

    def _sync_parent_employee_fields(self):
        """Keep the main iqama record aligned with the employee detail line."""
        for record in self.filtered(lambda line: line.line_type == 'employee' and line.iqama_id):
            record.iqama_id.with_context(
                skip_iqama_history=True,
                skip_iqama_detail_line_sync=True,
            ).write({
                'iqama_number': record.iqama_number,
                'serial_number': record.serial_number,
                'issue_place': record.issue_place,
                'issue_date': record.issue_date,
                'expiry_date': record.expiry_date,
                'arrival_date': record.arrival_date,
                'currently_in_kingdom': record.currently_in_kingdom,
                'requires_travel': record.requires_travel,
                'multiple_entry_exit': record.multiple_entry_exit,
                'iqama_cost': record.iqama_cost,
                'currency_id': record.currency_id.id,
            })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            iqama = self.env['hr.iqama'].browse(vals.get('iqama_id'))
            if iqama and iqama.state in LOCKED_REQUEST_STATES:
                raise ValidationError(_('You cannot modify iqama details for a locked residency/visa request.'))
        records = super().create(vals_list)
        if not self.env.context.get('skip_iqama_parent_sync'):
            records._sync_parent_employee_fields()
        return records

    def write(self, vals):
        if any(record.iqama_id.state in LOCKED_REQUEST_STATES for record in self):
            raise ValidationError(_('You cannot modify iqama details for a locked residency/visa request.'))
        result = super().write(vals)
        self._validate_details_before_save()
        if not self.env.context.get('skip_iqama_parent_sync'):
            self._sync_parent_employee_fields()
        return result

    def unlink(self):
        if not self.env.context.get('allow_iqama_detail_line_unlink'):
            raise ValidationError(_('Iqama detail lines are managed automatically and cannot be deleted.'))
        return super().unlink()

    def action_open_details_form(self):
        """Open the selected iqama detail line in a popup form."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('IQAMA Details'),
            'res_model': 'hr.iqama.detail.line',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {
                'form_view_initial_mode': 'edit',
            },
        }
