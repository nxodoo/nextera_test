# -*- coding: utf-8 -*-
"""Request-boundary aggregation for external API reads.

``odoo.service.model.execute_cr`` is the single point every XML-RPC /
JSON-RPC ``execute_kw`` call goes through, with the business cursor still
open. Read-like calls are aggregated per request into one access entry,
never one row per record.
"""
import logging

from . import context as audit_context
from . import observer

_logger = logging.getLogger(__name__)

READ_METHODS = frozenset({
    'read', 'search_read', 'web_read', 'web_search_read', 'read_group',
    'web_read_group', 'export_data', 'name_search', 'search',
})
_PATCHED = False


def result_count(method, result):
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict) and isinstance(result.get('records'), list):
        return len(result['records'])
    if isinstance(result, dict) and isinstance(result.get('groups'), list):
        return sum(g.get('__count', 0) for g in result['groups'] if isinstance(g, dict))
    return 0


def result_ids(result):
    rows = result
    if isinstance(result, dict):
        rows = result.get('records') or []
    if isinstance(rows, list):
        ids = []
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get('id'), int):
                ids.append(row['id'])
            elif isinstance(row, int):
                ids.append(row)
        return ids
    return []


def requested_fields(method, args, kwargs):
    fields = kwargs.get('fields') or kwargs.get('specification')
    if fields is None and method in ('read', 'search_read') and len(args) > 1:
        fields = args[1]
    if isinstance(fields, dict):
        fields = list(fields)
    return [f for f in (fields or []) if isinstance(f, str)][:200]


def register_api_read(env, model, method, args, kwargs, result, api):
    if method not in READ_METHODS or method == 'export_data':
        return
    observer.record_event(
        env, 'read', model=model, method=method, api=api,
        count=result_count(method, result), ids=result_ids(result)[:1000],
        fields=requested_fields(method, args, kwargs),
    )


def install():
    global _PATCHED
    if _PATCHED:
        return
    from odoo.service import model as service_model
    original = service_model.execute_cr

    def execute_cr(cr, uid, obj, method, *args, **kw):
        result = original(cr, uid, obj, method, *args, **kw)
        try:
            if audit_context.rpc_meta() is not None and method in READ_METHODS:
                from odoo import api
                env = api.Environment(cr, uid, {})
                if 'audit.rule' in env.registry:
                    register_api_read(env, obj, method, list(args), kw, result, api=True)
        except Exception:  # noqa: BLE001 - never break an RPC call
            _logger.debug("nx_audit_log: API read aggregation failed", exc_info=True)
        return result

    service_model.execute_cr = execute_cr
    _PATCHED = True
