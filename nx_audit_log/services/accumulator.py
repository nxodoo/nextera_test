# -*- coding: utf-8 -*-
"""Per-transaction accumulator.

Design decisions (see doc/ARCHITECTURE.md):

* The accumulator is attached to the database cursor, not to an Odoo
  environment, so every environment sharing the transaction feeds it.
* ``captures`` holds the first-observed database state of each touched record.
  It is read straight from PostgreSQL before the first change reaches the
  table, so it is the true BEFORE state for direct *and* derived changes.
* ``journal`` holds what happened (touch, delete, action, read, export...).
  A savepoint remembers the journal length and a ROLLBACK TO SAVEPOINT
  truncates it, so work undone by a savepoint never becomes evidence.
* Finalisation runs only when the transaction is really committed (not on the
  intermediate flushes Odoo performs when a savepoint is opened), so one
  logical transaction yields one event per record.
"""
import itertools
import logging
import uuid
import weakref

from . import context as audit_context

_logger = logging.getLogger(__name__)

_ACCUMULATORS = weakref.WeakKeyDictionary()
_OP_COUNTER = itertools.count(1)


class RecordCapture:
    """First observed database state of one record in this transaction."""
    __slots__ = ('row', 'm2m', 'o2m', 'domain_before', 'existed')

    def __init__(self, row, existed):
        self.row = row
        self.existed = existed
        self.m2m = {}
        self.o2m = {}
        self.domain_before = {}


class Accumulator:
    def __init__(self):
        self.captures = {}          # (model, id) -> RecordCapture
        self.journal = []           # ordered entries (dicts)
        self.correlation_id = None
        self.meta = None
        self.deferred = []          # events to persist after a read-only commit
        self.display_names = {}     # (model, id) -> name captured before deletion
        self.created_keys = set()   # (model, id) created in this transaction

    # -- lifecycle ---------------------------------------------------------
    def ensure_meta(self):
        if self.meta is None:
            self.meta = audit_context.request_meta()
            self.correlation_id = (
                self.meta.get('correlation_id') or uuid.uuid4().hex
            )
        return self.meta

    def truncate(self, mark):
        if mark < len(self.journal):
            del self.journal[mark:]

    def has_pending(self):
        return bool(self.journal)

    def consume(self):
        journal, self.journal = self.journal, []
        captures, self.captures = self.captures, {}
        names, self.display_names = self.display_names, {}
        self.created_keys = set()
        return journal, captures, names

    # -- journal helpers -----------------------------------------------------
    def add(self, entry):
        self.ensure_meta()
        entry.setdefault('source', audit_context.resolve_source(self.meta))
        entry.setdefault('execution_path', audit_context.execution_path())
        action = audit_context.current_action()
        entry.setdefault('action_key', action['key'] if action else None)
        self.journal.append(entry)
        return entry

    def captured(self, model_name, record_id):
        return self.captures.get((model_name, record_id))


def new_operation_id():
    return next(_OP_COUNTER)


def get_accumulator(cr, create=False):
    acc = _ACCUMULATORS.get(cr)
    if acc is None and create:
        acc = _ACCUMULATORS[cr] = Accumulator()
    return acc


def drop_accumulator(cr):
    _ACCUMULATORS.pop(cr, None)


# ---------------------------------------------------------------------------
# Cursor / savepoint patches
# ---------------------------------------------------------------------------
_PATCHED = False


def _patch_commit(cursor_class):
    original = cursor_class.commit

    def commit(self):
        acc = _ACCUMULATORS.get(self)
        if acc is not None and acc.has_pending() and not audit_context.is_guarded():
            from . import finalizer
            finalizer.finalize_before_commit(self, acc)
        result = original(self)
        acc = _ACCUMULATORS.pop(self, None)
        if acc is not None and acc.deferred:
            from . import finalizer
            finalizer.persist_deferred(self.dbname, acc.deferred)
        return result

    commit._nx_audit_original = original
    cursor_class.commit = commit


def _patch_rollback(cursor_class):
    original = cursor_class.rollback

    def rollback(self):
        _ACCUMULATORS.pop(self, None)
        return original(self)

    rollback._nx_audit_original = original
    cursor_class.rollback = rollback


def _patch_savepoint(savepoint_class):
    original_init = savepoint_class.__init__
    original_rollback = savepoint_class.rollback

    def __init__(self, cr):
        original_init(self, cr)
        acc = _ACCUMULATORS.get(cr)
        self._nx_audit_mark = len(acc.journal) if acc is not None else 0

    def rollback(self):
        original_rollback(self)
        acc = _ACCUMULATORS.get(self._cr)
        if acc is not None:
            acc.truncate(getattr(self, '_nx_audit_mark', 0))

    savepoint_class.__init__ = __init__
    savepoint_class.rollback = rollback


def install_patches():
    """Idempotently hook the PostgreSQL cursor classes.

    The hooks are no-ops for databases where the module is not installed:
    an accumulator only exists once the ORM hooks of this module created one.
    """
    global _PATCHED
    if _PATCHED:
        return
    from odoo import sql_db
    for cursor_class in (sql_db.Cursor, sql_db.TestCursor):
        _patch_commit(cursor_class)
        _patch_rollback(cursor_class)
    _patch_savepoint(sql_db.Savepoint)
    _PATCHED = True
    _logger.info("nx_audit_log: transaction hooks installed")
