# -*- coding: utf-8 -*-
import hashlib
import json
import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import context as audit_context
from ..services import integrity
from ..services.context import SOURCE_SELECTION

_logger = logging.getLogger(__name__)

OPERATION_SELECTION = [
    ('CREATE', 'Create'),
    ('UPDATE', 'Update'),
    ('DELETE', 'Delete'),
    ('ACTION', 'Business Action'),
    ('READ', 'Read'),
    ('EXPORT', 'Export'),
    ('IMPORT', 'Import'),
    ('REPORT', 'Print / Report'),
    ('LOGIN', 'Login'),
    ('LOGOUT', 'Logout'),
    ('FAILED_LOGIN', 'Failed Login'),
    ('MFA', 'Second Factor'),
    ('FAILED_ATTEMPT', 'Failed Operation'),
    ('CONFIG', 'Audit Configuration'),
    ('RETENTION', 'Retention Run'),
    ('REDACTION', 'Redaction'),
    ('ENGINE_ERROR', 'Audit Engine Error'),
]
# Fields a privileged internal operation may change on an existing row.
MUTABLE_BY_OPERATION = {
    'seal': {'chain_key', 'seal_seq', 'hash', 'previous_hash', 'seal_state', 'sealed_at',
             'hmac_key_id'},
    'bucket': {'attempt_count', 'event_datetime_last', 'seal_after'},
    'redact': {'delete_snapshot', 'before_snapshot', 'after_snapshot', 'redacted'},
    'alert': {'alert_ids'},
}
DELETABLE_BY_OPERATION = {'archive', 'purge', 'uninstall'}


class AuditLog(models.Model):
    _name = 'audit.log'
    _description = 'Audit Event'
    _order = 'event_datetime desc, id desc'
    _rec_name = 'reference'

    reference = fields.Char(readonly=True, index=True, copy=False)
    event_datetime = fields.Datetime(required=True, index=True, readonly=True,
                                     default=fields.Datetime.now)
    event_datetime_last = fields.Datetime('Last Occurrence', readonly=True)
    operation = fields.Selection(OPERATION_SELECTION, required=True, index=True, readonly=True)
    result = fields.Selection([('success', 'Success'), ('failure', 'Failure')],
                              default='success', required=True, index=True, readonly=True)
    failure_reason = fields.Text(readonly=True)

    model_name = fields.Char('Model', required=True, index=True, readonly=True)
    model_id = fields.Many2one('ir.model', 'Model Record', ondelete='set null', readonly=True)
    model_description = fields.Char(compute='_compute_model_description')
    res_id = fields.Many2oneReference('Record ID', model_field='model_name', index=True, readonly=True)
    record_display_name = fields.Char('Record', readonly=True)
    record_count = fields.Integer(readonly=True)
    res_ids_json = fields.Json('Record IDs', readonly=True)
    fields_json = fields.Json('Requested Fields', readonly=True)
    is_bulk = fields.Boolean(readonly=True)

    rule_id = fields.Many2one('audit.rule', ondelete='set null', index=True, readonly=True)
    user_id = fields.Many2one('res.users', 'User', ondelete='set null', index=True, readonly=True)
    user_login = fields.Char(readonly=True)
    initiating_user_id = fields.Many2one('res.users', ondelete='set null', readonly=True,
                                         help="Session user when the effective user differs "
                                              "(sudo / with_user).")
    is_sudo = fields.Boolean('Superuser Mode', readonly=True)
    company_id = fields.Many2one('res.company', ondelete='set null', index=True, readonly=True)
    visible_company_ids = fields.Many2many(
        'res.company', 'audit_log_visible_company_rel', 'log_id', 'company_id',
        string='Visible to Companies', readonly=True)
    is_shared = fields.Boolean('Shared / Global Record', index=True, readonly=True)

    source = fields.Selection(SOURCE_SELECTION, index=True, readonly=True)
    execution_path = fields.Char(readonly=True)
    claimed_client = fields.Char(readonly=True, help="Client type claimed by the User-Agent; "
                                                     "not verified.")
    ip_address = fields.Char('IP Address', index=True, readonly=True)
    user_agent = fields.Char(readonly=True)
    session_hash = fields.Char(readonly=True)
    request_path = fields.Char(readonly=True)
    http_method = fields.Char(readonly=True)
    correlation_id = fields.Char(index=True, readonly=True)

    action_method = fields.Char(readonly=True)
    action_label = fields.Char('Action', readonly=True)
    parent_action_id = fields.Many2one('audit.log', 'Semantic Action', ondelete='set null',
                                       index='btree_not_null', readonly=True)
    action_change_ids = fields.One2many('audit.log', 'parent_action_id', 'Resulting Changes')
    parent_log_id = fields.Many2one('audit.log', 'Parent Event', ondelete='set null',
                                    index='btree_not_null', readonly=True)
    child_log_ids = fields.One2many('audit.log', 'parent_log_id', 'Child Events')
    parent_model = fields.Char(readonly=True)
    parent_res_id = fields.Integer(readonly=True)
    batch_id = fields.Many2one('audit.batch', ondelete='set null', index='btree_not_null',
                               readonly=True)
    copy_of = fields.Char('Copied From', readonly=True)
    change_origin = fields.Selection(
        [('direct', 'Direct'), ('derived', 'Derived'), ('database_fk', 'Database cascade'),
         ('semantic', 'Semantic')], readonly=True)
    attempt_count = fields.Integer(readonly=True)
    bucket_key = fields.Char(index='btree_not_null', readonly=True)

    line_ids = fields.One2many('audit.log.line', 'audit_log_id', 'Changes', readonly=True)
    changed_fields_count = fields.Integer(readonly=True)
    before_snapshot = fields.Json(readonly=True, groups='nx_audit_log.group_audit_manager')
    after_snapshot = fields.Json(readonly=True, groups='nx_audit_log.group_audit_manager')
    delete_snapshot = fields.Json(readonly=True, groups='nx_audit_log.group_audit_manager')
    snapshot_text = fields.Text('Snapshot', compute='_compute_snapshot_text',
                                groups='nx_audit_log.group_audit_manager')
    snapshot_digest = fields.Char(readonly=True)
    redacted = fields.Boolean(readonly=True)

    # retention
    retention_policy_id = fields.Many2one('audit.retention.policy', ondelete='set null',
                                          readonly=True)
    archive_after = fields.Datetime(index='btree_not_null', readonly=True)
    purge_after = fields.Datetime(index='btree_not_null', readonly=True)
    prohibit_purge = fields.Boolean(readonly=True)

    # integrity
    chain_key = fields.Char(index=True, readonly=True)
    seal_state = fields.Selection([('unsealed', 'Unsealed'), ('sealed', 'Sealed')],
                                  default='unsealed', index=True, readonly=True)
    seal_after = fields.Datetime(index=True, readonly=True)
    seal_seq = fields.Integer(readonly=True)
    hash = fields.Char(readonly=True)
    previous_hash = fields.Char(readonly=True)
    hash_version = fields.Integer(default=integrity.HASH_VERSION, readonly=True)
    hmac_key_id = fields.Char(readonly=True)
    sealed_at = fields.Datetime(readonly=True)
    alert_ids = fields.Many2many('audit.alert', 'audit_alert_log_rel', 'log_id', 'alert_id',
                                 readonly=True)

    _sql_constraints = [
        ('chain_seq_uniq', 'unique(chain_key, seal_seq)', 'Seal sequence must be unique per chain.'),
    ]

    def init(self):
        from odoo.tools.sql import create_index
        create_index(self.env.cr, 'audit_log_model_res_idx', self._table,
                     ['model_name', 'res_id', 'event_datetime DESC'])
        create_index(self.env.cr, 'audit_log_unsealed_idx', self._table,
                     ['chain_key', 'seal_after', 'id'], where="seal_state = 'unsealed'")
        create_index(self.env.cr, 'audit_log_user_date_idx', self._table,
                     ['user_id', 'event_datetime DESC'])

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _compute_model_description(self):
        names = {m.model: m.name for m in self.env['ir.model'].sudo().search(
            [('model', 'in', list(set(self.mapped('model_name'))))])}
        for log in self:
            log.model_description = names.get(log.model_name, log.model_name)

    def _compute_snapshot_text(self):
        for log in self:
            data = {k: v for k, v in (('before', log.before_snapshot), ('after', log.after_snapshot),
                                      ('deleted', log.delete_snapshot)) if v}
            log.snapshot_text = json.dumps(data, indent=2, ensure_ascii=False, default=str) if data else False

    @api.depends('reference', 'operation', 'model_name', 'record_display_name')
    def _compute_display_name(self):
        for log in self:
            log.display_name = f"{log.reference or ''} {log.operation or ''} " \
                               f"{log.record_display_name or log.model_name or ''}".strip()

    # ------------------------------------------------------------------
    # Immutability
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if audit_context.privileged_operation() is None:
            raise AccessError(_("Audit events can only be created by the audit engine."))
        for vals in vals_list:
            self._prepare_integrity_and_retention(vals)
        logs = super().create(vals_list)
        for log in logs:
            log.reference = f"AUD/{log.event_datetime.year}/{log.id:010d}"
        return logs

    def write(self, vals):
        operation = audit_context.privileged_operation()
        allowed = MUTABLE_BY_OPERATION.get(operation, set())
        if operation != 'persist' and not set(vals) <= (allowed | {'reference'}):
            raise AccessError(_("Audit evidence is immutable."))
        return super().write(vals)

    def unlink(self):
        if audit_context.privileged_operation() not in DELETABLE_BY_OPERATION:
            raise AccessError(_("Audit evidence cannot be deleted. Use retention policies."))
        return super().unlink()

    def copy(self, default=None):
        raise UserError(_("Audit events cannot be duplicated."))

    def _prepare_integrity_and_retention(self, vals):
        now = fields.Datetime.now()
        vals.setdefault('event_datetime', now)
        event_at = fields.Datetime.to_datetime(vals['event_datetime'])
        settings = self.env['audit.rule']._get_engine_settings()
        company = vals.get('company_id')
        vals.setdefault('chain_key', f"{'c%s' % company if company else 'shared'}-{event_at.year}")
        delay = settings['seal_delay_seconds']
        if vals.get('bucket_key'):
            delay += settings['auth_bucket_minutes'] * 60
        vals.setdefault('seal_after', now + timedelta(seconds=delay))
        vals.setdefault('hash_version', integrity.HASH_VERSION)
        policy = self._retention_policy_for(vals)
        if policy:
            vals.update(policy._dates_for(event_at))
            vals['retention_policy_id'] = policy.id

    def _retention_policy_for(self, vals):
        Policy = self.env['audit.retention.policy'].sudo()
        if vals.get('retention_policy_id'):
            return Policy.browse(vals['retention_policy_id'])
        if vals.get('rule_id'):
            policy = self.env['audit.rule'].sudo().browse(vals['rule_id']).retention_policy_id
            if policy:
                return policy
        return Policy._default_for_operation(vals.get('operation'))

    # ------------------------------------------------------------------
    # Persistence service (called by the finalizer and side cursors)
    # ------------------------------------------------------------------
    @api.model
    def _audit_persist(self, events, batches):
        """Persist plain-dict events. Parents before children, actions first."""
        if not events:
            return self.browse()
        key = integrity.get_hmac_key(self.env)
        with audit_context.privileged('persist'), audit_context.guarded():
            batch_ids = self.env['audit.batch'].sudo()._persist_batches(batches)
            ids_by_key, created = {}, self.browse()
            ordered = sorted(events, key=lambda e: (e['operation'] != 'ACTION', e.get('depth', 0)))
            for depth_events in self._group_by_rank(ordered):
                vals_list = [self._event_vals(e, ids_by_key, batch_ids, key) for e in depth_events]
                logs = self.sudo().create(vals_list)
                for event, log in zip(depth_events, logs):
                    ids_by_key[event['key']] = log.id
                created |= logs
            created._update_batch_counts()
            created._post_persist()
        return created

    @staticmethod
    def _group_by_rank(events):
        groups, current, rank = [], [], None
        for event in events:
            event_rank = (event['operation'] != 'ACTION', event.get('depth', 0))
            if rank is not None and event_rank != rank:
                groups.append(current)
                current = []
            current.append(event)
            rank = event_rank
        if current:
            groups.append(current)
        return groups

    def _event_vals(self, event, ids_by_key, batch_ids, key):
        vals = {k: v for k, v in event.items() if k in self._fields and k not in (
            'line_ids', 'visible_company_ids')}
        lines = event.get('lines') or []
        vals['line_ids'] = [(0, 0, self.env['audit.log.line']._line_vals(line, key)) for line in lines]
        vals['changed_fields_count'] = len({line['field_name'] for line in lines})
        vals['visible_company_ids'] = [(6, 0, event.get('visible_company_ids') or [])]
        vals['parent_log_id'] = ids_by_key.get(event.get('parent_key')) or False
        vals['parent_action_id'] = ids_by_key.get(event.get('parent_action_key')) or False
        vals['batch_id'] = batch_ids.get(event.get('batch_key')) or False
        vals['model_id'] = self.env['ir.model']._get_id(event['model_name']) \
            if event.get('model_name') in self.env else False
        if event.get('operation') == 'ACTION':
            vals['change_origin'] = 'semantic'
        if vals.get('user_id'):
            vals['user_login'] = self.env['res.users'].sudo().browse(vals['user_id']).login
        snapshots = {k: event.get(k) for k in ('before_snapshot', 'after_snapshot', 'delete_snapshot')
                     if event.get(k)}
        vals['snapshot_digest'] = integrity.digest(key, snapshots) if snapshots else False
        vals['hmac_key_id'] = integrity.key_id(key)
        return vals

    def _update_batch_counts(self):
        for batch in self.mapped('batch_id'):
            batch._refresh_counts()

    def _post_persist(self):
        self.env['audit.alert.rule'].sudo()._evaluate_logs(self)
        self._mirror_to_chatter()

    def _mirror_to_chatter(self):
        for log in self.filtered(lambda l: l.rule_id.chatter_mirror and l.res_id
                                 and l.operation in ('CREATE', 'UPDATE', 'ACTION')):
            Model = self.env.get(log.model_name)
            if Model is None or not hasattr(Model, 'message_post'):
                continue
            record = Model.sudo().browse(log.res_id).exists()
            if not record:
                continue
            summary = ', '.join(
                f"{line.field_label}: {line.old_value_text or ''} \u2192 {line.new_value_text or ''}"
                for line in log.line_ids if not line.restricted)[:1000]
            record.with_context(mail_notrack=True).message_post(
                body=_("Audit %(ref)s: %(summary)s", ref=log.reference,
                       summary=summary or log.action_label or log.operation),
                message_type='notification', subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # Side-cursor recorders (auth, failures, config)
    # ------------------------------------------------------------------
    @api.model
    def _record_config_events(self, model_name, operation, lines_by_record):
        uid = self.env.uid
        meta = audit_context.request_meta()
        events = []
        for record_id, lines in lines_by_record.items():
            events.append({
                'key': f'config:{model_name}:{record_id}:{len(events)}',
                'operation': operation,
                'model_name': model_name,
                'res_id': record_id,
                'user_id': uid,
                'source': audit_context.resolve_source(meta),
                'correlation_id': meta.get('correlation_id') or False,
                'ip_address': meta.get('ip_address') or False,
                'user_agent': meta.get('user_agent') or False,
                'is_shared': True,
                'change_origin': 'direct',
                'lines': lines,
            })
        return self._audit_persist(events, [])

    @api.model
    def _record_auth_event(self, operation, uid=False, login=None, meta=None, extra=None):
        meta = meta or audit_context.request_meta()
        company = self.env['res.users'].sudo().browse(uid).company_id.id if uid else False
        event = {
            'key': f'auth:{operation}:{uid}',
            'operation': operation,
            'model_name': 'res.users',
            'res_id': uid or False,
            'record_display_name': login or False,
            'user_id': uid or False,
            'source': meta.get('transport') or 'system',
            'company_id': company,
            'visible_company_ids': [company] if company else [],
            'is_shared': not company,
            'ip_address': meta.get('ip_address') or False,
            'user_agent': meta.get('user_agent') or False,
            'claimed_client': meta.get('claimed_client') or False,
            'session_hash': meta.get('session_hash') or False,
            'request_path': meta.get('path') or False,
            'correlation_id': meta.get('correlation_id') or False,
            'lines': [],
        }
        event.update(extra or {})
        return self._audit_persist([event], [])

    @api.model
    def _record_failed_login(self, login, meta=None, credential_type='password'):
        """Aggregated per (login hash, IP, time bucket) to resist brute force floods."""
        meta = meta or audit_context.request_meta()
        settings = self.env['audit.rule']._get_engine_settings()
        window = settings['auth_bucket_minutes']
        now = fields.Datetime.now()
        bucket_start = now - timedelta(minutes=now.minute % window, seconds=now.second,
                                       microseconds=now.microsecond)
        ip = meta.get('ip_address') or 'n/a'
        login_hash = hashlib.sha256((login or '').strip().lower().encode()).hexdigest()[:24]
        bucket = self._failed_login_bucket_key(ip, login_hash, bucket_start)
        existing = self.sudo().search([('bucket_key', '=', bucket), ('seal_state', '=', 'unsealed')],
                                      limit=1)
        if existing:
            with audit_context.privileged('bucket'):
                existing.write({'attempt_count': existing.attempt_count + 1,
                                'event_datetime_last': now})
            self.env['audit.alert.rule'].sudo()._evaluate_logs(existing)
            return existing
        user = self.env['res.users'].sudo().with_context(active_test=False).search(
            [('login', '=', login)], limit=1) if login else self.env['res.users']
        shown = login if (user or settings['store_unknown_logins']) else f'sha256:{login_hash}'
        return self._record_auth_event('FAILED_LOGIN', uid=user.id, login=shown, meta=meta, extra={
            'result': 'failure', 'attempt_count': 1, 'bucket_key': bucket,
            'event_datetime': now, 'event_datetime_last': now,
            'failure_reason': f'credential type: {credential_type}',
        })

    def _failed_login_bucket_key(self, ip, login_hash, bucket_start):
        """Per IP: after 20 distinct logins in a window, collapse into one IP bucket."""
        window_key = bucket_start.strftime('%Y%m%d%H%M')
        distinct = self.sudo().search_count([
            ('operation', '=', 'FAILED_LOGIN'), ('ip_address', '=', ip),
            ('bucket_key', 'like', f'%:{window_key}'), ('seal_state', '=', 'unsealed'),
        ])
        if distinct >= 20:
            return f'ip:{ip}:*:{window_key}'
        return f'ip:{ip}:{login_hash}:{window_key}'

    @api.model
    def _record_failure(self, model_name, method, ids, uid, reason, meta=None):
        meta = meta or audit_context.request_meta()
        plan = self.env['audit.rule']._get_plan(model_name)
        flag = {'create': 'create', 'write': 'update', 'unlink': 'delete'}.get(method, 'action')
        if not plan or flag not in plan['ops']:
            return self.browse()
        ids = [i for i in (ids or []) if isinstance(i, int)]
        company = self.env['res.users'].sudo().browse(uid).company_id.id if uid else False
        names = {}
        Model = self.env[model_name].sudo().with_context(active_test=False)
        for record in Model.browse(ids[:20]).exists():
            names[record.id] = record.display_name
        event = {
            'key': f'failure:{model_name}:{method}',
            'operation': 'FAILED_ATTEMPT',
            'result': 'failure',
            'failure_reason': (reason or '')[:2000],
            'model_name': model_name,
            'res_id': ids[0] if len(ids) == 1 else False,
            'record_display_name': names.get(ids[0]) if len(ids) == 1 else False,
            'record_count': len(ids),
            'res_ids_json': ids[:1000],
            'action_method': method,
            'user_id': uid or False,
            'source': meta.get('transport') or 'system',
            'company_id': company,
            'visible_company_ids': [company] if company else [],
            'is_shared': not company,
            'ip_address': meta.get('ip_address') or False,
            'user_agent': meta.get('user_agent') or False,
            'claimed_client': meta.get('claimed_client') or False,
            'session_hash': meta.get('session_hash') or False,
            'request_path': meta.get('path') or False,
            'correlation_id': meta.get('correlation_id') or False,
            'lines': [],
        }
        return self._audit_persist([event], [])

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    @api.model
    def action_open_trail(self, model_name, res_ids):
        if len(res_ids) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'nx_audit_log.timeline',
                'name': _('Audit Trail'),
                'params': {'model': model_name, 'res_id': res_ids[0]},
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Audit Trail'),
            'res_model': 'audit.log',
            'view_mode': 'list,form',
            'domain': ['|', '&', ('model_name', '=', model_name), ('res_id', 'in', res_ids),
                       '&', ('parent_model', '=', model_name), ('parent_res_id', 'in', res_ids)],
        }

    def action_open_record_trail(self):
        self.ensure_one()
        return self.action_open_trail(self.model_name, [self.res_id])

    def action_open_record(self):
        self.ensure_one()
        record = self.env[self.model_name].browse(self.res_id).exists() \
            if self.model_name in self.env and self.res_id else None
        if not record:
            raise UserError(_("The record no longer exists. Its evidence is kept in this event."))
        return {'type': 'ir.actions.act_window', 'res_model': self.model_name,
                'res_id': self.res_id, 'view_mode': 'form'}

    @api.model
    def get_timeline(self, model_name, res_id, limit=200):
        """Events of a record and of its child lines, for the timeline view."""
        logs = self.search(['|', '&', ('model_name', '=', model_name), ('res_id', '=', res_id),
                            '&', ('parent_model', '=', model_name), ('parent_res_id', '=', res_id)],
                           limit=limit)
        result = []
        for log in logs:
            result.append({
                'id': log.id,
                'reference': log.reference,
                'operation': log.operation,
                'operation_label': dict(OPERATION_SELECTION).get(log.operation),
                'datetime': fields.Datetime.to_string(log.event_datetime),
                'user': log.user_id.display_name or log.user_login or '',
                'source': dict(SOURCE_SELECTION).get(log.source, log.source or ''),
                'model_name': log.model_name,
                'record': log.record_display_name or '',
                'is_child': log.model_name != model_name,
                'action_label': log.action_label or '',
                'parent_action': log.parent_action_id.action_label or '',
                'result': log.result,
                'sealed': log.seal_state == 'sealed',
                'lines': [{
                    'field': line.field_label,
                    'change_type': line.change_type,
                    'origin': line.change_origin,
                    'old': line.old_value_text or '',
                    'new': line.new_value_text or '',
                    'lang': line.lang or '',
                    'masked': line.masked,
                } for line in log.line_ids],
            })
        title = model_name
        if model_name in self.env:
            record = self.env[model_name].browse(res_id).exists()
            title = record.display_name if record else (logs[:1].record_display_name or title)
        return {'title': title, 'events': result}

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, days=1):
        days = max(1, min(int(days or 1), 365))
        since = fields.Datetime.now() - timedelta(days=days)
        domain = [('event_datetime', '>=', since)]
        by_operation = dict(self._read_group(domain, ['operation'], ['__count']))
        by_source = self._read_group(domain, ['source'], ['__count'])
        top_models = self._read_group(domain + [('operation', 'in', ['CREATE', 'UPDATE', 'DELETE'])],
                                      ['model_name'], ['__count'], order='__count desc', limit=8)
        top_users = self._read_group(domain, ['user_id'], ['__count'], order='__count desc', limit=8)
        failures = self.search_count(domain + [('result', '=', 'failure')])
        unsealed = self.search_count([('seal_state', '=', 'unsealed'),
                                      ('seal_after', '<', fields.Datetime.now() - timedelta(hours=1))])
        last_check = self.env['audit.integrity.check'].search([], limit=1)
        open_alerts = self.env['audit.alert'].search_count([('state', 'in', ('pending', 'sent'))])
        labels = dict(OPERATION_SELECTION)
        source_labels = dict(SOURCE_SELECTION)
        return {
            'days': days,
            'since': fields.Datetime.to_string(since),
            'operations': [{'code': op, 'label': labels[op], 'count': by_operation.get(op, 0)}
                           for op in ('CREATE', 'UPDATE', 'DELETE', 'ACTION', 'EXPORT', 'REPORT',
                                      'READ', 'LOGIN', 'FAILED_LOGIN', 'FAILED_ATTEMPT')],
            'total': sum(by_operation.values()),
            'failures': failures,
            'sources': [{'code': s or 'system', 'label': source_labels.get(s, s or 'System'),
                         'count': c} for s, c in by_source],
            'top_models': [{'model': m, 'count': c} for m, c in top_models],
            'top_users': [{'id': u.id, 'name': u.display_name or _('Unknown'), 'count': c}
                          for u, c in top_users],
            'unsealed_backlog': unsealed,
            'open_alerts': open_alerts,
            'integrity': {
                'state': last_check.state or 'never',
                'date': fields.Datetime.to_string(last_check.create_date) if last_check else False,
                'violations': last_check.violation_count if last_check else 0,
            },
            'storage': self.sudo()._storage_stats() if self.env.user.has_group(
                'nx_audit_log.group_audit_manager') else [],
        }

    def _storage_stats(self):
        self.env.cr.execute("""
            SELECT c.relname, pg_total_relation_size(c.oid), COALESCE(s.n_live_tup, 0)
              FROM pg_class c LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
             WHERE c.relname IN ('audit_log', 'audit_log_line', 'audit_log_archive',
                               'audit_log_tombstone')
        """)
        return [{'table': t, 'bytes': b, 'rows': r} for t, b, r in self.env.cr.fetchall()]
