# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services import context as audit_context
from ..services.serializer import REDACTED


class AuditSensitivePattern(models.Model):
    _name = 'audit.sensitive.pattern'
    _description = 'Sensitive Field Pattern'
    _inherit = ['audit.config.mixin']
    _order = 'sequence, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        [('secret', 'Secret (never stored)'), ('personal', 'Personal data')],
        required=True, default='secret')
    personal_mode = fields.Selection(
        [('store', 'Store value (redactable)'), ('digest', 'Store keyed digest only')],
        default='store')
    model_pattern = fields.Char(help="Regular expression on the technical model name. Empty = all.")
    field_pattern = fields.Char(required=True, help="Regular expression on the technical field name.")

    @api.constrains('model_pattern', 'field_pattern')
    def _check_patterns(self):
        for pattern in self:
            for value in (pattern.model_pattern, pattern.field_pattern):
                if value:
                    try:
                        re.compile(value)
                    except re.error as exc:
                        raise ValidationError(_("Invalid regular expression %s: %s", value, exc)) from exc

    @api.model
    def _compiled_patterns(self):
        return [
            (p.category, re.compile(p.model_pattern) if p.model_pattern else None,
             re.compile(p.field_pattern), p.personal_mode or 'store')
            for p in self.search([])
        ]

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records


class AuditRedactionRequest(models.Model):
    _name = 'audit.redaction.request'
    _description = 'Audit Redaction Request'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Waiting Approval'), ('approved', 'Approved'),
        ('done', 'Executed'), ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True)
    reason = fields.Text(required=True)
    legal_reference = fields.Char(help="Ticket, request number or legal basis.")
    model_name = fields.Char(required=True, help="Technical model of the data subject records.")
    res_ids = fields.Char('Record IDs', help="Comma separated ids. Empty = every record of the model.")
    field_names = fields.Char(required=True, help="Comma separated technical field names to redact.")
    date_to = fields.Datetime(help="Only evidence recorded before this date.")
    requested_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    approved_by_id = fields.Many2one('res.users', readonly=True, tracking=True)
    executed_at = fields.Datetime(readonly=True)
    matched_line_count = fields.Integer(compute='_compute_matched_line_count')
    redacted_line_count = fields.Integer(readonly=True)

    def _line_domain(self):
        self.ensure_one()
        fnames = [f.strip() for f in (self.field_names or '').split(',') if f.strip()]
        domain = [('audit_log_id.model_name', '=', self.model_name), ('field_name', 'in', fnames),
                  ('redacted', '=', False)]
        ids = [int(i) for i in (self.res_ids or '').split(',') if i.strip().isdigit()]
        if ids:
            domain.append(('audit_log_id.res_id', 'in', ids))
        if self.date_to:
            domain.append(('audit_log_id.event_datetime', '<=', self.date_to))
        return domain

    def _compute_matched_line_count(self):
        Line = self.env['audit.log.line'].sudo()
        for request in self:
            request.matched_line_count = Line.search_count(request._line_domain()) \
                if request.model_name and request.field_names else 0

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_approve(self):
        for request in self:
            if request.requested_by_id == self.env.user:
                raise UserError(_("Four-eyes principle: the requester cannot approve the redaction."))
            request.write({'state': 'approved', 'approved_by_id': self.env.user.id})

    def action_execute(self):
        for request in self:
            if request.state != 'approved':
                raise UserError(_("Only approved requests can be executed."))
            request._execute()

    def _execute(self):
        lines = self.env['audit.log.line'].sudo().search(self._line_domain())
        fnames = set(lines.mapped('field_name'))
        with audit_context.privileged('redact'):
            lines.write({
                'old_value_json': {'redacted': True}, 'new_value_json': {'redacted': True},
                'old_value_text': REDACTED, 'new_value_text': REDACTED,
                'redacted': True, 'redaction_id': self.id,
            })
            for log in lines.mapped('audit_log_id'):
                log._redact_snapshots(fnames)
        self.write({'state': 'done', 'executed_at': fields.Datetime.now(),
                    'redacted_line_count': len(lines)})
        self.env['audit.log'].sudo()._audit_persist([{
            'key': f'redaction:{self.id}', 'operation': 'REDACTION',
            'model_name': self.model_name, 'res_id': False, 'user_id': self.env.uid,
            'source': 'web_ui', 'record_count': len(lines), 'is_shared': True,
            'action_label': self.name,
            'fields_json': {'request': self.id, 'fields': sorted(fnames), 'reason': self.reason,
                            'approved_by': self.approved_by_id.login,
                            'requested_by': self.requested_by_id.login,
                            'log_ids': lines.mapped('audit_log_id').ids[:5000]},
            'lines': [],
        }], [])


class AuditLogRedaction(models.Model):
    _inherit = 'audit.log'

    def _redact_snapshots(self, fnames):
        """Snapshot digests were computed at write time and stay valid evidence."""
        vals = {'redacted': True}
        for name in ('before_snapshot', 'after_snapshot', 'delete_snapshot'):
            snapshot = self.sudo()[name]
            if snapshot and fnames & set(snapshot):
                vals[name] = {k: ({'redacted': True} if k in fnames else v) for k, v in snapshot.items()}
        self.sudo().write(vals)
