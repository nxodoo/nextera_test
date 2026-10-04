# -*- coding: utf-8 -*-
"""Integrity sealing and verification.

Rows are committed unsealed. A single sealing job later assigns, per chain,
a sealing sequence in the order it *sees* committed rows. Ids are never used
as chain order, so a transaction committing late (with a lower id) is simply
sealed in a later run; nothing is skipped or broken.
"""
import logging
from datetime import timedelta

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from ..services import context as audit_context
from ..services import integrity

_logger = logging.getLogger(__name__)

SEAL_BATCH = 5000
VERIFY_WINDOW = 5000
UNSEALED_WARNING_HOURS = 1


class AuditChain(models.Model):
    _name = 'audit.chain'
    _description = 'Audit Hash Chain'
    _order = 'chain_key'

    chain_key = fields.Char(required=True, readonly=True, index=True)
    last_seq = fields.Integer(readonly=True)
    last_hash = fields.Char(readonly=True)
    last_sealed_at = fields.Datetime(readonly=True)

    _sql_constraints = [('chain_key_uniq', 'unique(chain_key)', 'Chain keys are unique.')]

    def write(self, vals):
        if audit_context.privileged_operation() != 'seal':
            raise AccessError(_("Chains are maintained by the sealing job only."))
        return super().write(vals)

    def unlink(self):
        if audit_context.privileged_operation() != 'uninstall':
            raise AccessError(_("Chains cannot be deleted."))
        return super().unlink()

    @api.model
    def _get_or_create(self, chain_key):
        chain = self.sudo().search([('chain_key', '=', chain_key)], limit=1)
        return chain or self.sudo().create({'chain_key': chain_key})

    def _lock(self):
        """Row lock so a manual seal and the cron never seal the same chain twice."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute("SELECT id FROM audit_chain WHERE id = %s FOR UPDATE NOWAIT",
                                    [self.id])
            return True
        except psycopg2.errors.LockNotAvailable:
            return False

    # ------------------------------------------------------------------
    # Sealing
    # ------------------------------------------------------------------
    @api.model
    def _cron_seal(self):
        now = fields.Datetime.now()
        self.env.cr.execute("""
            SELECT DISTINCT chain_key FROM audit_log
             WHERE seal_state = 'unsealed' AND seal_after <= %s
        """, [now])
        keys = [r[0] for r in self.env.cr.fetchall()]
        sealed = 0
        for chain_key in keys:
            sealed += self._get_or_create(chain_key)._seal_pending(now)
        remaining = self.env['audit.log'].sudo().search_count(
            [('seal_state', '=', 'unsealed'), ('seal_after', '<=', now)])
        if remaining:
            self.env.ref('nx_audit_log.cron_seal_events')._trigger()
        return sealed

    def _seal_pending(self, now):
        self.ensure_one()
        if not self._lock():
            return 0
        logs = self.env['audit.log'].sudo().search(
            [('chain_key', '=', self.chain_key), ('seal_state', '=', 'unsealed'),
             ('seal_after', '<=', now)], order='id', limit=SEAL_BATCH)
        if not logs:
            return 0
        key = integrity.get_hmac_key(self.env)
        previous = self.last_hash or integrity.genesis_hash(self.chain_key)
        seq = self.last_seq
        with audit_context.privileged('seal'):
            for log in logs:
                seq += 1
                plain = dict(log._plain(), seal_seq=seq)
                digest = integrity.chain_hash(
                    previous, integrity.canonical_event(plain, [line._plain() for line in log.line_ids]))
                log.write({'seal_seq': seq, 'previous_hash': previous, 'hash': digest,
                           'seal_state': 'sealed', 'sealed_at': now,
                           'hmac_key_id': integrity.key_id(key)})
                previous = digest
            self.write({'last_seq': seq, 'last_hash': previous, 'last_sealed_at': now})
        return len(logs)


class AuditIntegrityCheck(models.Model):
    _name = 'audit.integrity.check'
    _description = 'Audit Integrity Verification'
    _order = 'id desc'

    name = fields.Char(default=lambda self: _('Verification %s', fields.Datetime.now()), readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('passed', 'Passed'), ('failed', 'Violations found')],
                             default='draft', readonly=True)
    chain_count = fields.Integer(readonly=True)
    checked_count = fields.Integer(readonly=True)
    violation_count = fields.Integer(readonly=True)
    unsealed_backlog = fields.Integer(readonly=True)
    duration = fields.Float(readonly=True)
    violation_ids = fields.One2many('audit.integrity.violation', 'check_id', readonly=True)

    @api.model
    def _cron_verify(self):
        return self.create({})._run()

    def action_run(self):
        for check in self:
            check._run()
        return True

    def _run(self):
        self.ensure_one()
        started = fields.Datetime.now()
        self.violation_ids.unlink()
        key = integrity.get_hmac_key(self.env)
        chains = self.env['audit.chain'].sudo().search([])
        checked, violations = 0, []
        for chain in chains:
            count, found = self._verify_chain(chain, key)
            checked += count
            violations.extend(found)
        backlog = self.env['audit.log'].sudo().search_count([
            ('seal_state', '=', 'unsealed'),
            ('seal_after', '<', fields.Datetime.now() - timedelta(hours=UNSEALED_WARNING_HOURS)),
        ])
        if backlog:
            violations.append({'kind': 'unsealed_backlog', 'detail': _(
                "%s events are waiting for sealing for more than %s hour(s).",
                backlog, UNSEALED_WARNING_HOURS)})
        self.write({
            'state': 'failed' if violations else 'passed',
            'chain_count': len(chains), 'checked_count': checked,
            'violation_count': len(violations), 'unsealed_backlog': backlog,
            'duration': (fields.Datetime.now() - started).total_seconds(),
            'violation_ids': [(0, 0, v) for v in violations],
        })
        return self

    # ------------------------------------------------------------------
    def _verify_chain(self, chain, key):
        violations = []
        checkpoint = self.env['audit.checkpoint']._latest(chain.chain_key)
        if checkpoint and not checkpoint._signature_valid():
            violations.append(self._violation(chain, checkpoint.seq_to, 'invalid_checkpoint',
                                              _("Checkpoint signature does not match.")))
        expected_seq = checkpoint.seq_to + 1 if checkpoint else 1
        expected_prev = checkpoint.last_hash if checkpoint else integrity.genesis_hash(chain.chain_key)
        count = 0
        while expected_seq <= chain.last_seq:
            window = self._load_window(chain.chain_key, expected_seq, expected_seq + VERIFY_WINDOW - 1)
            if not window:
                violations.append(self._violation(chain, expected_seq, 'gap', _(
                    "Events %s..%s are missing without checkpoint.", expected_seq, chain.last_seq)))
                break
            for seq in range(expected_seq, min(expected_seq + VERIFY_WINDOW, chain.last_seq + 1)):
                item = window.get(seq)
                if item is None:
                    violations.append(self._violation(chain, seq, 'gap', _("Event is missing.")))
                    expected_prev = None
                    continue
                count += 1
                violations.extend(self._verify_item(chain, seq, item, expected_prev, key))
                expected_prev = item['hash']
            expected_seq += VERIFY_WINDOW
        if chain.last_seq and expected_prev and expected_prev != chain.last_hash:
            violations.append(self._violation(chain, chain.last_seq, 'tail',
                                              _("Chain tail does not match the recorded last hash.")))
        return count, violations

    def _verify_item(self, chain, seq, item, expected_prev, key):
        found = []
        if expected_prev is not None and item['previous_hash'] != expected_prev:
            found.append(self._violation(chain, seq, 'link', _("Previous hash does not link."),
                                         item.get('reference')))
        if item['kind'] == 'tombstone':
            return found
        recomputed = integrity.chain_hash(
            item['previous_hash'], integrity.canonical_event(item['log'], item['lines']))
        if recomputed != item['hash']:
            found.append(self._violation(chain, seq, 'modified', _("Event content was modified."),
                                         item.get('reference')))
        log = item['log']
        snapshots = {k: log.get(k) for k in ('before_snapshot', 'after_snapshot', 'delete_snapshot')
                     if log.get(k)}
        if snapshots and not log.get('redacted') and \
                integrity.digest(key, snapshots) != log.get('snapshot_digest'):
            found.append(self._violation(chain, seq, 'value_modified', _("Snapshot was modified."),
                                         item.get('reference')))
        for line in item['lines']:
            if not line.get('redacted') and (
                    integrity.digest(key, line['old_value_json']) != line['old_digest']
                    or integrity.digest(key, line['new_value_json']) != line['new_digest']):
                found.append(self._violation(chain, seq, 'value_modified', _(
                    "Value of field %s does not match its digest.", line['field_name']),
                    item.get('reference')))
        return found

    def _load_window(self, chain_key, seq_from, seq_to):
        items = {}
        domain = [('chain_key', '=', chain_key), ('seal_seq', '>=', seq_from), ('seal_seq', '<=', seq_to)]
        for log in self.env['audit.log'].sudo().search(domain + [('seal_state', '=', 'sealed')]):
            items[log.seal_seq] = {
                'kind': 'hot', 'reference': log.reference, 'hash': log.hash,
                'previous_hash': log.previous_hash, 'log': log._plain(),
                'lines': [line._plain() for line in log.line_ids],
            }
        for row in self.env['audit.log.archive'].sudo().search(domain):
            payload = row.payload or {}
            items[row.seal_seq] = {
                'kind': 'archive', 'reference': row.reference, 'hash': row.hash,
                'previous_hash': row.previous_hash, 'log': payload.get('log', {}),
                'lines': payload.get('lines', []),
            }
        for stone in self.env['audit.log.tombstone'].sudo().search(domain):
            items[stone.seal_seq] = {'kind': 'tombstone', 'reference': stone.reference,
                                     'hash': stone.hash, 'previous_hash': stone.previous_hash}
        return items

    @staticmethod
    def _violation(chain, seq, kind, detail, reference=None):
        return {'chain_key': chain.chain_key, 'seal_seq': seq, 'kind': kind,
                'detail': detail, 'reference': reference or False}


class AuditIntegrityViolation(models.Model):
    _name = 'audit.integrity.violation'
    _description = 'Audit Integrity Violation'
    _order = 'check_id desc, chain_key, seal_seq'

    check_id = fields.Many2one('audit.integrity.check', required=True, ondelete='cascade')
    chain_key = fields.Char()
    seal_seq = fields.Integer()
    reference = fields.Char()
    kind = fields.Selection([
        ('gap', 'Missing event'), ('link', 'Broken link'), ('modified', 'Modified event'),
        ('value_modified', 'Modified value'), ('invalid_checkpoint', 'Invalid checkpoint'),
        ('tail', 'Truncated tail'), ('unsealed_backlog', 'Unsealed backlog'),
    ])
    detail = fields.Char()
