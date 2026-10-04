# -*- coding: utf-8 -*-
"""Audit models are excluded from the generic engine (no recursion), so their
own configuration changes are recorded explicitly through this mixin."""
import json

from odoo import api, fields, models

from ..services import context as audit_context
from ..services.serializer import json_safe

SKIP_FIELDS = {'write_date', 'write_uid', 'create_date', 'create_uid', 'display_name', 'log_count'}


class AuditConfigMixin(models.AbstractModel):
    _name = 'audit.config.mixin'
    _description = 'Audited configuration'

    def _config_fields(self):
        return [
            fname for fname, field in self._fields.items()
            if field.store and fname not in SKIP_FIELDS and fname != 'id'
            and field.type not in ('binary', 'one2many')
        ]

    def _config_values(self):
        fnames = self._config_fields()
        values = {}
        for record in self.sudo():
            row = {}
            for fname in fnames:
                value = record[fname]
                if isinstance(value, models.BaseModel):
                    value = {'ids': value.ids, 'names': value.mapped('display_name')}
                row[fname] = json_safe(value)
            values[record.id] = row
        return values

    def _config_logging_enabled(self):
        return not (audit_context.is_guarded() or self.env.context.get('install_mode')
                    or not self.env.registry.ready)

    def _log_config_change(self, operation, before, after):
        lines_by_record = {}
        for record_id in set(before) | set(after):
            old, new = before.get(record_id, {}), after.get(record_id, {})
            lines = []
            for fname in sorted(set(old) | set(new)):
                if old.get(fname) == new.get(fname):
                    continue
                lines.append({
                    'field_name': fname,
                    'field_label': self._fields[fname].string,
                    'field_type': self._fields[fname].type,
                    'model_name': self._name,
                    'change_type': 'change',
                    'change_origin': 'direct',
                    'old_value_json': {'v': old.get(fname)},
                    'new_value_json': {'v': new.get(fname)},
                    'old_value_text': json.dumps(old.get(fname), default=str)[:300] if fname in old else False,
                    'new_value_text': json.dumps(new.get(fname), default=str)[:300] if fname in new else False,
                })
            if lines or operation != 'UPDATE':
                lines_by_record[record_id] = lines
        if lines_by_record:
            self.env['audit.log'].sudo()._record_config_events(
                self._name, operation, lines_by_record)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records._config_logging_enabled():
            records._log_config_change('CONFIG', {}, records._config_values())
        return records

    def write(self, vals):
        if not self._config_logging_enabled():
            return super().write(vals)
        before = self._config_values()
        result = super().write(vals)
        self._log_config_change('CONFIG', before, self._config_values())
        return result

    def unlink(self):
        if not self._config_logging_enabled():
            return super().unlink()
        before = self._config_values()
        result = super().unlink()
        self._log_config_change('CONFIG', before, {})
        return result
