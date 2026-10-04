# -*- coding: utf-8 -*-
import re

from odoo import api, models

from ..services import context as audit_context
from ..services import observer

SECRET_PARAMETER_RE = re.compile(
    r'(secret|password|passwd|token|api_?key|private|credential|hmac|signature)', re.IGNORECASE)


class IrCron(models.Model):
    _inherit = 'ir.cron'

    def _callback(self, cron_name, server_action_id):
        with audit_context.execution('cron', self.id, cron_name):
            return super()._callback(cron_name, server_action_id)


class IrActionsServer(models.Model):
    _inherit = 'ir.actions.server'

    def run(self):
        result = False
        for action in self:
            automation = 'base_automation_id' in action._fields and action.base_automation_id
            kind = 'automated_action' if automation else 'server_action'
            with audit_context.execution(kind, action.id, action.name):
                result = super(IrActionsServer, action).run()
        return result


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render(self, report_ref, res_ids, data=None):
        result = super()._render(report_ref, res_ids, data=data)
        if not audit_context.is_bypassed():
            report = self._get_report(report_ref)
            ids = [i for i in (res_ids or []) if isinstance(i, int)]
            observer.record_event(
                self.env, 'report', model=report.model or 'ir.actions.report',
                report=report.report_name, method=report.report_type,
                count=len(ids), ids=ids[:1000], fields=[],
            )
        return result


class IrConfigParameter(models.Model):
    _inherit = 'ir.config_parameter'

    def _audit_dynamic_secret_fields(self, row):
        if SECRET_PARAMETER_RE.search(row.get('key') or '') or (row.get('key') or '').startswith(
                'nx_audit_log.hmac'):
            return ('value',)
        return ()


class BaseImport(models.TransientModel):
    _inherit = 'base_import.import'

    def execute_import(self, fields, columns, options, dryrun=False):
        if dryrun or audit_context.is_bypassed():
            # dry runs execute inside a rolled back savepoint: never a real import
            return super().execute_import(fields, columns, options, dryrun=dryrun)
        key = f'import:{self.id}'
        with audit_context.execution('import', key, self.file_name or self.res_model):
            result = super().execute_import(fields, columns, options, dryrun=dryrun)
        messages = result.get('messages') or []
        observer.record_event(
            self.env, 'import', key=key, model=self.res_model,
            count=len(result.get('ids') or []), fields=[f for f in fields if f][:200],
            failed=len([m for m in messages if m.get('type') == 'error']),
            file_name=self.file_name,
        )
        return result
