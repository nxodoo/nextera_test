# -*- coding: utf-8 -*-
import datetime
import gzip
import json
import logging
import os

from odoo.tools import config

from .services import context as audit_context
from .services import integrity

_logger = logging.getLogger(__name__)

EXPORT_TABLES = ('audit_log', 'audit_log_line', 'audit_log_archive', 'audit_log_tombstone',
                 'audit_checkpoint', 'audit_chain')


def post_init_hook(env):
    integrity.get_hmac_key(env)
    with audit_context.guarded():
        env['audit.rule'].sudo()._load_default_rules()
        env['audit.alert.rule'].sudo()._load_default_alert_rules()
    env['audit.rule'].sudo()._sync_bindings()


def uninstall_hook(env):
    """Uninstalling drops every audit table: export all evidence first.

    The export is a gzip JSON-lines file per table in the server data
    directory. The server log records its location.
    """
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    folder = os.path.join(config['data_dir'], 'nx_audit_log_exports', env.cr.dbname, stamp)
    os.makedirs(folder, exist_ok=True)
    for table in EXPORT_TABLES:
        env.cr.execute("SELECT to_regclass(%s)", [table])
        if not env.cr.fetchone()[0]:
            continue
        path = os.path.join(folder, f'{table}.jsonl.gz')
        env.cr.execute(f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY id')  # noqa: S608
        with gzip.open(path, 'wt', encoding='utf-8') as handle:
            while True:
                rows = env.cr.fetchmany(5000)
                if not rows:
                    break
                for (row,) in rows:
                    handle.write(row + '\n')
    _logger.critical("nx_audit_log uninstalled on %s: evidence exported to %s", env.cr.dbname, folder)
    with open(os.path.join(folder, 'README.txt'), 'w', encoding='utf-8') as handle:
        json.dump({'database': env.cr.dbname, 'exported_at': stamp,
                   'note': 'Audit evidence exported before module uninstall.'}, handle)
    env['ir.actions.server'].sudo().search([('code', 'like', '# nx_audit_trail')]).unlink()
