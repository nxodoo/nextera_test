# -*- coding: utf-8 -*-
"""Read persisted state straight from PostgreSQL.

Capturing through SQL instead of the ORM gives the real persisted value at the
moment of observation (stored computed fields included), never triggers
computations, and never flushes - which matters because some captures happen
inside Odoo's own flush (``_write_multi``).
"""
import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

TRUNC_MARK = '\x1fNXTRUNC:'
SECRET_MARK = '\x1fNXSECRET:'


def _column_expression(table, fname, kind, max_chars):
    col = SQL.identifier(table, fname)
    if kind == 'binary':
        return SQL(
            "CASE WHEN %s IS NULL THEN NULL ELSE 'md5:' || md5(%s) || ':' || octet_length(%s) END",
            col, col, col,
        )
    if kind == 'secret':
        return SQL(
            "CASE WHEN %s IS NULL THEN NULL ELSE %s || md5(%s::text) END",
            col, SECRET_MARK, col,
        )
    if kind == 'text':
        return SQL(
            "CASE WHEN length(%s) > %s THEN %s || length(%s) || ':' || md5(%s) || ':' || left(%s, %s)"
            " ELSE %s END",
            col, max_chars, TRUNC_MARK, col, col, col, max_chars, col,
        )
    return col


def fetch_rows(cr, plan, ids, max_chars):
    """Return {id: {fname: raw_value}} for existing ids only."""
    ids = [i for i in ids if isinstance(i, int)]
    if not ids or not plan['columns']:
        return {i: {} for i in ids} if ids and not plan['columns'] else {}
    table = plan['table']
    exprs = [SQL.identifier(table, 'id')]
    names = []
    for fname, kind in plan['columns']:
        exprs.append(_column_expression(table, fname, kind, max_chars))
        names.append(fname)
    result = {}
    for sub_ids in cr.split_for_in_conditions(ids):
        cr.execute(SQL(
            "SELECT %s FROM %s WHERE %s IN %s",
            SQL(", ").join(exprs), SQL.identifier(table),
            SQL.identifier(table, 'id'), tuple(sub_ids),
        ))
        for row in cr.fetchall():
            result[row[0]] = dict(zip(names, row[1:]))
    return result


def fetch_m2m(cr, spec, ids):
    """spec = (fname, relation, column1, column2)."""
    _fname, relation, column1, column2 = spec
    result = {i: set() for i in ids}
    for sub_ids in cr.split_for_in_conditions(ids):
        cr.execute(SQL(
            "SELECT %s, %s FROM %s WHERE %s IN %s",
            SQL.identifier(column1), SQL.identifier(column2),
            SQL.identifier(relation), SQL.identifier(column1), tuple(sub_ids),
        ))
        for x, y in cr.fetchall():
            result.setdefault(x, set()).add(y)
    return result


def fetch_o2m(cr, spec, ids):
    """spec = (fname, comodel_table, inverse_column)."""
    _fname, table, inverse = spec
    result = {i: set() for i in ids}
    for sub_ids in cr.split_for_in_conditions(ids):
        cr.execute(SQL(
            "SELECT %s, id FROM %s WHERE %s IN %s",
            SQL.identifier(inverse), SQL.identifier(table),
            SQL.identifier(inverse), tuple(sub_ids),
        ))
        for parent, child in cr.fetchall():
            result.setdefault(parent, set()).add(child)
    return result


def fetch_referencing_ids(cr, table, column, target_ids):
    """Ids of rows in ``table`` whose ``column`` points to ``target_ids``."""
    found = set()
    for sub_ids in cr.split_for_in_conditions(list(target_ids)):
        cr.execute(SQL(
            "SELECT id FROM %s WHERE %s IN %s",
            SQL.identifier(table), SQL.identifier(column), tuple(sub_ids),
        ))
        found.update(r[0] for r in cr.fetchall())
    return found


def fetch_relation_owners(cr, relation, owner_column, target_column, target_ids):
    found = set()
    for sub_ids in cr.split_for_in_conditions(list(target_ids)):
        cr.execute(SQL(
            "SELECT DISTINCT %s FROM %s WHERE %s IN %s",
            SQL.identifier(owner_column), SQL.identifier(relation),
            SQL.identifier(target_column), tuple(sub_ids),
        ))
        found.update(r[0] for r in cr.fetchall())
    return found


def existing_ids(cr, table, ids):
    found = set()
    for sub_ids in cr.split_for_in_conditions(list(ids)):
        cr.execute(SQL(
            "SELECT id FROM %s WHERE id IN %s", SQL.identifier(table), tuple(sub_ids),
        ))
        found.update(r[0] for r in cr.fetchall())
    return found


def match_domain(env, model_name, domain, ids):
    """Ids among ``ids`` matching ``domain`` against the *database* state.

    Uses ``_where_calc`` + a raw execute: no flush, no record rules, so it can
    run inside a flush and reflects exactly what is persisted. Rule domains
    are restricted to stored fields (see audit.rule constraints). On any
    error the record is considered in scope (fail-open for evidence).
    """
    ids = [i for i in ids if isinstance(i, int)]
    if not ids:
        return set()
    model = env[model_name].sudo().with_context(active_test=False)
    try:
        matched = set()
        # non-flushing savepoint: a broken domain must never abort the
        # business transaction
        with env.cr.savepoint(flush=False):
            for sub_ids in env.cr.split_for_in_conditions(ids):
                query = model._where_calc(domain, active_test=False)
                query.add_where(SQL("%s IN %s", SQL.identifier(model._table, 'id'), tuple(sub_ids)))
                env.cr.execute(query.select())
                matched.update(r[0] for r in env.cr.fetchall())
        return matched
    except Exception:  # noqa: BLE001 - evidence must not be lost on a bad domain
        _logger.warning("Audit domain evaluation failed on %s %s", model_name, domain, exc_info=True)
        return set(ids)
