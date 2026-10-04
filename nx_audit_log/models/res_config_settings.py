# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.sql import create_index

from ..services import integrity


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nx_audit_preview_length = fields.Integer(
        'Preview length', config_parameter='nx_audit_log.preview_length', default=300)
    nx_audit_max_value_chars = fields.Integer(
        'Max stored text length', config_parameter='nx_audit_log.max_value_chars', default=20000)
    nx_audit_bulk_read_threshold = fields.Integer(
        'Bulk API read threshold', config_parameter='nx_audit_log.bulk_read_threshold', default=500)
    nx_audit_bulk_batch_threshold = fields.Integer(
        'Bulk operation batch threshold', config_parameter='nx_audit_log.bulk_batch_threshold',
        default=100)
    nx_audit_seal_delay = fields.Integer(
        'Sealing delay (seconds)', config_parameter='nx_audit_log.seal_delay_seconds', default=120)
    nx_audit_auth_bucket = fields.Integer(
        'Failed login window (minutes)', config_parameter='nx_audit_log.auth_bucket_minutes', default=10)
    nx_audit_lang = fields.Char(
        'Evidence language', config_parameter='nx_audit_log.audit_lang', default='en_US')
    nx_audit_fail_mode = fields.Selection(
        [('open', 'Keep business running and record an engine error'),
         ('closed', 'Block the transaction')],
        string='If auditing fails', config_parameter='nx_audit_log.fail_mode', default='open')
    nx_audit_all_exports = fields.Boolean(
        'Audit every export', config_parameter='nx_audit_log.audit_all_exports', default=True)
    nx_audit_store_unknown_logins = fields.Boolean(
        'Store unknown login names', config_parameter='nx_audit_log.store_unknown_logins',
        help="Typed logins that match no user are stored hashed by default: people "
             "sometimes type their password in the login field.")
    nx_audit_excluded_fields = fields.Char(
        'Excluded fields', config_parameter='nx_audit_log.excluded_fields')
    nx_audit_key_source = fields.Char('Integrity key', compute='_compute_nx_audit_key_source')

    def _compute_nx_audit_key_source(self):
        source = integrity.key_source()
        for settings in self:
            settings.nx_audit_key_source = _('Server configuration file') if source == 'config' else _(
                'Database (set nx_audit_hmac_key in odoo.conf)')

    def set_values(self):
        icp = self.env['ir.config_parameter'].sudo()
        before = {k: icp.get_param(k) for k in self._nx_audit_params()}
        super().set_values()
        after = {k: icp.get_param(k) for k in self._nx_audit_params()}
        if before != after:
            self.env.registry.clear_cache()
            lines = [{
                'field_name': k, 'field_label': k, 'field_type': 'char', 'model_name': 'res.config.settings',
                'change_type': 'change', 'change_origin': 'direct',
                'old_value_json': {'v': before[k]}, 'new_value_json': {'v': after[k]},
                'old_value_text': before[k] or False, 'new_value_text': after[k] or False,
            } for k in after if before[k] != after[k]]
            self.env['audit.log'].sudo()._record_config_events('res.config.settings', 'CONFIG', {0: lines})

    def _nx_audit_params(self):
        return [field.config_parameter for name, field in self._fields.items()
                if name.startswith('nx_audit_') and getattr(field, 'config_parameter', None)]

    def action_nx_audit_load_defaults(self):
        self.env['audit.rule'].sudo()._load_default_rules()
        self.env['audit.alert.rule'].sudo()._load_default_alert_rules()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'message': _("Default audit rules loaded for the installed applications."),
            'type': 'success', 'sticky': False}}

    def action_nx_audit_seal_now(self):
        sealed = self.env['audit.chain'].sudo()._cron_seal()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'message': _("%s events sealed.", sealed), 'type': 'success', 'sticky': False}}

    def action_nx_audit_enable_trigram(self):
        if not self.env.registry.has_trigram:
            raise UserError(_("The PostgreSQL extension pg_trgm is not available."))
        for column in ('old_value_text', 'new_value_text'):
            create_index(self.env.cr, f'audit_log_line_{column}_trgm_idx', 'audit_log_line',
                         [f'{column} gin_trgm_ops'], method='gin')
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'message': _("Value search indexes created."), 'type': 'success', 'sticky': False}}
