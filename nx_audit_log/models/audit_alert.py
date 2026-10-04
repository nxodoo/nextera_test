# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

TRIGGERS = [
    ('delete', 'Record deleted'),
    ('failed_operation', 'Failed operation (e.g. blocked delete)'),
    ('field_change', 'Field changed'),
    ('mass_delete', 'Many deletions by one user'),
    ('failed_login', 'Repeated failed logins'),
    ('action', 'Business action executed'),
]
SEVERITIES = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')]


class AuditAlertRule(models.Model):
    _name = 'audit.alert.rule'
    _description = 'Audit Alert Rule'
    _inherit = ['audit.config.mixin']
    _order = 'sequence, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    trigger = fields.Selection(TRIGGERS, required=True)
    severity = fields.Selection(SEVERITIES, default='medium', required=True)
    model_name = fields.Char(help="Technical model name. Empty matches every model.")
    field_name = fields.Char(help="For 'Field changed': technical field name.")
    action_method = fields.Char(help="For 'Business action': method name, empty = any.")
    threshold_type = fields.Selection(
        [('any', 'Any change'), ('absolute', 'Absolute difference'), ('percent', 'Percentage')],
        default='any', required=True)
    threshold = fields.Float()
    count_threshold = fields.Integer('Count', default=20,
                                     help="Mass delete / failed login: number of events.")
    window_minutes = fields.Integer('Window (minutes)', default=10)
    dedup_minutes = fields.Integer('Deduplicate (minutes)', default=30)
    max_per_hour = fields.Integer('Max alerts / hour', default=20)
    recipient_user_ids = fields.Many2many('res.users', 'audit_alert_rule_user_rel', 'rule_id',
                                          'user_id', string='Recipients')
    recipient_group_id = fields.Many2one('res.groups', string='Recipient Group')

    # ------------------------------------------------------------------
    # Evaluation (runs in the same transaction as the evidence)
    # ------------------------------------------------------------------
    @api.model
    def _evaluate_logs(self, logs):
        rules = self.search([])
        if not rules or not logs:
            return
        for rule in rules:
            matcher = getattr(rule, f'_match_{rule.trigger}')
            for log, dedup_key, message in matcher(logs):
                rule._raise_alert(log, dedup_key, message)

    def _model_ok(self, log):
        return not self.model_name or self.model_name == log.model_name

    def _match_delete(self, logs):
        for log in logs.filtered(lambda l: l.operation == 'DELETE' and self._model_ok(l)):
            yield log, f'delete:{log.model_name}:{log.res_id}', _(
                "%(model)s %(name)s deleted by %(user)s", model=log.model_name,
                name=log.record_display_name, user=log.user_login)

    def _match_failed_operation(self, logs):
        for log in logs.filtered(lambda l: l.operation == 'FAILED_ATTEMPT' and self._model_ok(l)):
            yield log, f'failed:{log.model_name}:{log.action_method}:{log.user_id.id}', _(
                "Failed %(method)s on %(model)s by %(user)s: %(reason)s", method=log.action_method,
                model=log.model_name, user=log.user_login, reason=(log.failure_reason or '')[:200])

    def _match_action(self, logs):
        for log in logs.filtered(lambda l: l.operation == 'ACTION' and self._model_ok(l)
                                 and (not self.action_method or l.action_method == self.action_method)):
            yield log, f'action:{log.id}', _("%(action)s on %(record)s by %(user)s",
                                             action=log.action_label, record=log.record_display_name,
                                             user=log.user_login)

    def _match_field_change(self, logs):
        for log in logs.filtered(lambda l: l.operation in ('UPDATE', 'CREATE') and self._model_ok(l)):
            for line in log.line_ids.filtered(lambda ln: ln.field_name == self.field_name):
                if not self._threshold_reached(line):
                    continue
                # the change content is part of the key: an escalation right after a
                # first change must not be swallowed by deduplication
                key = f'field:{log.model_name}:{log.res_id}:{line.field_name}:{line.change_type}:' \
                      f'{line.old_value_text or ""}>{line.new_value_text or ""}'
                if line.change_type in ('add', 'remove'):
                    yield log, key, _(
                        "%(field)s on %(record)s - %(kind)s: %(values)s", field=line.field_label,
                        record=log.record_display_name,
                        kind=_('added') if line.change_type == 'add' else _('removed'),
                        values=line.new_value_text if line.change_type == 'add' else line.old_value_text)
                else:
                    yield log, key, _(
                        "%(field)s changed on %(record)s: %(old)s \u2192 %(new)s",
                        field=line.field_label, record=log.record_display_name,
                        old=line.old_value_text or '', new=line.new_value_text or '')

    def _threshold_reached(self, line):
        if self.threshold_type == 'any':
            return True
        try:
            old = float((line.old_value_json or {}).get('v') or 0.0)
            new = float((line.new_value_json or {}).get('v') or 0.0)
        except (TypeError, ValueError, AttributeError):
            return True
        diff = abs(new - old)
        if self.threshold_type == 'absolute':
            return diff >= self.threshold
        return (diff / abs(old) * 100.0 if old else 100.0) >= self.threshold

    def _match_mass_delete(self, logs):
        deleters = set(logs.filtered(lambda l: l.operation == 'DELETE' and self._model_ok(l))
                       .mapped('user_id').ids)
        since = fields.Datetime.now() - timedelta(minutes=self.window_minutes)
        for uid in deleters:
            domain = [('operation', '=', 'DELETE'), ('user_id', '=', uid),
                      ('event_datetime', '>=', since)]
            if self.model_name:
                domain.append(('model_name', '=', self.model_name))
            count = self.env['audit.log'].search_count(domain)
            if count >= self.count_threshold:
                log = logs.filtered(lambda l: l.user_id.id == uid)[:1]
                yield log, f'mass_delete:{uid}', _(
                    "%(count)s deletions in %(minutes)s minutes by %(user)s",
                    count=count, minutes=self.window_minutes, user=log.user_login)

    def _match_failed_login(self, logs):
        for log in logs.filtered(lambda l: l.operation == 'FAILED_LOGIN'
                                 and l.attempt_count >= self.count_threshold):
            yield log, f'failed_login:{log.bucket_key}', _(
                "%(count)s failed logins for %(login)s from %(ip)s",
                count=log.attempt_count, login=log.record_display_name, ip=log.ip_address)

    # ------------------------------------------------------------------
    # Outbox with deduplication and rate limiting
    # ------------------------------------------------------------------
    def _raise_alert(self, log, dedup_key, message):
        Alert = self.env['audit.alert'].sudo()
        now = fields.Datetime.now()
        duplicate = Alert.search([
            ('rule_id', '=', self.id), ('dedup_key', '=', dedup_key),
            ('last_seen', '>=', now - timedelta(minutes=self.dedup_minutes)),
        ], limit=1)
        if duplicate:
            duplicate.write({'occurrence_count': duplicate.occurrence_count + 1, 'last_seen': now,
                             'log_ids': [(4, log.id)]})
            return duplicate
        recent = Alert.search_count([('rule_id', '=', self.id),
                                     ('create_date', '>=', now - timedelta(hours=1))])
        state = 'suppressed' if self.max_per_hour and recent >= self.max_per_hour else 'pending'
        alert = Alert.create({
            'name': message, 'rule_id': self.id, 'severity': self.severity, 'state': state,
            'dedup_key': dedup_key, 'first_seen': now, 'last_seen': now,
            'log_ids': [(6, 0, log.ids)], 'company_id': log.company_id.id,
        })
        if state == 'pending':
            cron = self.env.ref('nx_audit_log.cron_dispatch_alerts', raise_if_not_found=False)
            if cron:
                cron._trigger()
        return alert

    def _recipients(self):
        users = self.recipient_user_ids | self.recipient_group_id.users
        if not users:
            group = self.env.ref('nx_audit_log.group_audit_manager', raise_if_not_found=False)
            users = group.users if group else users
        return users.filtered('active')

    @api.model
    def _load_default_alert_rules(self):
        definitions = [
            {'name': 'Journal entry deleted', 'trigger': 'delete', 'model_name': 'account.move',
             'severity': 'high'},
            {'name': 'Journal entry deletion blocked', 'trigger': 'failed_operation',
             'model_name': 'account.move', 'severity': 'high'},
            {'name': 'Invoice total changed > 10%', 'trigger': 'field_change',
             'model_name': 'account.move', 'field_name': 'amount_total',
             'threshold_type': 'percent', 'threshold': 10.0, 'severity': 'high'},
            {'name': 'Bank account number changed', 'trigger': 'field_change',
             'model_name': 'res.partner.bank', 'field_name': 'acc_number', 'severity': 'critical'},
            {'name': 'User groups changed', 'trigger': 'field_change', 'model_name': 'res.users',
             'field_name': 'groups_id', 'severity': 'high'},
            {'name': 'Group members changed', 'trigger': 'field_change', 'model_name': 'res.groups',
             'field_name': 'users', 'severity': 'high', 'active': False},
            {'name': 'Mass deletion', 'trigger': 'mass_delete', 'count_threshold': 50,
             'window_minutes': 10, 'severity': 'critical'},
            {'name': 'Brute force login', 'trigger': 'failed_login', 'count_threshold': 10,
             'severity': 'critical'},
        ]
        for values in definitions:
            if not self.with_context(active_test=False).search_count([('name', '=', values['name'])]):
                self.create(values)


class AuditAlert(models.Model):
    _name = 'audit.alert'
    _description = 'Audit Alert'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True)
    rule_id = fields.Many2one('audit.alert.rule', ondelete='set null', readonly=True)
    severity = fields.Selection(SEVERITIES, readonly=True, tracking=True)
    state = fields.Selection([
        ('pending', 'Pending'), ('sent', 'Notified'), ('acknowledged', 'Acknowledged'),
        ('closed', 'Closed'), ('suppressed', 'Suppressed (rate limit)'),
    ], default='pending', required=True, tracking=True, index=True)
    dedup_key = fields.Char(index=True, readonly=True)
    occurrence_count = fields.Integer(default=1, readonly=True)
    first_seen = fields.Datetime(readonly=True)
    last_seen = fields.Datetime(readonly=True)
    log_ids = fields.Many2many('audit.log', 'audit_alert_log_rel', 'alert_id', 'log_id',
                               readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    note = fields.Text()

    def action_acknowledge(self):
        self.write({'state': 'acknowledged'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_open_logs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.name, 'res_model': 'audit.log',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.log_ids.ids)]}

    @api.model
    def _cron_dispatch(self, limit=200):
        """Post-commit delivery: alerts only exist once their evidence committed."""
        pending = self.search([('state', '=', 'pending')], limit=limit, order='id')
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for alert in pending:
            users = alert.rule_id._recipients()
            alert.message_post(
                body=alert.name, partner_ids=users.partner_id.ids,
                message_type='notification', subtype_xmlid='mail.mt_comment')
            if todo:
                for user in users:
                    alert.activity_schedule(activity_type_id=todo.id, user_id=user.id,
                                            summary=alert.name[:200])
            alert.state = 'sent'
        if len(pending) == limit:
            self.env.ref('nx_audit_log.cron_dispatch_alerts')._trigger()
