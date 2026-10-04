# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from ..services import context as audit_context
from ..services import integrity

CHANGE_TYPES = [
    ('set', 'Set'), ('change', 'Change'), ('clear', 'Clear'),
    ('add', 'Added'), ('remove', 'Removed'),
    ('create_child', 'Line Created'), ('update_child', 'Line Updated'),
    ('delete_child', 'Line Deleted'),
]


class AuditLogLine(models.Model):
    _name = 'audit.log.line'
    _description = 'Audit Field Change'
    _order = 'audit_log_id desc, sequence, id'

    audit_log_id = fields.Many2one('audit.log', required=True, ondelete='cascade', index=True,
                                   readonly=True)
    sequence = fields.Integer(readonly=True)
    event_datetime = fields.Datetime(related='audit_log_id.event_datetime', store=True, index=True)
    operation = fields.Selection(related='audit_log_id.operation', store=True)
    user_id = fields.Many2one(related='audit_log_id.user_id', store=True, index=True)
    res_id = fields.Many2oneReference(related='audit_log_id.res_id', model_field='model_name')
    model_name = fields.Char(readonly=True, index=True)
    field_name = fields.Char(required=True, index=True, readonly=True)
    field_label = fields.Char(readonly=True)
    field_type = fields.Char(readonly=True)
    field_id = fields.Many2one('ir.model.fields', ondelete='set null', readonly=True)
    related_model = fields.Char(readonly=True)
    change_type = fields.Selection(CHANGE_TYPES, required=True, readonly=True)
    change_origin = fields.Selection(
        [('direct', 'Direct'), ('derived', 'Derived'), ('database_fk', 'Database cascade')],
        default='direct', readonly=True)
    lang = fields.Char('Language', readonly=True)
    old_value_text = fields.Char('Old Value', readonly=True)
    new_value_text = fields.Char('New Value', readonly=True)
    old_value_json = fields.Json(readonly=True)
    new_value_json = fields.Json(readonly=True)
    old_digest = fields.Char(readonly=True)
    new_digest = fields.Char(readonly=True)
    masked = fields.Boolean(readonly=True)
    personal = fields.Boolean('Personal Data', readonly=True)
    restricted = fields.Boolean(readonly=True, help="Source field is restricted to groups.")
    required_group_ids = fields.Many2many(
        'res.groups', 'audit_log_line_group_rel', 'line_id', 'group_id', readonly=True)
    redacted = fields.Boolean(readonly=True)
    redaction_id = fields.Many2one('audit.redaction.request', ondelete='restrict', readonly=True)

    @api.model
    def _line_vals(self, line, key):
        vals = dict(line)
        vals['old_digest'] = integrity.digest(key, line.get('old_value_json'))
        vals['new_digest'] = integrity.digest(key, line.get('new_value_json'))
        vals['required_group_ids'] = [(6, 0, line.get('required_group_ids') or [])]
        model_name = line.get('model_name')
        if model_name and model_name in self.env:
            field = self.env['ir.model.fields']._get(model_name, line['field_name'])
            vals['field_id'] = field.id or False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        if audit_context.privileged_operation() is None:
            raise AccessError(_("Audit evidence can only be created by the audit engine."))
        return super().create(vals_list)

    def write(self, vals):
        if audit_context.privileged_operation() not in ('persist', 'redact'):
            raise AccessError(_("Audit evidence is immutable."))
        if audit_context.privileged_operation() == 'redact' and not set(vals) <= {
                'old_value_json', 'new_value_json', 'old_value_text', 'new_value_text',
                'redacted', 'redaction_id'}:
            raise AccessError(_("Redaction can only replace values."))
        return super().write(vals)

    def unlink(self):
        if audit_context.privileged_operation() not in ('archive', 'purge', 'uninstall'):
            raise AccessError(_("Audit evidence cannot be deleted."))
        return super().unlink()

    def _plain(self):
        return {
            'id': self.id, 'field_name': self.field_name, 'change_type': self.change_type,
            'change_origin': self.change_origin, 'lang': self.lang, 'masked': self.masked,
            'old_digest': self.old_digest, 'new_digest': self.new_digest,
            'old_value_json': self.old_value_json, 'new_value_json': self.new_value_json,
            'old_value_text': self.old_value_text, 'new_value_text': self.new_value_text,
            'field_label': self.field_label, 'field_type': self.field_type,
            'redacted': self.redacted,
        }

    def _digest_mismatch(self, key):
        """True if a stored value no longer matches its digest (tampering)."""
        if self.redacted:
            return False
        return (integrity.digest(key, self.old_value_json) != self.old_digest
                or integrity.digest(key, self.new_value_json) != self.new_digest)


class AuditBatch(models.Model):
    _name = 'audit.batch'
    _description = 'Audit Batch (import / bulk operation)'
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True)
    batch_type = fields.Selection([
        ('import', 'Import'), ('bulk_create', 'Bulk Create'), ('bulk_write', 'Bulk Update'),
        ('bulk_unlink', 'Bulk Delete'),
    ], required=True, readonly=True)
    model_name = fields.Char(readonly=True, index=True)
    user_id = fields.Many2one('res.users', ondelete='set null', readonly=True)
    correlation_id = fields.Char(readonly=True, index=True)
    log_ids = fields.One2many('audit.log', 'batch_id', readonly=True)
    total_count = fields.Integer(readonly=True)
    created_count = fields.Integer(readonly=True)
    updated_count = fields.Integer(readonly=True)
    deleted_count = fields.Integer(readonly=True)
    failed_count = fields.Integer(readonly=True)

    @api.model
    def _persist_batches(self, batches):
        result = {}
        for batch in batches:
            vals = {k: v for k, v in batch.items() if k in self._fields}
            result[batch['key']] = self.create(vals).id
        return result

    def _refresh_counts(self):
        for batch in self:
            counts = dict(self.env['audit.log']._read_group(
                [('batch_id', '=', batch.id)], ['operation'], ['__count']))
            batch.write({
                'created_count': counts.get('CREATE', 0),
                'updated_count': counts.get('UPDATE', 0),
                'deleted_count': counts.get('DELETE', 0),
                'total_count': sum(v for k, v in counts.items() if k in ('CREATE', 'UPDATE', 'DELETE')),
            })

    def action_open_logs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.name, 'res_model': 'audit.log',
                'view_mode': 'list,form', 'domain': [('batch_id', '=', self.id)]}

    def json_summary(self):
        return json.dumps({'created': self.created_count, 'updated': self.updated_count})
