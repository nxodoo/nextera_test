# -*- coding: utf-8 -*-
"""Observation layer: called from the BaseModel hooks.

Each function does one thing: register what happened (journal) and make sure
the BEFORE state of every touched record is captured exactly once, straight
from the database, before the change reaches the table.
"""
import logging

from odoo import SUPERUSER_ID

from . import accumulator as acc_module
from . import capture
from . import context as audit_context

_logger = logging.getLogger(__name__)

FK_MAX_DEPTH = 3
FK_MAX_RECORDS = 20000
OP_FOR_HOOK = {
    'create': 'create',
    'write': 'update',
    'flush': 'update',
    'unlink': 'delete',
}


# ---------------------------------------------------------------------------
# Plan lookup
# ---------------------------------------------------------------------------
def get_plan(env, model_name):
    registry = env.registry
    if not registry.ready or 'audit.rule' not in registry:
        return None
    if model_name.startswith('audit.'):
        return None
    return env['audit.rule']._get_plan(model_name)


def plan_for(records, hook):
    """Plan if ``records`` must be observed for ``hook``, else None."""
    if audit_context.is_bypassed():
        return None
    plan = get_plan(records.env, records._name)
    if not plan:
        return None
    if OP_FOR_HOOK[hook] not in plan['ops']:
        return None
    return plan


def _settings(env):
    return env['audit.rule']._get_engine_settings()


def _accumulator(env):
    return acc_module.get_accumulator(env.cr, create=True)


def _real_ids(records):
    return [i for i in records._ids if isinstance(i, int)]


# ---------------------------------------------------------------------------
# BEFORE-state capture
# ---------------------------------------------------------------------------
def capture_before(env, plan, ids, acc):
    """Capture first-observed DB state for ids not yet captured."""
    model = plan['model']
    new_ids = [
        i for i in ids
        if (model, i) not in acc.captures and (model, i) not in acc.created_keys
    ]
    if not new_ids:
        return
    cr = env.cr
    rows = capture.fetch_rows(cr, plan, new_ids, _settings(env)['max_value_chars'])
    for record_id in new_ids:
        acc.captures[(model, record_id)] = acc_module.RecordCapture(
            rows.get(record_id, {}), record_id in rows)
    existing = [i for i in new_ids if i in rows]
    if not existing:
        return
    for spec in plan['m2m']:
        values = capture.fetch_m2m(cr, spec, existing)
        for record_id in existing:
            acc.captures[(model, record_id)].m2m[spec[0]] = values.get(record_id, set())
    for spec in plan['o2m']:
        values = capture.fetch_o2m(cr, spec, existing)
        for record_id in existing:
            acc.captures[(model, record_id)].o2m[spec[0]] = values.get(record_id, set())
    for rule in plan['rules']:
        if not rule['domain']:
            continue
        matched = capture.match_domain(env, model, rule['domain'], existing)
        for record_id in existing:
            acc.captures[(model, record_id)].domain_before[rule['id']] = record_id in matched


def _touch(acc, env, model, ids, kind, direct=None, **extra):
    entry = {
        'type': 'touch',
        'kind': kind,
        'model': model,
        'ids': tuple(ids),
        'direct': direct or {},
        'uid': env.uid,
        'su': env.su,
        'op_id': acc_module.new_operation_id(),
        'copy_of': audit_context.current_copy_source(),
        'import_key': (audit_context.current_frame('import') or (None, None))[1],
    }
    entry.update(extra)
    acc.add(entry)
    return entry


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------
def observe_create(records, vals_list):
    plan = plan_for(records, 'create')
    if not plan:
        return
    env = records.env
    acc = _accumulator(env)
    ids = _real_ids(records)
    direct = {
        record_id: frozenset(vals)
        for record_id, vals in zip(records._ids, vals_list) if isinstance(record_id, int)
    }
    acc.created_keys.update((records._name, i) for i in ids)
    _touch(acc, env, records._name, ids, 'create', direct)


def observe_write(records, vals):
    plan = plan_for(records, 'write')
    if not plan:
        return
    env = records.env
    acc = _accumulator(env)
    ids = _real_ids(records)
    if not ids:
        return
    capture_before(env, plan, ids, acc)
    _capture_m2m_inverse(env, records, plan, vals, acc)
    names = frozenset(vals)
    _touch(acc, env, records._name, ids, 'write', {i: names for i in ids})


def observe_flush(records, vals_list):
    """Stored values about to be persisted by Odoo's flush (incl. recompute)."""
    plan = plan_for(records, 'flush')
    if not plan:
        return
    env = records.env
    acc = _accumulator(env)
    ids = _real_ids(records)
    if not ids:
        return
    capture_before(env, plan, ids, acc)
    _touch(acc, env, records._name, ids, 'flush')


def observe_unlink(records):
    plan = plan_for(records, 'unlink')
    if not plan:
        return
    env = records.env
    ids = _real_ids(records)
    if not ids:
        return
    env.flush_all()
    acc = _accumulator(env)
    capture_before(env, plan, ids, acc)
    _capture_deletion(env, plan, ids, acc, 'unlink', depth=0)


# ---------------------------------------------------------------------------
# Deletion & database-level FK effects
# ---------------------------------------------------------------------------
def _remember_names(env, model, ids, acc):
    settings = _settings(env)
    records = env[model].sudo().with_context(
        active_test=False, lang=settings['audit_lang'], prefetch_fields=False,
    ).browse(ids)
    try:
        for record in records:
            acc.display_names[(model, record.id)] = record.display_name
    except Exception:  # noqa: BLE001 - a failing name must not block a delete
        _logger.debug("Could not compute display names for %s", model, exc_info=True)


def _capture_deletion(env, plan, ids, acc, kind, depth, parent=None):
    model = plan['model']
    snapshots = capture.fetch_rows(env.cr, plan, ids, _settings(env)['max_value_chars'])
    _remember_names(env, model, ids, acc)
    _touch(acc, env, model, ids, kind, snapshots=snapshots, parent=parent)
    if depth >= FK_MAX_DEPTH:
        return
    _capture_fk_cascade(env, plan, ids, acc, depth)
    _capture_fk_set_null(env, plan, ids, acc)
    _capture_m2m_owners(env, plan, ids, acc)


def _capture_fk_cascade(env, plan, ids, acc, depth):
    for child_model, table, column in plan['fk_cascade']:
        child_plan = get_plan(env, child_model)
        if not child_plan:
            continue
        child_ids = capture.fetch_referencing_ids(env.cr, table, column, ids)
        child_ids -= {i for (m, i) in acc.captures if m == child_model and _deleted(acc, m, i)}
        if not child_ids:
            continue
        child_ids = _bounded(child_model, child_ids)
        capture_before(env, child_plan, child_ids, acc)
        _capture_deletion(env, child_plan, list(child_ids), acc, 'fk_cascade', depth + 1,
                          parent=(plan['model'], column))


def _capture_fk_set_null(env, plan, ids, acc):
    for child_model, table, column in plan['fk_set_null']:
        child_plan = get_plan(env, child_model)
        if not child_plan:
            continue
        child_ids = _bounded(child_model, capture.fetch_referencing_ids(env.cr, table, column, ids))
        if not child_ids:
            continue
        capture_before(env, child_plan, child_ids, acc)
        _touch(acc, env, child_model, child_ids, 'fk_set_null', fk_field=column)


def _capture_m2m_owners(env, plan, ids, acc):
    for owner_model, relation, owner_column, target_column, fname in plan['m2m_owners']:
        owner_plan = get_plan(env, owner_model)
        if not owner_plan or fname not in {spec[0] for spec in owner_plan['m2m']}:
            continue
        owner_ids = _bounded(owner_model, capture.fetch_relation_owners(
            env.cr, relation, owner_column, target_column, ids))
        if not owner_ids:
            continue
        capture_before(env, owner_plan, owner_ids, acc)
        _touch(acc, env, owner_model, owner_ids, 'fk_m2m', fk_field=fname)


def _deleted(acc, model, record_id):
    return any(
        e['type'] == 'touch' and e['model'] == model and record_id in e['ids']
        and e['kind'] in ('unlink', 'fk_cascade')
        for e in acc.journal
    )


def _bounded(model, ids):
    if len(ids) > FK_MAX_RECORDS:
        _logger.warning("Audit FK capture on %s truncated to %s records", model, FK_MAX_RECORDS)
        return set(sorted(ids)[:FK_MAX_RECORDS])
    return ids


# ---------------------------------------------------------------------------
# Many2many inverse side (e.g. res.groups.users vs res.users.groups_id)
# ---------------------------------------------------------------------------
def _command_ids(value):
    ids = set()
    for command in value or ():
        if isinstance(command, int):
            ids.add(command)
        elif isinstance(command, (list, tuple)) and command:
            if command[0] in (1, 2, 3, 4) and len(command) > 1:
                ids.add(command[1])
            elif command[0] == 6 and len(command) > 2:
                ids.update(command[2] or ())
    return {i for i in ids if isinstance(i, int)}


def _capture_m2m_inverse(env, records, plan, vals, acc):
    ids = _real_ids(records)
    for fname, comodel, relation, column1, column2 in plan['m2m_inverse']:
        if fname not in vals:
            continue
        coplan = get_plan(env, comodel)
        if not coplan:
            continue
        current = capture.fetch_m2m(env.cr, (fname, relation, column1, column2), ids)
        corecord_ids = set().union(*current.values()) | _command_ids(vals[fname])
        if not corecord_ids:
            continue
        capture_before(env, coplan, corecord_ids, acc)
        _touch(acc, env, comodel, corecord_ids, 'm2m_inverse')


# ---------------------------------------------------------------------------
# Access / semantic events
# ---------------------------------------------------------------------------
def record_event(env, entry_type, **values):
    """Append an access/semantic entry (read, export, report, action...)."""
    if audit_context.is_bypassed():
        return
    if not env.registry.ready or 'audit.rule' not in env.registry:
        return
    acc = _accumulator(env)
    entry = {'type': entry_type, 'uid': env.uid, 'su': env.su}
    entry.update(values)
    acc.add(entry)


def superuser_env(env):
    from odoo import api
    return api.Environment(env.cr, SUPERUSER_ID, {})
