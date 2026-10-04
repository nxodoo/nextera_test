# -*- coding: utf-8 -*-
"""Turn the transaction journal into audit evidence.

Runs right before the real COMMIT. Because AFTER values are read from the
database once everything is flushed, the evidence is the final persisted
state; changes undone inside the transaction (savepoint rollbacks, writes
back to the original value) produce no event.
"""
import logging
import traceback
import uuid
from collections import defaultdict

from odoo import SUPERUSER_ID, api, fields

from . import capture
from . import context as audit_context
from . import integrity
from .observer import get_plan
from .serializer import ValueSerializer, is_secret_digest, values_equal

_logger = logging.getLogger(__name__)

READ_CAP_IDS = 1000
MAX_FINALIZE_ROUNDS = 4


# ===========================================================================
# Entry points (called from the cursor hooks)
# ===========================================================================
def finalize_before_commit(cr, acc):
    for _round in range(MAX_FINALIZE_ROUNDS):
        cr.flush()
        if not acc.has_pending():
            return
        _finalize_once(cr, acc)
    _logger.warning("nx_audit_log: audit finalisation did not converge")


def _finalize_once(cr, acc):
    env = api.Environment(cr, SUPERUSER_ID, {})
    settings = env['audit.rule']._get_engine_settings()
    journal, captures, names = acc.consume()
    try:
        with audit_context.guarded(), cr.savepoint():
            builder = EventBuilder(env, acc, journal, captures, names, settings)
            events, batches = builder.build()
            if not events:
                return
            if cr.readonly:
                acc.deferred.append((events, batches))
                return
            env['audit.log']._audit_persist(events, batches)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("nx_audit_log: audit finalisation failed")
        if settings['fail_mode'] == 'closed':
            raise
        acc.deferred.append(([engine_error_event(acc, exc)], []))


def persist_deferred(dbname, deferred):
    """Write events that could not be written in a read-only transaction."""
    from odoo.modules.registry import Registry
    try:
        registry = Registry(dbname)
        with registry.cursor() as cr, audit_context.guarded():
            env = api.Environment(cr, SUPERUSER_ID, {})
            for events, batches in deferred:
                env['audit.log']._audit_persist(events, batches)
    except Exception:  # noqa: BLE001 - never break the already committed request
        _logger.exception("nx_audit_log: could not persist deferred audit events")


def engine_error_event(acc, exc):
    meta = acc.meta or {}
    return {
        'key': uuid.uuid4().hex,
        'operation': 'ENGINE_ERROR',
        'model_name': 'audit.log',
        'res_id': False,
        'user_id': SUPERUSER_ID,
        'source': 'system',
        'result': 'failure',
        'failure_reason': ''.join(traceback.format_exception_only(type(exc), exc))[:2000],
        'correlation_id': acc.correlation_id,
        'is_shared': True,
        **_meta_values(meta),
    }


def _meta_values(meta):
    return {
        'ip_address': meta.get('ip_address') or False,
        'user_agent': meta.get('user_agent') or False,
        'claimed_client': meta.get('claimed_client') or False,
        'session_hash': meta.get('session_hash') or False,
        'request_path': meta.get('path') or False,
        'http_method': meta.get('http_method') or False,
        'initiating_user_id': meta.get('initiating_uid') or False,
    }


# ===========================================================================
# Journal folding
# ===========================================================================
class RecordState:
    __slots__ = (
        'model', 'id', 'created', 'deleted', 'direct', 'fk_fields', 'uid', 'su',
        'op_ids', 'action_keys', 'source', 'execution_path', 'copy_of', 'import_key',
        'snapshot', 'fk_parent',
    )

    def __init__(self, entry, record_id):
        self.model = entry['model']
        self.id = record_id
        self.created = False
        self.deleted = None
        self.direct = set()
        self.fk_fields = set()
        self.uid = entry['uid']
        self.su = entry['su']
        self.op_ids = []
        self.action_keys = []
        self.source = entry['source']
        self.execution_path = entry['execution_path']
        self.copy_of = entry.get('copy_of')
        self.import_key = entry.get('import_key')
        self.snapshot = None
        self.fk_parent = None


def fold_journal(journal):
    states = {}
    access, actions, imports = [], {}, {}
    for entry in journal:
        etype = entry['type']
        if etype == 'touch':
            _fold_touch(states, entry)
        elif etype == 'action':
            actions.setdefault(entry['key'], entry)
        elif etype == 'import':
            imports[entry['key']] = entry
        else:
            access.append(entry)
    return states, access, actions, imports


def _fold_touch(states, entry):
    kind = entry['kind']
    for record_id in entry['ids']:
        key = (entry['model'], record_id)
        state = states.get(key)
        if state is None:
            state = states[key] = RecordState(entry, record_id)
        if kind == 'create':
            state.created = True
            state.direct.update(entry['direct'].get(record_id, ()))
        elif kind == 'write':
            state.direct.update(entry['direct'].get(record_id, ()))
        elif kind in ('unlink', 'fk_cascade'):
            state.deleted = kind
            state.snapshot = entry.get('snapshots', {}).get(record_id)
            state.fk_parent = entry.get('parent')
        elif kind in ('fk_set_null', 'fk_m2m'):
            state.fk_fields.add(entry['fk_field'])
        if kind not in ('flush', 'm2m_inverse'):
            state.op_ids.append((entry['op_id'], kind))
        if entry.get('action_key') and entry['action_key'] not in state.action_keys:
            state.action_keys.append(entry['action_key'])
        if entry.get('import_key') and not state.import_key:
            state.import_key = entry['import_key']


# ===========================================================================
# Event building
# ===========================================================================
class RecordDraft:
    """Raw (not yet serialized) evidence for one record."""
    __slots__ = (
        'state', 'plan', 'rule', 'operation', 'before', 'after', 'changes',
        'company_before', 'company_after', 'parent', 'depth', 'child_links', 'key',
        'snapshot_mode',
    )

    def __init__(self, state, plan, rule, operation, before, after):
        self.state = state
        self.plan = plan
        self.rule = rule
        self.operation = operation
        self.before = before
        self.after = after
        self.changes = []
        self.company_before = None
        self.company_after = None
        self.parent = None
        self.depth = 0
        self.child_links = defaultdict(list)   # fname -> [(child_key, op)]
        self.key = uuid.uuid4().hex
        self.snapshot_mode = rule['snapshot_policy']


class EventBuilder:

    def __init__(self, env, acc, journal, captures, names, settings):
        self.env = env
        self.cr = env.cr
        self.acc = acc
        self.journal = journal
        self.captures = captures
        self.settings = settings
        self.meta = acc.meta or {}
        self.known_names = dict(names)
        self.Rule = env['audit.rule']
        self._user_groups = {}
        self._user_company = {}
        self._group_ids = {}
        self._hmac_key = None

    # -- orchestration -----------------------------------------------------
    def build(self):
        states, access, actions, imports = fold_journal(self.journal)
        drafts = self._build_record_drafts(states)
        self._link_children(drafts)
        action_events = self._build_action_events(actions)
        access_events = self._build_access_events(access)
        serializer = self._make_serializer(drafts)
        record_events = [self._serialize_draft(d, serializer) for d in drafts]
        self._attach_actions(record_events, action_events)
        batches = self._assign_batches(record_events, drafts, imports)
        import_events = self._build_import_events(imports)
        events = action_events + record_events + access_events + import_events
        return events, batches

    # -- shared helpers ------------------------------------------------------
    def _base_event(self, uid, source, execution_path):
        return {
            'key': uuid.uuid4().hex,
            'user_id': uid,
            'source': source or 'system',
            'execution_path': execution_path or False,
            'correlation_id': self.acc.correlation_id,
            'result': 'success',
            **_meta_values(self.meta),
        }

    def user_group_ids(self, uid):
        if uid not in self._user_groups:
            self.cr.execute("SELECT gid FROM res_groups_users_rel WHERE uid = %s", [uid])
            self._user_groups[uid] = {r[0] for r in self.cr.fetchall()}
        return self._user_groups[uid]

    def user_company(self, uid):
        if uid not in self._user_company:
            self.cr.execute("SELECT company_id FROM res_users WHERE id = %s", [uid])
            row = self.cr.fetchone()
            self._user_company[uid] = row[0] if row else None
        return self._user_company[uid]

    def hmac_key(self):
        if self._hmac_key is None:
            self._hmac_key = integrity.get_hmac_key(self.env)
        return self._hmac_key

    # -- rules -----------------------------------------------------------------
    def _user_allowed(self, rule, uid):
        if uid in rule['excluded_user_ids']:
            return False
        groups = self.user_group_ids(uid) if (rule['group_ids'] or rule['excluded_group_ids']) else set()
        if groups & rule['excluded_group_ids']:
            return False
        if rule['user_ids'] or rule['group_ids']:
            return uid in rule['user_ids'] or bool(groups & rule['group_ids'])
        return True

    def rule_allows(self, rule, operation_flag, uid, source, company_id):
        if operation_flag not in rule['ops']:
            return False
        if rule['company_ids'] and company_id and company_id not in rule['company_ids']:
            return False
        if rule['sources'] and source not in rule['sources']:
            return False
        return self._user_allowed(rule, uid)

    def _domain_allows(self, rule, operation, capture_, after_match):
        if not rule['domain'] or rule['implicit']:
            return True
        before_match = capture_.domain_before.get(rule['id'], True) if capture_ and capture_.existed else False
        if operation == 'CREATE':
            return after_match
        if operation == 'DELETE':
            return before_match if capture_ and capture_.existed else after_match
        return before_match or after_match

    def resolve_rule(self, plan, state, operation, capture_, domain_after, company_id):
        flag = {'CREATE': 'create', 'UPDATE': 'update', 'DELETE': 'delete'}[operation]
        for rule in plan['rules']:
            if not self.rule_allows(rule, flag, state.uid, state.source, company_id):
                continue
            after_match = state.id in domain_after.get(rule['id'], ()) if rule['domain'] else True
            if self._domain_allows(rule, operation, capture_, after_match):
                return rule
        return None

    # -- record drafts ---------------------------------------------------------
    def _build_record_drafts(self, states):
        by_model = defaultdict(list)
        for state in states.values():
            by_model[state.model].append(state)
        drafts = []
        for model, model_states in by_model.items():
            plan = get_plan(self.env, model)
            if plan:
                drafts.extend(self._drafts_for_model(plan, model_states))
        return drafts

    def _drafts_for_model(self, plan, model_states):
        ids = [s.id for s in model_states]
        after_rows = capture.fetch_rows(self.cr, plan, ids, self.settings['max_value_chars'])
        existing = list(after_rows)
        after_m2m = {spec[0]: capture.fetch_m2m(self.cr, spec, existing) for spec in plan['m2m']} if existing else {}
        after_o2m = {spec[0]: capture.fetch_o2m(self.cr, spec, existing) for spec in plan['o2m']} if existing else {}
        domain_after = {
            rule['id']: capture.match_domain(self.env, plan['model'], rule['domain'], existing)
            for rule in plan['rules'] if rule['domain'] and existing
        }
        drafts = []
        for state in model_states:
            draft = self._draft_for_state(plan, state, after_rows, after_m2m, after_o2m, domain_after)
            if draft is not None:
                drafts.append(draft)
        return drafts

    @staticmethod
    def classify(state, exists, capture_):
        if state.created:
            return 'CREATE' if exists else None
        if state.deleted:
            return None if exists else 'DELETE'
        if not exists:
            return 'DELETE' if capture_ and capture_.existed else None
        return 'UPDATE'

    def _draft_for_state(self, plan, state, after_rows, after_m2m, after_o2m, domain_after):
        capture_ = self.captures.get((state.model, state.id))
        exists = state.id in after_rows
        operation = self.classify(state, exists, capture_)
        if operation is None:
            return None
        before = {}
        if operation != 'CREATE' and capture_ and capture_.existed:
            before = dict(capture_.row)
        if operation == 'DELETE' and state.snapshot:
            before = dict(state.snapshot)
        after = after_rows.get(state.id, {}) if operation != 'DELETE' else {}
        company_field = plan['company_field']
        company_before = before.get(company_field) if company_field else None
        company_after = after.get(company_field) if company_field else None
        rule = self.resolve_rule(plan, state, operation, capture_, domain_after,
                                 company_after or company_before)
        if rule is None:
            return None
        draft = RecordDraft(state, plan, rule, operation, before, after)
        draft.company_before, draft.company_after = company_before, company_after
        draft.changes = self._compute_changes(draft, capture_, after_m2m, after_o2m)
        if operation == 'UPDATE' and not draft.changes:
            return None
        return draft

    # -- field policy ----------------------------------------------------------
    def field_allowed(self, rule, fname):
        if fname in self.settings['excluded_fields'] and fname not in rule['fields']:
            return False
        mode = rule['field_mode']
        if mode == 'selected':
            return fname in rule['fields']
        return fname not in rule['excluded']

    def origin_of(self, draft, fname):
        if fname in draft.state.fk_fields:
            return 'database_fk'
        if fname in draft.state.direct:
            return 'direct'
        return 'derived'

    def origin_allowed(self, rule, origin, fname, operation):
        if operation != 'UPDATE' or origin != 'derived':
            return True
        policy = rule['derived_policy']
        if policy == 'all':
            return True
        if policy == 'selected':
            return fname in rule['derived_fields']
        return False

    # -- diffs -------------------------------------------------------------------
    def _compute_changes(self, draft, capture_, after_m2m, after_o2m):
        changes = []
        model = self.env[draft.plan['model']]
        for fname, kind in draft.plan['columns']:
            if not self.field_allowed(draft.rule, fname):
                continue
            changes.extend(self._column_changes(draft, model._fields[fname], kind))
        if draft.operation == 'DELETE':
            return changes
        for spec in draft.plan['m2m']:
            fname = spec[0]
            if self.field_allowed(draft.rule, fname):
                old = capture_.m2m.get(fname, set()) if capture_ and draft.operation != 'CREATE' else set()
                new = after_m2m.get(fname, {}).get(draft.state.id, set())
                changes.extend(self._set_changes(draft, model._fields[fname], old, new, 'add', 'remove'))
        for spec in draft.plan['o2m']:
            fname = spec[0]
            if self.field_allowed(draft.rule, fname):
                old = capture_.o2m.get(fname, set()) if capture_ and draft.operation != 'CREATE' else set()
                new = after_o2m.get(fname, {}).get(draft.state.id, set())
                draft.child_links[fname] = [('ids', old | new)]
                changes.extend(self._set_changes(draft, model._fields[fname], old, new,
                                                 'create_child', 'delete_child'))
        return changes

    def _column_changes(self, draft, field, kind):
        """DELETE events carry their evidence in the snapshot, not in lines."""
        if draft.operation == 'DELETE':
            return []
        fname = field.name
        old = draft.before.get(fname) if draft.operation == 'UPDATE' else None
        new = draft.after.get(fname)
        origin = self.origin_of(draft, fname)
        if not self.origin_allowed(draft.rule, origin, fname, draft.operation):
            return []
        if field.translate and (isinstance(old, dict) or isinstance(new, dict)):
            return self._translation_changes(draft, field, old or {}, new or {}, origin)
        if draft.operation == 'CREATE' and new in (None, False, '', {}, []):
            return []
        if draft.operation == 'UPDATE' and values_equal(field.type, old, new):
            return []
        return [{
            'field': field, 'kind': kind, 'origin': origin, 'old': old, 'new': new,
            'change_type': _scalar_change_type(old, new),
        }]

    def _translation_changes(self, draft, field, old, new, origin):
        changes = []
        for lang in sorted(set(old) | set(new)):
            o, n = old.get(lang), new.get(lang)
            if draft.operation == 'CREATE' and not n:
                continue
            if values_equal(field.type, o, n):
                continue
            changes.append({
                'field': field, 'kind': 'text', 'origin': origin, 'old': o, 'new': n,
                'lang': lang, 'change_type': _scalar_change_type(o, n),
            })
        return changes

    def _set_changes(self, draft, field, old, new, add_type, remove_type):
        origin = self.origin_of(draft, field.name)
        if not self.origin_allowed(draft.rule, origin, field.name, draft.operation):
            return []
        changes = []
        added, removed = new - old, old - new
        if added:
            changes.append({'field': field, 'kind': 'set', 'origin': origin, 'old': set(),
                            'new': added, 'change_type': add_type})
        if removed:
            changes.append({'field': field, 'kind': 'set', 'origin': origin, 'old': removed,
                            'new': set(), 'change_type': remove_type})
        return changes

    # -- parent / child links ---------------------------------------------------
    def _link_children(self, drafts):
        index = {(d.state.model, d.state.id): d for d in drafts}
        for draft in drafts:
            for fname, links in list(draft.child_links.items()):
                comodel = draft.plan['o2m_comodel'][fname]
                child_ids = links[0][1] if links else set()
                draft.child_links[fname] = []
                for child_id in sorted(child_ids):
                    child = index.get((comodel, child_id))
                    if child is None:
                        continue
                    child.parent = draft
                    draft.child_links[fname].append(child)
                    if child.operation == 'UPDATE':
                        draft.changes.append({
                            'field': self.env[draft.plan['model']]._fields[fname], 'kind': 'child',
                            'origin': 'derived', 'old': set(), 'new': {child_id},
                            'change_type': 'update_child',
                        })
        for draft in drafts:
            depth, node = 0, draft.parent
            while node is not None and depth < 10:
                depth, node = depth + 1, node.parent
            draft.depth = depth

    # -- names ---------------------------------------------------------------------
    def _make_serializer(self, drafts):
        wanted = defaultdict(set)
        currency_needed = False
        for draft in drafts:
            if draft.operation != 'DELETE':
                wanted[draft.state.model].add(draft.state.id)
            rows = [draft.before, draft.after]
            for change in draft.changes:
                field = change['field']
                if field.type in ('many2one', 'one2many', 'many2many'):
                    for value in (change['old'], change['new']):
                        ids = value if isinstance(value, set) else {value}
                        wanted[field.comodel_name].update(i for i in ids if isinstance(i, int))
                currency_needed = currency_needed or field.type == 'monetary'
            if draft.snapshot_mode == 'full' or draft.operation == 'DELETE':
                self._collect_row_names(draft, rows, wanted)
                currency_needed = True
        names = dict(self.known_names)
        names.update(self._resolve_names(wanted, names))
        currencies = self._currency_codes() if currency_needed else {}
        return ValueSerializer(self.env, self.settings['preview_length'], names, currencies)

    def _collect_row_names(self, draft, rows, wanted):
        model = self.env[draft.plan['model']]
        for fname, _kind in draft.plan['columns']:
            field = model._fields[fname]
            if field.type != 'many2one':
                continue
            for row in rows:
                if row.get(fname):
                    wanted[field.comodel_name].add(row[fname])

    def _resolve_names(self, wanted, known):
        resolved = {}
        lang = self.settings['audit_lang']
        for model, ids in wanted.items():
            if model not in self.env:
                continue
            ids = [i for i in ids if (model, i) not in known]
            if not ids:
                continue
            Model = self.env[model].sudo().with_context(active_test=False, lang=lang, prefetch_fields=False)
            try:
                existing = capture.existing_ids(self.cr, Model._table, ids) if Model._auto else set(ids)
                for record in Model.browse(sorted(existing)):
                    resolved[(model, record.id)] = record.display_name
            except Exception:  # noqa: BLE001 - names are presentation only
                _logger.debug("Audit name resolution failed for %s", model, exc_info=True)
        return resolved

    def _currency_codes(self):
        if 'res.currency' not in self.env:
            return {}
        self.cr.execute("SELECT id, name FROM res_currency")
        return dict(self.cr.fetchall())

    # -- serialization ----------------------------------------------------------------
    def _mask_mode(self, draft, field, kind, row):
        if kind == 'secret' or field.name in draft.plan['secret_fields']:
            return 'secret'
        dynamic = self.env[draft.plan['model']]._audit_dynamic_secret_fields(row or {})
        if field.name in dynamic:
            return 'secret'
        if draft.plan['personal_fields'].get(field.name) == 'digest':
            return 'personal_digest'
        return None

    def _visibility(self, field):
        groups = field.groups or ''
        xmlids = [g.strip() for g in groups.split(',') if g.strip()]
        negated = any(g.startswith('!') for g in xmlids)
        positive = [g for g in xmlids if not g.startswith('!')]
        group_ids = []
        for xmlid in positive:
            if xmlid not in self._group_ids:
                record = self.env.ref(xmlid, raise_if_not_found=False)
                self._group_ids[xmlid] = record.id if record else None
            if self._group_ids[xmlid]:
                group_ids.append(self._group_ids[xmlid])
        restricted = bool(xmlids)
        return restricted, ([] if negated else group_ids)

    def _serialize_value(self, draft, change, serializer, value, row):
        field = change['field']
        if change['kind'] in ('set', 'child'):
            return serializer.serialize_ids(field.comodel_name, value)
        mask = self._mask_mode(draft, field, change['kind'], row)
        json_value, text = serializer.serialize(field, value, row, masked=mask)
        if mask == 'personal_digest' and value not in (None, False):
            json_value['digest'] = integrity.digest(self.hmac_key(), value)
        if mask == 'secret' and is_secret_digest(value):
            json_value.pop('digest', None)
        return json_value, text

    def _line_vals(self, draft, change, serializer, sequence):
        field = change['field']
        old_json, old_text = self._serialize_value(draft, change, serializer, change['old'], draft.before)
        new_json, new_text = self._serialize_value(draft, change, serializer, change['new'], draft.after)
        restricted, group_ids = self._visibility(field)
        mask = self._mask_mode(draft, field, change['kind'], draft.after or draft.before) \
            if change['kind'] not in ('set', 'child') else None
        return {
            'sequence': sequence,
            'field_name': field.name,
            'field_label': field.string or field.name,
            'field_type': field.type,
            'model_name': field.model_name,
            'change_type': change['change_type'],
            'change_origin': change['origin'],
            'lang': change.get('lang') or False,
            'old_value_json': old_json,
            'new_value_json': new_json,
            'old_value_text': old_text or False,
            'new_value_text': new_text or False,
            'masked': mask == 'secret',
            'personal': field.name in draft.plan['personal_fields'],
            'restricted': restricted,
            'required_group_ids': group_ids,
            'related_model': field.comodel_name if field.relational else False,
        }

    def _snapshot(self, draft, row, serializer):
        model = self.env[draft.plan['model']]
        snapshot = {}
        for fname, kind in draft.plan['columns']:
            field = model._fields[fname]
            if field.groups:
                continue  # restricted fields never enter snapshots (side channel)
            mask = self._mask_mode(draft, field, kind, row)
            if mask == 'secret':
                continue
            json_value, _text = serializer.serialize(field, row.get(fname), row, masked=mask)
            snapshot[fname] = json_value
        return snapshot

    def _visible_companies(self, draft):
        if draft.state.model == 'res.company':
            return [draft.state.id]
        return sorted({c for c in (draft.company_before, draft.company_after) if c})

    def _serialize_draft(self, draft, serializer):
        state = draft.state
        event = self._base_event(state.uid, state.source, state.execution_path)
        visible = self._visible_companies(draft)
        lines = [
            self._line_vals(draft, change, serializer, index)
            for index, change in enumerate(draft.changes, start=1)
        ]
        event.update({
            'key': draft.key,
            'operation': draft.operation,
            'model_name': state.model,
            'res_id': state.id,
            'record_display_name': serializer.name_of(state.model, state.id),
            'rule_id': draft.rule['id'],
            'is_sudo': bool(state.su),
            'company_id': draft.company_after or draft.company_before or (visible[0] if visible else False),
            'visible_company_ids': visible,
            'is_shared': not visible,
            'copy_of': state.copy_of or False,
            'change_origin': _event_origin(state),
            'depth': draft.depth,
            'parent_key': draft.parent.key if draft.parent else False,
            'parent_model': draft.parent.state.model if draft.parent else False,
            'parent_res_id': draft.parent.state.id if draft.parent else False,
            'action_keys': list(state.action_keys),
            'action_label': _archive_label(draft),
            'lines': lines,
        })
        if draft.operation == 'DELETE':
            event['delete_snapshot'] = self._snapshot(draft, draft.before, serializer)
        elif draft.snapshot_mode == 'full':
            if draft.operation == 'UPDATE':
                event['before_snapshot'] = self._snapshot(draft, draft.before, serializer)
            event['after_snapshot'] = self._snapshot(draft, draft.after, serializer)
        return event

    # -- semantic actions ------------------------------------------------------
    def _action_rule(self, plan, entry):
        for rule in plan['rules']:
            if not self.rule_allows(rule, 'action', entry['uid'], entry['source'], None):
                continue
            if rule['action_methods'] and entry['method'] not in rule['action_methods']:
                continue
            return rule
        return None

    def _build_action_events(self, actions):
        events = []
        for entry in actions.values():
            plan = get_plan(self.env, entry['model'])
            rule = plan and self._action_rule(plan, entry)
            if not rule:
                continue
            ids = [i for i in entry['ids'] if isinstance(i, int)]
            event = self._base_event(entry['uid'], entry['source'], entry['execution_path'])
            company = self.user_company(entry['uid'])
            event.update({
                'key': entry['key'],
                'operation': 'ACTION',
                'model_name': entry['model'],
                'res_id': ids[0] if len(ids) == 1 else False,
                'record_count': len(ids),
                'res_ids_json': ids[:READ_CAP_IDS],
                'action_method': entry['method'],
                'action_label': entry['label'],
                'rule_id': rule['id'],
                'is_sudo': bool(entry['su']),
                'company_id': company or False,
                'visible_company_ids': [company] if company else [],
                'is_shared': not company,
                'record_display_name': entry.get('display_name') or False,
                'lines': list(entry.get('lines') or []),
            })
            events.append(event)
        return events

    @staticmethod
    def _attach_actions(record_events, action_events):
        known = {e['key'] for e in action_events}
        for event in record_events:
            keys = [k for k in event.pop('action_keys', []) if k in known]
            event['parent_action_key'] = keys[0] if keys else False

    # -- access events (read / export / report) -----------------------------------
    def _build_access_events(self, access):
        grouped = {}
        for entry in access:
            gkey = (entry['type'], entry['model'], entry.get('report') or '', entry['uid'])
            agg = grouped.setdefault(gkey, {**entry, 'ids': [], 'count': 0, 'fields': set()})
            agg['count'] += entry.get('count', 0)
            agg['ids'].extend(entry.get('ids') or [])
            agg['fields'].update(entry.get('fields') or ())
        events = []
        for (etype, model, _report, uid), agg in grouped.items():
            rule_id = self._access_rule(etype, model, agg)
            if rule_id is False:
                continue
            events.append(self._access_event(etype, model, uid, agg, rule_id))
        return events

    def _access_rule(self, etype, model, agg):
        """Rule id, None when logged by global policy, False when not logged."""
        plan = get_plan(self.env, model)
        flag = {'read': 'read', 'export': 'export', 'report': 'report'}[etype]
        if plan:
            for rule in plan['rules']:
                if self.rule_allows(rule, flag, agg['uid'], agg['source'], None):
                    return rule['id']
        if not self.Rule._is_model_eligible(model):
            return False
        if etype == 'export' and self.settings['audit_all_exports']:
            return None
        if etype == 'read' and agg.get('api') and agg['count'] >= self.settings['bulk_read_threshold']:
            return None
        return False

    def _access_event(self, etype, model, uid, agg, rule_id):
        event = self._base_event(uid, agg['source'], agg['execution_path'])
        company = self.user_company(uid)
        ids = sorted({i for i in agg['ids'] if isinstance(i, int)})
        operation = {'read': 'READ', 'export': 'EXPORT', 'report': 'REPORT'}[etype]
        event.update({
            'operation': operation,
            'model_name': model,
            'res_id': ids[0] if len(ids) == 1 else False,
            'record_count': agg['count'] or len(ids),
            'res_ids_json': ids[:READ_CAP_IDS],
            'fields_json': sorted(agg['fields']),
            'action_method': agg.get('method') or False,
            'action_label': agg.get('report') or False,
            'is_bulk': bool(agg.get('api') and agg['count'] >= self.settings['bulk_read_threshold']),
            'rule_id': rule_id or False,
            'is_sudo': bool(agg['su']),
            'company_id': company or False,
            'visible_company_ids': [company] if company else [],
            'is_shared': not company,
            'lines': [],
        })
        return event

    # -- imports & bulk batches ----------------------------------------------------
    def _build_import_events(self, imports):
        events = []
        for key, entry in imports.items():
            event = self._base_event(entry['uid'], 'import', entry.get('execution_path'))
            company = self.user_company(entry['uid'])
            event.update({
                'operation': 'IMPORT',
                'model_name': entry['model'],
                'res_id': False,
                'record_count': entry.get('count', 0),
                'fields_json': entry.get('fields') or [],
                'batch_key': f'import:{key}',
                'action_label': entry.get('file_name') or False,
                'company_id': company or False,
                'visible_company_ids': [company] if company else [],
                'is_shared': not company,
                'lines': [],
            })
            events.append(event)
        return events

    def _assign_batches(self, record_events, drafts, imports):
        batches = {}
        for key, entry in imports.items():
            batches[f'import:{key}'] = {
                'key': f'import:{key}', 'batch_type': 'import', 'model_name': entry['model'],
                'user_id': entry['uid'], 'name': entry.get('file_name') or entry['model'],
                'failed_count': entry.get('failed', 0), 'correlation_id': self.acc.correlation_id,
            }
        per_operation = defaultdict(list)
        for event, draft in zip(record_events, drafts):
            if draft.state.import_key and f'import:{draft.state.import_key}' in batches:
                event['batch_key'] = f'import:{draft.state.import_key}'
                continue
            if draft.state.op_ids:
                per_operation[draft.state.op_ids[0]].append(event)
        threshold = self.settings['bulk_batch_threshold']
        for (op_id, kind), events in per_operation.items():
            if len(events) < threshold:
                continue
            key = f'bulk:{self.acc.correlation_id}:{op_id}'
            batches[key] = {
                'key': key, 'batch_type': f'bulk_{_bulk_kind(kind)}',
                'model_name': events[0]['model_name'], 'user_id': events[0]['user_id'],
                'name': f"Bulk {_bulk_kind(kind)} on {events[0]['model_name']}",
                'correlation_id': self.acc.correlation_id,
            }
            for event in events:
                event['batch_key'] = key
        return list(batches.values())


# ===========================================================================
# Small pure helpers
# ===========================================================================
def _scalar_change_type(old, new):
    if old in (None, False, '') and new not in (None, False, ''):
        return 'set'
    if new in (None, False, '') and old not in (None, False, ''):
        return 'clear'
    return 'change'


def _event_origin(state):
    if state.deleted == 'fk_cascade' or (state.fk_fields and not state.direct):
        return 'database_fk'
    if state.direct or state.created or state.deleted:
        return 'direct'
    return 'derived'


def _bulk_kind(kind):
    return {'create': 'create', 'write': 'write', 'unlink': 'unlink'}.get(kind, 'write')


def _archive_label(draft):
    if draft.operation != 'UPDATE':
        return False
    names = {c['field'].name for c in draft.changes}
    if names == {'active'} or names == {'active', 'write_date'}:
        return 'Unarchive' if draft.after.get('active') else 'Archive'
    return False
