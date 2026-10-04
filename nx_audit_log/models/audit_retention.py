# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..services import context as audit_context
from ..services import integrity

_logger = logging.getLogger(__name__)

AUTH_OPERATIONS = ('LOGIN', 'LOGOUT', 'FAILED_LOGIN', 'MFA', 'CONFIG', 'REDACTION', 'RETENTION')
BATCH_SIZE = 2000


class AuditRetentionPolicy(models.Model):
    _name = 'audit.retention.policy'
    _description = 'Audit Retention Policy'
    _inherit = ['audit.config.mixin']

    name = fields.Char(required=True)
    code = fields.Char(index=True)
    hot_days = fields.Integer('Online (days)', default=365,
                              help="Days kept in the main audit tables. 0 = never archive.")
    retention_days = fields.Integer('Total retention (days)', default=0,
                                    help="0 = keep forever.")
    prohibit_purge = fields.Boolean(help="Evidence under this policy can never be purged.")
    note = fields.Text()

    @api.constrains('hot_days', 'retention_days')
    def _check_days(self):
        for policy in self:
            if policy.hot_days < 0 or policy.retention_days < 0:
                raise ValidationError(_("Retention periods cannot be negative."))
            if policy.retention_days and policy.hot_days and policy.retention_days < policy.hot_days:
                raise ValidationError(_("Total retention must cover the online period."))

    def _dates_for(self, event_at):
        self.ensure_one()
        return {
            'archive_after': event_at + timedelta(days=self.hot_days) if self.hot_days else False,
            'purge_after': (event_at + timedelta(days=self.retention_days)
                            if self.retention_days and not self.prohibit_purge else False),
            'prohibit_purge': self.prohibit_purge,
        }

    @api.model
    def _ensure_default_policies(self):
        defaults = {
            'finance': {'name': 'Finance (10 years, no purge)', 'hot_days': 730,
                        'retention_days': 0, 'prohibit_purge': True},
            'security': {'name': 'Security (5 years)', 'hot_days': 365, 'retention_days': 1825},
            'standard': {'name': 'Standard (3 years)', 'hot_days': 365, 'retention_days': 1095},
        }
        result = {}
        for code, values in defaults.items():
            policy = self.search([('code', '=', code)], limit=1)
            result[code] = policy or self.create(dict(values, code=code))
        return result

    @api.model
    def _default_for_operation(self, operation):
        code = 'security' if operation in AUTH_OPERATIONS else 'standard'
        return self.search([('code', '=', code)], limit=1)

    # ------------------------------------------------------------------
    # Retention job
    # ------------------------------------------------------------------
    @api.model
    def _cron_retention(self):
        stats = {
            'archived': self._archive_due(),
            'purged_hot': self._purge_hot_due(),
            'purged_archive': self._purge_archive_due(),
            'compacted': self.env['audit.log.tombstone']._compact(),
        }
        if any(stats.values()):
            self.env['audit.log'].sudo()._audit_persist([{
                'key': 'retention', 'operation': 'RETENTION', 'model_name': 'audit.log',
                'res_id': False, 'user_id': self.env.uid, 'source': 'cron',
                'record_count': sum(stats.values()), 'fields_json': stats, 'is_shared': True,
                'lines': [],
            }], [])
        _logger.info("nx_audit_log retention: %s", stats)
        return stats

    def _archive_due(self):
        Log = self.env['audit.log'].sudo()
        logs = Log.search([('archive_after', '<=', fields.Datetime.now()),
                           ('seal_state', '=', 'sealed')], limit=BATCH_SIZE, order='id')
        if not logs:
            return 0
        self.env['audit.log.archive'].sudo()._archive_logs(logs)
        return len(logs)

    def _purge_hot_due(self):
        Log = self.env['audit.log'].sudo()
        logs = Log.search([('purge_after', '<=', fields.Datetime.now()), ('prohibit_purge', '=', False),
                           ('seal_state', '=', 'sealed')], limit=BATCH_SIZE, order='id')
        if not logs:
            return 0
        self.env['audit.log.tombstone']._bury([log._tombstone_vals() for log in logs])
        with audit_context.privileged('purge'):
            logs.unlink()
        return len(logs)

    def _purge_archive_due(self):
        Archive = self.env['audit.log.archive'].sudo()
        rows = Archive.search([('purge_after', '<=', fields.Datetime.now()),
                               ('prohibit_purge', '=', False)], limit=BATCH_SIZE, order='id')
        if not rows:
            return 0
        self.env['audit.log.tombstone']._bury([row._tombstone_vals() for row in rows])
        with audit_context.privileged('purge'):
            rows.unlink()
        return len(rows)


class AuditLogRetentionMixin(models.Model):
    _inherit = 'audit.log'

    def _tombstone_vals(self):
        self.ensure_one()
        return {'original_id': self.id, 'reference': self.reference, 'chain_key': self.chain_key,
                'seal_seq': self.seal_seq, 'hash': self.hash, 'previous_hash': self.previous_hash}

    def _plain(self):
        """Plain dict used for canonical hashing and archiving."""
        self.ensure_one()
        return {
            'id': self.id, 'reference': self.reference,
            'hash_version': self.hash_version, 'chain_key': self.chain_key,
            'seal_seq': self.seal_seq, 'event_datetime': fields.Datetime.to_string(self.event_datetime),
            'operation': self.operation, 'model_name': self.model_name, 'res_id': self.res_id,
            'user_id': self.user_id.id, 'user_login': self.user_login,
            'company_id': self.company_id.id, 'source': self.source,
            'action_method': self.action_method, 'action_label': self.action_label,
            'result': self.result, 'record_count': self.record_count,
            'attempt_count': self.attempt_count, 'snapshot_digest': self.snapshot_digest,
            'correlation_id': self.correlation_id, 'record_display_name': self.record_display_name,
            'ip_address': self.ip_address, 'failure_reason': self.failure_reason,
            'before_snapshot': self.sudo().before_snapshot, 'after_snapshot': self.sudo().after_snapshot,
            'delete_snapshot': self.sudo().delete_snapshot, 'hash': self.hash,
            'previous_hash': self.previous_hash, 'redacted': self.redacted,
        }


class AuditLogArchive(models.Model):
    _name = 'audit.log.archive'
    _description = 'Archived Audit Event'
    _order = 'event_datetime desc, id desc'
    _rec_name = 'reference'

    original_id = fields.Integer(index=True, readonly=True)
    reference = fields.Char(readonly=True, index=True)
    event_datetime = fields.Datetime(readonly=True, index=True)
    operation = fields.Char(readonly=True)
    model_name = fields.Char(readonly=True, index=True)
    res_id = fields.Integer(readonly=True, index=True)
    record_display_name = fields.Char(readonly=True)
    user_id = fields.Many2one('res.users', ondelete='set null', readonly=True)
    company_id = fields.Many2one('res.company', ondelete='set null', readonly=True)
    visible_company_ids = fields.Many2many('res.company', 'audit_log_archive_company_rel',
                                           'archive_id', 'company_id', readonly=True)
    is_shared = fields.Boolean(readonly=True)
    chain_key = fields.Char(readonly=True, index=True)
    seal_seq = fields.Integer(readonly=True)
    hash = fields.Char(readonly=True)
    previous_hash = fields.Char(readonly=True)
    purge_after = fields.Datetime(readonly=True, index='btree_not_null')
    prohibit_purge = fields.Boolean(readonly=True)
    payload = fields.Json(readonly=True, groups='nx_audit_log.group_audit_manager')

    @api.model_create_multi
    def create(self, vals_list):
        if audit_context.privileged_operation() != 'archive':
            raise AccessError(_("Archive rows are written by the retention job only."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Archived evidence is immutable."))

    def unlink(self):
        if audit_context.privileged_operation() not in ('purge', 'uninstall'):
            raise AccessError(_("Archived evidence is removed by the retention job only."))
        return super().unlink()

    @api.model
    def _archive_logs(self, logs):
        vals_list = []
        for log in logs:
            plain = log._plain()
            vals_list.append({
                'original_id': log.id, 'reference': log.reference,
                'event_datetime': log.event_datetime, 'operation': log.operation,
                'model_name': log.model_name, 'res_id': log.res_id,
                'record_display_name': log.record_display_name, 'user_id': log.user_id.id,
                'company_id': log.company_id.id,
                'visible_company_ids': [(6, 0, log.visible_company_ids.ids)],
                'is_shared': log.is_shared, 'chain_key': log.chain_key, 'seal_seq': log.seal_seq,
                'hash': log.hash, 'previous_hash': log.previous_hash,
                'purge_after': log.purge_after, 'prohibit_purge': log.prohibit_purge,
                'payload': {'log': plain, 'lines': [line._plain() for line in log.line_ids]},
            })
        with audit_context.privileged('archive'):
            self.create(vals_list)
            logs.unlink()

    def _tombstone_vals(self):
        self.ensure_one()
        return {'original_id': self.original_id, 'reference': self.reference,
                'chain_key': self.chain_key, 'seal_seq': self.seal_seq, 'hash': self.hash,
                'previous_hash': self.previous_hash}


class AuditLogTombstone(models.Model):
    _name = 'audit.log.tombstone'
    _description = 'Purged Audit Event Stub'
    _order = 'chain_key, seal_seq'

    original_id = fields.Integer(readonly=True)
    reference = fields.Char(readonly=True)
    chain_key = fields.Char(readonly=True, index=True)
    seal_seq = fields.Integer(readonly=True, index=True)
    hash = fields.Char(readonly=True)
    previous_hash = fields.Char(readonly=True)
    purged_at = fields.Datetime(readonly=True, default=fields.Datetime.now)

    @api.model
    def _bury(self, vals_list):
        with audit_context.privileged('purge'):
            return self.sudo().create(vals_list)

    @api.model_create_multi
    def create(self, vals_list):
        if audit_context.privileged_operation() != 'purge':
            raise AccessError(_("Tombstones are written by the retention job only."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Tombstones are immutable."))

    def unlink(self):
        if audit_context.privileged_operation() not in ('compact', 'uninstall'):
            raise AccessError(_("Tombstones are removed by checkpoint compaction only."))
        return super().unlink()

    @api.model
    def _compact(self):
        """Replace the contiguous oldest tombstones of each chain by a signed checkpoint."""
        compacted = 0
        Checkpoint = self.env['audit.checkpoint'].sudo()
        for chain_key in set(self.sudo().search([]).mapped('chain_key')):
            start = Checkpoint._next_seq(chain_key)
            stones = self.sudo().search([('chain_key', '=', chain_key), ('seal_seq', '>=', start)],
                                        order='seal_seq', limit=50000)
            run = []
            for stone in stones:
                if stone.seal_seq != start + len(run):
                    break
                run.append(stone)
            if not run:
                continue
            Checkpoint._create_checkpoint(chain_key, run[0].seal_seq, run[-1].seal_seq,
                                          run[-1].hash, len(run))
            with audit_context.privileged('compact'):
                self.browse([s.id for s in run]).unlink()
            compacted += len(run)
        return compacted


class AuditCheckpoint(models.Model):
    _name = 'audit.checkpoint'
    _description = 'Audit Chain Checkpoint'
    _order = 'chain_key, seq_to desc'

    chain_key = fields.Char(required=True, readonly=True, index=True)
    seq_from = fields.Integer(readonly=True)
    seq_to = fields.Integer(readonly=True)
    event_count = fields.Integer(readonly=True)
    last_hash = fields.Char(readonly=True)
    signature = fields.Char(readonly=True, help="HMAC of the checkpoint content.")
    hmac_key_id = fields.Char(readonly=True)

    def write(self, vals):
        raise AccessError(_("Checkpoints are immutable."))

    def unlink(self):
        if audit_context.privileged_operation() != 'uninstall':
            raise AccessError(_("Checkpoints cannot be deleted."))
        return super().unlink()

    def _signed_payload(self, chain_key, seq_from, seq_to, last_hash, count):
        return {'chain': chain_key, 'from': seq_from, 'to': seq_to, 'last': last_hash, 'count': count}

    @api.model
    def _create_checkpoint(self, chain_key, seq_from, seq_to, last_hash, count):
        key = integrity.get_hmac_key(self.env)
        payload = self._signed_payload(chain_key, seq_from, seq_to, last_hash, count)
        return self.create({
            'chain_key': chain_key, 'seq_from': seq_from, 'seq_to': seq_to,
            'event_count': count, 'last_hash': last_hash,
            'signature': integrity.digest(key, payload), 'hmac_key_id': integrity.key_id(key),
        })

    def _signature_valid(self):
        self.ensure_one()
        key = integrity.get_hmac_key(self.env)
        payload = self._signed_payload(self.chain_key, self.seq_from, self.seq_to,
                                       self.last_hash, self.event_count)
        return integrity.digest(key, payload) == self.signature

    @api.model
    def _latest(self, chain_key):
        return self.sudo().search([('chain_key', '=', chain_key)], order='seq_to desc', limit=1)

    @api.model
    def _next_seq(self, chain_key):
        latest = self._latest(chain_key)
        return latest.seq_to + 1 if latest else 1
