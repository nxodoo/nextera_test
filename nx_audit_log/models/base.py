# -*- coding: utf-8 -*-
"""Single, central ORM interception point (no per-model audit code).

Hooks only *observe*; evidence is produced at commit by the finalizer.
"""
from odoo import api, models

from ..services import context as audit_context
from ..services import observer


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not audit_context.is_bypassed():
            observer.observe_create(records, vals_list)
        return records

    def write(self, vals):
        if not audit_context.is_bypassed():
            observer.observe_write(self, vals)
        return super().write(vals)

    def _write_multi(self, vals_list):
        if not audit_context.is_bypassed():
            observer.observe_flush(self, vals_list)
        return super()._write_multi(vals_list)

    def unlink(self):
        if not audit_context.is_bypassed():
            observer.observe_unlink(self)
        return super().unlink()

    def copy(self, default=None):
        if audit_context.is_bypassed():
            return super().copy(default)
        with audit_context.copy_scope(self):
            return super().copy(default)

    def export_data(self, fields_to_export):
        result = super().export_data(fields_to_export)
        if not audit_context.is_bypassed():
            observer.record_event(
                self.env, 'export', model=self._name, count=len(self),
                ids=[i for i in self._ids if isinstance(i, int)][:1000],
                fields=list(fields_to_export)[:200],
            )
        return result

    def load(self, fields, data):
        if audit_context.current_frame('import') or audit_context.is_bypassed():
            return super().load(fields, data)
        with audit_context.execution('import', f'load:{self._name}', self._name):
            result = super().load(fields, data)
        observer.record_event(
            self.env, 'import', key=f'load:{self._name}', model=self._name,
            count=len(result.get('ids') or []), fields=list(fields)[:200],
            failed=len([m for m in result.get('messages', []) if m.get('type') == 'error']),
            file_name=False,
        )
        return result

    # ------------------------------------------------------------------
    # Extension API
    # ------------------------------------------------------------------
    def _audit_dynamic_secret_fields(self, row):
        """Fields to mask for this specific row (override per model).

        ``row`` holds raw column values of the record (before or after).
        """
        return ()
