# -*- coding: utf-8 -*-
"""Integrity primitives.

* Value digests are HMAC-SHA256 over the canonical JSON of each value. The
  canonical event hash uses those digests, so a governed redaction can remove
  a plaintext value without breaking verification.
* The HMAC key should live in the server configuration file
  (``nx_audit_hmac_key``), outside the database. If absent, a key stored in
  ``ir.config_parameter`` is used and the settings screen warns about it.
"""
import hashlib
import hmac
import secrets

from odoo.tools import config

from .serializer import canonical_json

HASH_VERSION = 1
GENESIS_PREFIX = 'GENESIS:'
ICP_KEY = 'nx_audit_log.hmac_key'
CONFIG_KEY = 'nx_audit_hmac_key'


def key_source():
    return 'config' if config.get(CONFIG_KEY) else 'database'


def get_hmac_key(env):
    configured = config.get(CONFIG_KEY)
    if configured:
        return configured.encode()
    icp = env['ir.config_parameter'].sudo()
    value = icp.get_param(ICP_KEY)
    if not value:
        value = secrets.token_hex(32)
        icp.set_param(ICP_KEY, value)
    return value.encode()


def key_id(key):
    return hashlib.sha256(key).hexdigest()[:12]


def digest(key, value):
    return hmac.new(key, canonical_json(value).encode(), hashlib.sha256).hexdigest()


def genesis_hash(chain_key):
    return hashlib.sha256((GENESIS_PREFIX + chain_key).encode()).hexdigest()


def chain_hash(previous_hash, canonical_payload):
    return hashlib.sha256((previous_hash + canonical_payload).encode()).hexdigest()


def canonical_event(log, lines):
    """Canonical payload from plain dicts (works for hot and archived rows).

    Only raw technical values and digests: no translated labels, no display
    names, no preview text.
    """
    payload = {
        'v': log['hash_version'],
        'id': log['id'],
        'chain': log['chain_key'],
        'seq': log['seal_seq'],
        'at': log['event_datetime'],
        'op': log['operation'],
        'model': log['model_name'],
        'res_id': log['res_id'] or None,
        'uid': log['user_id'] or None,
        'company': log['company_id'] or None,
        'source': log['source'],
        'method': log['action_method'] or None,
        'result': log['result'],
        'count': log['record_count'] or 0,
        'attempts': log['attempt_count'] or 0,
        'snapshot': log['snapshot_digest'] or None,
        'corr': log['correlation_id'] or None,
        'lines': sorted(
            [
                [line['id'], line['field_name'], line['change_type'], line['change_origin'],
                 line['lang'] or None, bool(line['masked']),
                 line['old_digest'] or None, line['new_digest'] or None]
                for line in lines
            ],
            key=lambda item: item[0],
        ),
    }
    return canonical_json(payload)
