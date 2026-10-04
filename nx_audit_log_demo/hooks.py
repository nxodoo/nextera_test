# -*- coding: utf-8 -*-
import logging

from odoo.addons.nx_audit_log.services import context as audit_context

_logger = logging.getLogger(__name__)

MODULE = 'nx_audit_log_demo'
# deletion order: dependents first
MODEL_ORDER = ['audit.redaction.request', 'res.users', 'ir.config_parameter', 'res.partner',
               'res.partner.category', 'audit.rule']


def post_init_hook(env):
    """Generate the demo evidence during installation.

    The audit engine normally ignores operations while modules are loading,
    so capture is explicitly enabled for this block. If generation fails for
    any reason, installation still succeeds and the one-shot job retries
    after installation (also available from Audit > Configuration).
    """
    cron = env.ref(f'{MODULE}.cron_generate_demo')
    try:
        with env.cr.savepoint(), audit_context.capture_during_install():
            env['nx.audit.demo']._generate_once()
        cron.active = False
    except Exception:  # noqa: BLE001 - never block the installation
        _logger.exception("nx_audit_log_demo: generation during install failed, retrying via cron")
        cron._trigger()


def uninstall_hook(env):
    """Remove every demo record and every demo audit event, without creating
    new evidence and without touching real hash chains."""
    with audit_context.audit_bypass('nx_audit_log_demo uninstall'), audit_context.guarded():
        removed_events = _remove_demo_evidence(env)
        removed_records = _remove_demo_records(env)
        env['ir.config_parameter'].sudo().search([('key', '=like', f'{MODULE}.%')]).unlink()
    _logger.info("nx_audit_log_demo uninstalled: %s demo events and %s demo records removed",
                 removed_events, removed_records)


def _remove_demo_evidence(env):
    Log = env['audit.log'].sudo()
    logs = Log.search([('chain_key', '=like', 'demo-%')])
    alerts = env['audit.alert'].sudo().search([('log_ids', 'in', logs.ids)])
    batches = logs.mapped('batch_id')
    count = len(logs)
    alerts.unlink()
    with audit_context.privileged('uninstall'):
        logs.unlink()
        env['audit.log.archive'].sudo().search([('chain_key', '=like', 'demo-%')]).unlink()
        env['audit.log.tombstone'].sudo().search([('chain_key', '=like', 'demo-%')]).unlink()
        env['audit.checkpoint'].sudo().search([('chain_key', '=like', 'demo-%')]).unlink()
        env['audit.chain'].sudo().search([('chain_key', '=like', 'demo-%')]).unlink()
    batches.exists().filtered(lambda b: not b.log_ids).unlink()
    env['audit.integrity.check'].sudo().search([('name', '=like', '[Demo]%')]).unlink()
    return count


def _remove_demo_records(env):
    data = env['ir.model.data'].sudo().search([('module', '=', MODULE), ('model', 'in', MODEL_ORDER)])
    by_model = {}
    for entry in data:
        by_model.setdefault(entry.model, []).append(entry.res_id)
    removed = 0
    for model in MODEL_ORDER:
        records = env[model].sudo().with_context(active_test=False).browse(by_model.get(model, [])).exists()
        if model == 'res.partner':
            # children before parents
            records = records.sorted(lambda p: 0 if p.parent_id else 1)
        for record in records:
            removed += _unlink_or_archive(env, record)
    return removed


def _unlink_or_archive(env, record):
    try:
        with env.cr.savepoint():
            record.unlink()
        return 1
    except Exception:  # noqa: BLE001 - e.g. a user referenced by real data
        if 'active' in record._fields:
            record.active = False
            _logger.warning("Demo record %s could not be deleted and was archived", record)
        return 0
