# -*- coding: utf-8 -*-
"""Public API for custom modules.

    from odoo.addons.nx_audit_log.services.api import audit_action, audit_bypass

    class SaleOrder(models.Model):
        _inherit = 'sale.order'

        @audit_action('Approve Discount')
        def action_approve_discount(self):
            ...

Field changes made inside the decorated method are linked to the semantic
ACTION event. The ACTION event is persisted only if the transaction commits.
"""
import contextlib
import functools
import uuid

from . import accumulator as acc_module
from . import context as audit_context
from . import observer
from .context import audit_bypass  # noqa: F401 - re-exported

KNOWN_LABELS = {
    'action_confirm': 'Confirm',
    'button_confirm': 'Confirm',
    'action_post': 'Post',
    'button_validate': 'Validate',
    'action_done': 'Mark as Done',
    'action_approve': 'Approve',
    'button_approve': 'Approve',
    'action_draft': 'Reset to Draft',
    'button_draft': 'Reset to Draft',
    'action_cancel': 'Cancel',
    'button_cancel': 'Cancel',
    'action_lock': 'Lock',
    'action_unlock': 'Unlock',
    'action_reverse': 'Reverse',
    'action_register_payment': 'Register Payment',
    'action_archive': 'Archive',
    'action_unarchive': 'Unarchive',
}


def label_for(method):
    return KNOWN_LABELS.get(method) or method.replace('_', ' ').strip().capitalize()


@contextlib.contextmanager
def semantic_action(records, method, label=None):
    """Register a semantic ACTION and link nested field changes to it."""
    current = audit_context.current_action()
    plan = observer.get_plan(records.env, records._name)
    if (current and current['model'] == records._name and current['method'] == method) \
            or not plan or 'action' not in plan['ops'] or audit_context.is_bypassed():
        yield
        return
    action = {
        'key': uuid.uuid4().hex,
        'model': records._name,
        'method': method,
        'label': label or label_for(method),
    }
    display_name = False
    ids = [i for i in records._ids if isinstance(i, int)]
    if len(ids) == 1:
        try:
            display_name = records.sudo().browse(ids).display_name
        except Exception:  # noqa: BLE001
            display_name = False
    with audit_context.action_scope(action):
        observer.record_event(
            records.env, 'action', key=action['key'], model=records._name, ids=ids,
            method=method, label=action['label'], display_name=display_name,
        )
        yield


def audit_action(label=None):
    """Decorator turning a model method into an audited semantic action."""
    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            with semantic_action(self, method.__name__, label):
                return method(self, *args, **kwargs)
        return wrapper
    return decorator


def record_action(records, label, method=None):
    """Imperative variant for code paths that cannot use the decorator."""
    with semantic_action(records, method or label, label):
        pass


def flush_audit(env):
    """Finalize pending evidence of the current transaction without committing.

    Intended for tests and for long-running scripts that want evidence
    written progressively.
    """
    acc = acc_module.get_accumulator(env.cr)
    if acc is not None and acc.has_pending():
        from .finalizer import finalize_before_commit
        finalize_before_commit(env.cr, acc)
        if acc.deferred:
            deferred, acc.deferred = acc.deferred, []
            for events, batches in deferred:
                with audit_context.guarded():
                    env['audit.log'].sudo()._audit_persist(events, batches)
