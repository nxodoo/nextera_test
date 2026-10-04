# -*- coding: utf-8 -*-
import logging
import re

from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError
from odoo.osv import expression

from ..services.context import SOURCE_SELECTION

_logger = logging.getLogger(__name__)

# Models that are never audited by the generic engine: they are the audit
# engine itself, transport/infrastructure tables, or would recurse.
HARD_EXCLUDED_MODELS = frozenset({
    'bus.bus', 'bus.presence', 'mail.presence', 'ir.cron.trigger', 'ir.cron.progress',
    'res.users.log', 'res.device', 'res.device.log', 'mail.tracking.value',
    'mail.message', 'mail.notification', 'mail.followers', 'mail.mail',
    'ir.logging', 'ir.profile', 'ir.model.data', 'ir.model.fields.selection',
    'ir.model.constraint', 'ir.model.relation', 'ir.module.module.dependency',
    'ir.module.module.exclusion', 'ir.asset', 'ir.qweb', 'base_import.import',
    'base_import.mapping', 'mail.message.reaction', 'mail.link.preview',
    'mail.guest', 'discuss.channel.member', 'discuss.channel.rtc.session',
    'mail.scheduled.message',
})
# Default soft exclusions for the broad "all models" rule (editable).
DEFAULT_GLOBAL_EXCLUDED_MODELS = (
    'stock.quant', 'stock.move.line', 'ir.attachment', 'ir.ui.view', 'ir.ui.menu',
    'mail.activity', 'ir.default', 'ir.sequence', 'ir.sequence.date_range',
    'ir.config_parameter', 'res.users.settings', 'mail.alias', 'ir.module.module',
    'ir.module.category', 'digest.digest', 'iap.account', 'web_tour.tour',
    'res.users.settings.volumes', 'account.move.line', 'stock.move',
)
DEFAULT_EXCLUDED_FIELDS = (
    'write_date,write_uid,create_date,create_uid,__last_update,message_ids,'
    'message_follower_ids,activity_ids,message_main_attachment_id,'
    'website_message_ids,parent_path,standard_price,access_token'
)
BUILTIN_SECRET_RE = re.compile(
    r'(^|_)(password|passwd|pwd|secret|token|api_?key|apikey|private_?key|otp|totp|'
    r'credential|signature_key|client_secret|refresh_token|access_key)s?($|_)',
    re.IGNORECASE,
)
OPERATION_FLAGS = (
    ('op_create', 'create'), ('op_update', 'update'), ('op_delete', 'delete'),
    ('op_read', 'read'), ('op_export', 'export'), ('op_report', 'report'),
    ('op_action', 'action'),
)
ENGINE_PARAMS = {
    'preview_length': ('nx_audit_log.preview_length', int, 300),
    'max_value_chars': ('nx_audit_log.max_value_chars', int, 20000),
    'bulk_read_threshold': ('nx_audit_log.bulk_read_threshold', int, 500),
    'bulk_batch_threshold': ('nx_audit_log.bulk_batch_threshold', int, 100),
    'seal_delay_seconds': ('nx_audit_log.seal_delay_seconds', int, 120),
    'auth_bucket_minutes': ('nx_audit_log.auth_bucket_minutes', int, 10),
    'audit_lang': ('nx_audit_log.audit_lang', str, 'en_US'),
    'fail_mode': ('nx_audit_log.fail_mode', str, 'open'),
    'audit_all_exports': ('nx_audit_log.audit_all_exports', 'bool', True),
    'store_unknown_logins': ('nx_audit_log.store_unknown_logins', 'bool', False),
    'excluded_fields': ('nx_audit_log.excluded_fields', 'set', DEFAULT_EXCLUDED_FIELDS),
}


class AuditSource(models.Model):
    _name = 'audit.source'
    _description = 'Audit Execution Source'
    _order = 'sequence, id'

    code = fields.Selection(SOURCE_SELECTION, required=True)
    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [('code_uniq', 'unique(code)', 'Source codes must be unique.')]


class AuditRule(models.Model):
    _name = 'audit.rule'
    _description = 'Audit Rule'
    _inherit = ['audit.config.mixin']
    _order = 'sequence, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10, help="Lower sequence wins when several rules match.")
    scope = fields.Selection(
        [('model', 'One model'), ('all', 'All eligible models')],
        default='model', required=True,
    )
    model_id = fields.Many2one('ir.model', ondelete='cascade', domain=[('transient', '=', False)])
    model_name = fields.Char('Model Name', related='model_id.model', store=True, index=True)
    excluded_model_ids = fields.Many2many(
        'ir.model', 'audit_rule_excluded_model_rel', 'rule_id', 'model_id',
        string='Excluded Models', help="Only for rules covering all models.")
    company_ids = fields.Many2many(
        'res.company', string='Companies', help="Empty means all companies.")
    domain = fields.Char(
        default='[]', help="Only records matching this domain (before OR after the change) "
                           "are audited. Stored fields only.")

    op_create = fields.Boolean('Create', default=True)
    op_update = fields.Boolean('Update', default=True)
    op_delete = fields.Boolean('Delete', default=True)
    op_read = fields.Boolean('Read', help="Aggregated per request. Expensive: off by default.")
    op_export = fields.Boolean('Export', default=True)
    op_report = fields.Boolean('Print / Report')
    op_action = fields.Boolean('Business Actions', default=True)
    action_methods = fields.Char(
        help="Comma separated method names. Empty means every button method.")

    field_mode = fields.Selection(
        [('all', 'All fields'), ('selected', 'Selected fields only'),
         ('all_except', 'All fields except excluded')],
        default='all', required=True)
    field_ids = fields.Many2many(
        'ir.model.fields', 'audit_rule_field_rel', 'rule_id', 'field_id', string='Audited Fields',
        domain="[('model_id', '=', model_id)]")
    excluded_field_ids = fields.Many2many(
        'ir.model.fields', 'audit_rule_excluded_field_rel', 'rule_id', 'field_id',
        string='Excluded Fields', domain="[('model_id', '=', model_id)]")
    sensitive_field_ids = fields.Many2many(
        'ir.model.fields', 'audit_rule_sensitive_field_rel', 'rule_id', 'field_id',
        string='Secret Fields', domain="[('model_id', '=', model_id)]",
        help="Change is recorded, value is never stored.")
    derived_policy = fields.Selection(
        [('direct', 'Direct changes only'), ('selected', 'Direct + selected derived fields'),
         ('all', 'Direct + all derived fields')],
        default='all', required=True,
        help="Derived = values produced by recomputation, not written by the caller.")
    derived_field_ids = fields.Many2many(
        'ir.model.fields', 'audit_rule_derived_field_rel', 'rule_id', 'field_id',
        string='Derived Fields', domain="[('model_id', '=', model_id)]")

    user_ids = fields.Many2many('res.users', 'audit_rule_user_rel', 'rule_id', 'user_id',
                                string='Only Users')
    group_ids = fields.Many2many('res.groups', 'audit_rule_group_rel', 'rule_id', 'group_id',
                                 string='Only Groups')
    excluded_user_ids = fields.Many2many('res.users', 'audit_rule_excl_user_rel', 'rule_id',
                                         'user_id', string='Excluded Users')
    excluded_group_ids = fields.Many2many('res.groups', 'audit_rule_excl_group_rel', 'rule_id',
                                          'group_id', string='Excluded Groups')
    source_ids = fields.Many2many('audit.source', string='Sources',
                                  help="Empty means every execution source.")

    snapshot_policy = fields.Selection(
        [('changed', 'Changed fields'), ('full', 'Full before/after snapshot')],
        default='changed', required=True,
        help="Deleted records always keep a delete snapshot.")
    retention_policy_id = fields.Many2one('audit.retention.policy', ondelete='restrict')
    chatter_mirror = fields.Boolean(
        help="Post a short summary on the record chatter. The audit tables stay the evidence.")
    notes = fields.Text()
    log_count = fields.Integer(compute='_compute_log_count')

    @api.depends('model_name')
    def _compute_log_count(self):
        counts = dict(self.env['audit.log']._read_group(
            [('rule_id', 'in', self.ids)], ['rule_id'], ['__count']))
        for rule in self:
            rule.log_count = counts.get(rule, 0)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('scope', 'model_id')
    def _check_model(self):
        for rule in self:
            if rule.scope == 'model' and not rule.model_id:
                raise ValidationError(_("Select the model audited by rule %s.", rule.name))
            if rule.model_id and rule.model_id.model.startswith('audit.'):
                raise ValidationError(_("Audit models cannot audit themselves."))
            if rule.model_id and not self._is_model_eligible(rule.model_id.model):
                raise ValidationError(_("Model %s cannot be audited (transient, technical or "
                                        "infrastructure model).", rule.model_id.model))

    @api.constrains('domain', 'model_id')
    def _check_domain(self):
        for rule in self.filtered(lambda r: r.domain and r.model_id):
            domain = rule._parsed_domain()
            Model = self.env[rule.model_id.model]
            for leaf in expression.normalize_domain(domain):
                if not isinstance(leaf, (list, tuple)) or len(leaf) != 3 \
                        or not isinstance(leaf[0], str):
                    continue
                rule._check_stored_path(Model, str(leaf[0]))

    def _check_stored_path(self, Model, path):
        for part in path.split('.'):
            field = Model._fields.get(part)
            if field is None or not field.store:
                raise ValidationError(_(
                    "Rule %(rule)s: domain field '%(path)s' must be a stored field "
                    "(domains are evaluated in SQL, also inside flushes).",
                    rule=self.name, path=path))
            if field.relational:
                Model = self.env[field.comodel_name]

    def _parsed_domain(self):
        self.ensure_one()
        try:
            domain = tools.safe_eval.safe_eval(self.domain or '[]')
        except Exception as exc:
            raise ValidationError(_("Invalid domain on rule %s: %s", self.name, exc)) from exc
        return domain if isinstance(domain, list) else []

    # ------------------------------------------------------------------
    # Cache invalidation & bindings
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        self._invalidate_plans()
        rules._sync_bindings()
        return rules

    def write(self, vals):
        result = super().write(vals)
        self._invalidate_plans()
        self._sync_bindings()
        return result

    def unlink(self):
        result = super().unlink()
        self._invalidate_plans()
        self.browse()._sync_bindings()
        return result

    @api.model
    def _invalidate_plans(self):
        self.env.registry.clear_cache()

    @api.model
    def _sync_bindings(self):
        """One 'Audit Trail' entry in the Action menu of each explicitly audited model."""
        Action = self.env['ir.actions.server'].sudo()
        marker = '# nx_audit_trail'
        audited = set(self.sudo().search([('scope', '=', 'model')]).mapped('model_id').ids)
        existing = Action.with_context(active_test=False).search([('code', 'like', marker)])
        for action in existing:
            if action.model_id.id not in audited:
                action.unlink()
        bound = set(existing.exists().mapped('model_id').ids)
        group = self.env.ref('nx_audit_log.group_audit_user', raise_if_not_found=False)
        for model_id in audited - bound:
            Action.create({
                'name': _('Audit Trail'),
                'model_id': model_id,
                'binding_model_id': model_id,
                'binding_type': 'action',
                'state': 'code',
                'group_ids' if 'group_ids' in Action._fields else 'groups_id':
                    [(6, 0, group.ids)] if group else [],
                'code': f"{marker}\naction = env['audit.log'].action_open_trail(model._name, records.ids)",
            })

    # ------------------------------------------------------------------
    # Engine settings
    # ------------------------------------------------------------------
    @api.model
    @tools.ormcache()
    def _get_engine_settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        settings = {}
        for name, (key, kind, default) in ENGINE_PARAMS.items():
            raw = icp.get_param(key)
            raw = None if raw in (False, None, '') else raw
            if kind == 'bool':
                value = default if raw in (None, '') else raw in ('1', 'True', 'true')
            elif kind == 'set':
                value = frozenset(f.strip() for f in (raw if raw is not None else default).split(',')
                                  if f.strip())
            elif kind is int:
                try:
                    value = int(raw) if raw not in (None, '') else default
                except ValueError:
                    value = default
            else:
                value = raw or default
            settings[name] = value
        return settings

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    @api.model
    @tools.ormcache('model_name')
    def _is_model_eligible(self, model_name):
        if not model_name or model_name.startswith('audit.') or model_name in HARD_EXCLUDED_MODELS:
            return False
        Model = self.env.registry.get(model_name)
        if Model is None:
            return False
        if Model._transient or Model._abstract or not Model._table:
            return False
        if Model._auto:
            return True
        # _auto = False: real tables (e.g. res.users.apikeys) yes, SQL views (reports) no
        self.env.cr.execute("SELECT relkind FROM pg_class WHERE relname = %s", [Model._table])
        row = self.env.cr.fetchone()
        return bool(row and row[0] in ('r', 'p'))

    # ------------------------------------------------------------------
    # Plan compilation
    # ------------------------------------------------------------------
    @api.model
    @tools.ormcache('model_name')
    def _get_plan(self, model_name):
        """Compiled, immutable audit plan of one model (None = not audited).

        Cached per worker with ``ormcache``; any rule/setting change calls
        ``registry.clear_cache()`` which is signalled to every worker.
        """
        if not self._is_model_eligible(model_name):
            return None
        rules = self.sudo().with_context(active_test=True).search([], order='sequence, id')
        specs = self._rule_specs_for(model_name, rules)
        if not specs:
            return None
        return self._compile_plan(model_name, specs)

    def _rule_specs_for(self, model_name, rules):
        explicit = [r._spec() for r in rules if r.scope == 'model' and r.model_name == model_name]
        if explicit:
            return tuple(explicit)
        implicit = self._implicit_child_specs(model_name, rules)
        global_specs = [
            r._spec() for r in rules
            if r.scope == 'all' and model_name not in r.excluded_model_ids.mapped('model')
        ]
        return tuple(implicit + global_specs)

    def _implicit_child_specs(self, model_name, rules):
        """A rule on sale.order auditing order_line audits sale.order.line too."""
        specs = []
        for rule in rules.filtered(lambda r: r.scope == 'model' and r.model_name):
            Parent = self.env.registry.get(rule.model_name)
            if Parent is None:
                continue
            parent_spec = rule._spec()
            Child = self.env.registry.get(model_name)
            for fname, field in Parent._fields.items():
                if field.type != 'one2many' or field.comodel_name != model_name:
                    continue
                inverse = Child._fields.get(field.inverse_name)
                # only owned lines (inverse many2one with ondelete cascade, e.g.
                # order_id / move_id): auditing a company must not audit all partners
                if inverse is None or inverse.type != 'many2one' or inverse.ondelete != 'cascade':
                    continue
                if self._spec_allows_field(parent_spec, fname):
                    spec = dict(parent_spec)
                    spec.update({
                        'implicit': True, 'domain': None, 'field_mode': 'all',
                        'fields': frozenset(), 'excluded': frozenset(),
                        'derived_policy': 'all',
                        'ops': parent_spec['ops'] & {'create', 'update', 'delete'},
                        'snapshot_policy': 'changed',
                    })
                    specs.append(spec)
                    break
        return specs

    @staticmethod
    def _spec_allows_field(spec, fname):
        if spec['field_mode'] == 'selected':
            return fname in spec['fields']
        return fname not in spec['excluded']

    def _spec(self):
        self.ensure_one()
        ops = frozenset(op for flag, op in OPERATION_FLAGS if self[flag])
        domain = self._parsed_domain() if self.domain and self.domain.strip() not in ('', '[]') else None
        return {
            'id': self.id,
            'name': self.name,
            'implicit': False,
            'ops': ops,
            'field_mode': self.field_mode,
            'fields': frozenset(self.field_ids.mapped('name')),
            'excluded': frozenset(self.excluded_field_ids.mapped('name')),
            'sensitive': frozenset(self.sensitive_field_ids.mapped('name')),
            'derived_policy': self.derived_policy,
            'derived_fields': frozenset(self.derived_field_ids.mapped('name')),
            'domain': domain,
            'user_ids': frozenset(self.user_ids.ids),
            'group_ids': frozenset(self.group_ids.ids),
            'excluded_user_ids': frozenset(self.excluded_user_ids.ids),
            'excluded_group_ids': frozenset(self.excluded_group_ids.ids),
            'sources': frozenset(self.source_ids.mapped('code')),
            'company_ids': frozenset(self.company_ids.ids),
            'snapshot_policy': self.snapshot_policy,
            'retention_policy_id': self.retention_policy_id.id,
            'action_methods': frozenset(
                m.strip() for m in (self.action_methods or '').split(',') if m.strip()),
            'chatter_mirror': self.chatter_mirror,
        }

    def _compile_plan(self, model_name, specs):
        Model = self.env[model_name]
        secret, personal = self._sensitivity_for(model_name, specs)
        columns, m2m, o2m, o2m_comodel, m2m_inverse = [], [], [], {}, []
        for fname, field in Model._fields.items():
            if fname == 'id' or not field.store:
                continue
            allowed = any(self._spec_allows_field(spec, fname) for spec in specs)
            if field.column_type:
                columns.append((fname, self._column_kind(field, fname in secret)))
            elif field.type == 'many2many':
                spec = (fname, field.relation, field.column1, field.column2)
                if allowed:
                    m2m.append(spec)
                inverse = self._m2m_inverse_spec(field)
                if inverse:
                    m2m_inverse.append(inverse)
            elif field.type == 'one2many' and allowed:
                comodel = self.env.registry.get(field.comodel_name)
                inverse = comodel and comodel._fields.get(field.inverse_name)
                if comodel is not None and inverse is not None and inverse.store \
                        and inverse.type == 'many2one' and self._is_model_eligible(field.comodel_name):
                    o2m.append((fname, comodel._table, field.inverse_name))
                    o2m_comodel[fname] = field.comodel_name
        company_field = Model._fields.get('company_id')
        fk_cascade, fk_set_null, m2m_owners = self._fk_specs(model_name)
        return {
            'model': model_name,
            'table': Model._table,
            'columns': tuple(columns),
            'm2m': tuple(m2m),
            'o2m': tuple(o2m),
            'o2m_comodel': o2m_comodel,
            'm2m_inverse': tuple(m2m_inverse),
            'fk_cascade': fk_cascade,
            'fk_set_null': fk_set_null,
            'm2m_owners': m2m_owners,
            'company_field': 'company_id' if company_field is not None and company_field.store
            and company_field.type == 'many2one' and company_field.comodel_name == 'res.company'
            and not company_field.company_dependent else None,
            'rules': specs,
            'ops': frozenset().union(*(spec['ops'] for spec in specs)),
            'secret_fields': frozenset(secret),
            'personal_fields': personal,
        }

    @staticmethod
    def _column_kind(field, is_secret):
        if is_secret:
            return 'secret'
        if field.type == 'binary':
            return 'binary'
        if field.type in ('text', 'html') and not field.translate:
            return 'text'
        return 'plain'

    def _m2m_inverse_spec(self, field):
        Comodel = self.env.registry.get(field.comodel_name)
        if Comodel is None:
            return None
        for cofield in Comodel._fields.values():
            if cofield.type == 'many2many' and cofield.store and cofield.relation == field.relation \
                    and cofield is not field:
                return (field.name, field.comodel_name, field.relation, field.column1, field.column2)
        return None

    def _fk_specs(self, model_name):
        cascade, set_null, owners = [], [], []
        for other_name, Other in self.env.registry.items():
            if not self._is_model_eligible(other_name):
                continue
            for fname, field in Other._fields.items():
                if not field.store or field.comodel_name != model_name:
                    continue
                if field.type == 'many2one' and field.column_type and not field.company_dependent:
                    if field.ondelete == 'cascade':
                        cascade.append((other_name, Other._table, fname))
                    elif field.ondelete == 'set null':
                        set_null.append((other_name, Other._table, fname))
                elif field.type == 'many2many':
                    owners.append((other_name, field.relation, field.column1, field.column2, fname))
        return tuple(cascade), tuple(set_null), tuple(owners)

    def _sensitivity_for(self, model_name, specs):
        Model = self.env[model_name]
        secret = set().union(*(spec['sensitive'] for spec in specs))
        personal = {}
        patterns = self.env['audit.sensitive.pattern'].sudo()._compiled_patterns()
        for fname in Model._fields:
            if BUILTIN_SECRET_RE.search(fname):
                secret.add(fname)
                continue
            for category, model_re, field_re, mode in patterns:
                if model_re and not model_re.search(model_name):
                    continue
                if not field_re.search(fname):
                    continue
                if category == 'secret':
                    secret.add(fname)
                else:
                    personal.setdefault(fname, mode)
        for fname in secret:
            personal.pop(fname, None)
        return secret, personal

    # ------------------------------------------------------------------
    # Default configuration
    # ------------------------------------------------------------------
    @api.model
    def _load_default_rules(self):
        """Idempotent: creates default rules for models present in this database."""
        policies = self.env['audit.retention.policy'].sudo()._ensure_default_policies()
        for values in self._default_rule_definitions(policies):
            model = self.env['ir.model'].sudo()._get(values['model'])
            if not model or self.with_context(active_test=False).search_count(
                    [('model_id', '=', model.id), ('name', '=', values['name'])]):
                continue
            self._create_default_rule(model, values)
        self._ensure_global_rule()

    def _create_default_rule(self, model, values):
        vals = {k: v for k, v in values.items() if k not in ('model', 'fields', 'sensitive')}
        vals['model_id'] = model.id
        for key, target in (('fields', 'field_ids'), ('sensitive', 'sensitive_field_ids')):
            if values.get(key):
                field_ids = self.env['ir.model.fields'].sudo().search(
                    [('model', '=', model.model), ('name', 'in', values[key])]).ids
                vals[target] = [(6, 0, field_ids)]
        return self.create(vals)

    def _ensure_global_rule(self):
        if self.with_context(active_test=False).search_count([('scope', '=', 'all')]):
            return
        excluded = self.env['ir.model'].sudo().search(
            [('model', 'in', list(DEFAULT_GLOBAL_EXCLUDED_MODELS))])
        self.create({
            'name': 'All business models (Create / Update / Delete)',
            'scope': 'all',
            'active': False,
            'sequence': 1000,
            'op_export': True,
            'op_action': False,
            'derived_policy': 'direct',
            'excluded_model_ids': [(6, 0, excluded.ids)],
            'notes': 'Broad policy. Activate after reviewing excluded models; explicit '
                     'model rules always take precedence.',
        })

    @api.model
    def _default_rule_definitions(self, policies):
        finance = policies['finance'].id
        security = policies['security'].id
        standard = policies['standard'].id
        return [
            {'model': 'account.move', 'name': 'Journal entries & invoices', 'sequence': 5,
             'op_report': True, 'retention_policy_id': finance, 'snapshot_policy': 'full'},
            {'model': 'account.payment', 'name': 'Payments', 'retention_policy_id': finance,
             'op_report': True},
            {'model': 'account.account', 'name': 'Chart of accounts', 'retention_policy_id': finance},
            {'model': 'res.partner.bank', 'name': 'Bank accounts', 'retention_policy_id': finance},
            {'model': 'sale.order', 'name': 'Sales orders', 'retention_policy_id': standard,
             'op_report': True},
            {'model': 'purchase.order', 'name': 'Purchase orders', 'retention_policy_id': standard,
             'op_report': True},
            {'model': 'stock.picking', 'name': 'Transfers', 'retention_policy_id': standard},
            {'model': 'stock.quant', 'name': 'Stock quantities (selected fields)',
             'field_mode': 'selected', 'derived_policy': 'direct', 'op_action': False,
             'fields': ['quantity', 'location_id', 'lot_id', 'package_id', 'owner_id'],
             'retention_policy_id': standard},
            {'model': 'res.partner', 'name': 'Contacts', 'retention_policy_id': standard,
             'derived_policy': 'direct'},
            {'model': 'res.users', 'name': 'Users & access', 'retention_policy_id': security,
             'sensitive': ['password']},
            {'model': 'res.groups', 'name': 'Security groups', 'retention_policy_id': security,
             'field_mode': 'selected', 'fields': ['users', 'implied_ids', 'name']},
            {'model': 'ir.model.access', 'name': 'Access rights', 'retention_policy_id': security},
            {'model': 'ir.rule', 'name': 'Record rules', 'retention_policy_id': security},
            {'model': 'res.company', 'name': 'Companies', 'retention_policy_id': security},
            {'model': 'res.users.apikeys', 'name': 'API keys', 'retention_policy_id': security,
             'sensitive': ['key']},
            {'model': 'ir.config_parameter', 'name': 'System parameters',
             'retention_policy_id': security},
            {'model': 'ir.attachment', 'name': 'Attachments (metadata only)',
             'field_mode': 'selected', 'op_update': False, 'op_export': False,
             'fields': ['name', 'mimetype', 'file_size', 'res_model', 'res_id', 'type'],
             'domain': "[('res_model', 'not in', ['ir.ui.view', 'ir.qweb', 'mail.compose.message']),"
                       " ('res_field', '=', False)]",
             'retention_policy_id': standard},
        ]
