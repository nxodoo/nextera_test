# -*- coding: utf-8 -*-
"""Field-type aware serialization of raw database values.

Two representations are produced for every value:

* structured JSON (source of truth, hashed for integrity)
* a bounded human-readable preview (UI / text search only)
"""
import datetime
import json
import re

from .capture import SECRET_MARK, TRUNC_MARK

MASK_SECRET = '[changed - value not stored]'
MASK_PERSONAL = '[personal data - digest only]'
REDACTED = '[redacted]'
_TAG_RE = re.compile(r'<[^>]+>')
_SPACE_RE = re.compile(r'\s+')
FLOAT_TOLERANCE = 1e-9


def json_safe(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return value


def canonical_json(value):
    return json.dumps(json_safe(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def decode_truncated(raw):
    """'\\x1fNXTRUNC:<len>:<md5>:<head>' -> dict, otherwise None."""
    if isinstance(raw, str) and raw.startswith(TRUNC_MARK):
        length, digest, head = raw[len(TRUNC_MARK):].split(':', 2)
        return {'truncated': True, 'length': int(length), 'md5': digest, 'head': head}
    return None


def is_secret_digest(raw):
    return isinstance(raw, str) and raw.startswith(SECRET_MARK)


def values_equal(field_type, old, new):
    if old is None and new is None:
        return True
    if field_type in ('float', 'monetary'):
        try:
            a, b = float(old or 0.0), float(new or 0.0)
        except (TypeError, ValueError):
            return old == new
        return abs(a - b) <= FLOAT_TOLERANCE * max(1.0, abs(a), abs(b))
    if field_type in ('char', 'text', 'html', 'selection'):
        return (old or False) == (new or False)
    if field_type == 'boolean':
        return bool(old) == bool(new)
    return old == new


def _clip(text, limit):
    text = '' if text is None else str(text)
    return text if len(text) <= limit else text[:max(limit - 1, 1)] + '\u2026'


def html_to_text(value):
    return _SPACE_RE.sub(' ', _TAG_RE.sub(' ', value or '')).strip()


class ValueSerializer:
    """Serialize raw column values of one model field."""

    def __init__(self, env, preview_length, names, currencies):
        self.env = env
        self.preview_length = preview_length
        self.names = names              # {(model, id): display name}
        self.currencies = currencies    # {currency_id: code}
        self._selection_cache = {}

    # -- helpers -----------------------------------------------------------
    def _selection_label(self, field, key):
        if key in (None, False):
            return ''
        cache_key = (field.model_name, field.name)
        if cache_key not in self._selection_cache:
            try:
                labels = dict(field._description_selection(self.env))
            except Exception:  # noqa: BLE001 - dynamic selections may need context
                labels = {}
            self._selection_cache[cache_key] = labels
        return self._selection_cache[cache_key].get(key, str(key))

    def name_of(self, model, record_id):
        if not record_id:
            return ''
        return self.names.get((model, record_id)) or f'{model},{record_id} (deleted)'

    # -- public API --------------------------------------------------------
    def serialize(self, field, raw, row=None, masked=None):
        """Return (json_value, preview_text) for one raw value."""
        if masked == 'secret':
            return ({'masked': True}, MASK_SECRET if raw not in (None, False) else '')
        if masked == 'personal_digest':
            return ({'personal_digest': True}, MASK_PERSONAL if raw not in (None, False) else '')
        ftype = field.type
        handler = getattr(self, f'_ser_{ftype}', self._ser_default)
        return handler(field, raw, row or {})

    def serialize_ids(self, comodel, ids):
        ids = sorted(i for i in ids if i)
        names = [self.name_of(comodel, i) for i in ids]
        return ({'ids': ids, 'names': names, 'model': comodel},
                _clip(', '.join(names), self.preview_length))

    # -- per type ------------------------------------------------------------
    def _ser_default(self, field, raw, row):
        truncated = decode_truncated(raw)
        if truncated:
            return ({'v': None, **truncated}, _clip(truncated['head'], self.preview_length))
        value = json_safe(raw)
        return ({'v': value}, _clip('' if raw in (None, False) else value, self.preview_length))

    def _ser_html(self, field, raw, row):
        truncated = decode_truncated(raw)
        if truncated:
            return ({'v': None, **truncated},
                    _clip(html_to_text(truncated['head']), self.preview_length))
        return ({'v': raw}, _clip(html_to_text(raw), self.preview_length))

    def _ser_boolean(self, field, raw, row):
        return ({'v': bool(raw)}, 'Yes' if raw else 'No')

    def _ser_selection(self, field, raw, row):
        label = self._selection_label(field, raw)
        return ({'v': raw, 'label': label}, label)

    def _ser_monetary(self, field, raw, row):
        currency_field = field.get_currency_field(self.env[field.model_name]) \
            if hasattr(field, 'get_currency_field') else getattr(field, 'currency_field', None)
        currency_id = row.get(currency_field) if currency_field else None
        code = self.currencies.get(currency_id) if currency_id else None
        text = '' if raw is None else f'{raw:,.2f}'
        return ({'v': raw, 'currency': code}, f'{text} {code}'.strip() if code else text)

    def _ser_float(self, field, raw, row):
        return ({'v': raw}, '' if raw is None else repr(raw))

    def _ser_date(self, field, raw, row):
        return ({'v': json_safe(raw)}, '' if not raw else raw.isoformat())

    def _ser_datetime(self, field, raw, row):
        return ({'v': json_safe(raw), 'tz': 'UTC'},
                '' if not raw else raw.strftime('%Y-%m-%d %H:%M:%S UTC'))

    def _ser_many2one(self, field, raw, row):
        if not raw:
            return ({'id': None, 'model': field.comodel_name}, '')
        name = self.name_of(field.comodel_name, raw)
        return ({'id': raw, 'name': name, 'model': field.comodel_name}, _clip(name, self.preview_length))

    def _ser_many2one_reference(self, field, raw, row):
        model = row.get(field.model_field) if getattr(field, 'model_field', None) else None
        if not raw:
            return ({'id': None, 'model': model}, '')
        name = self.name_of(model, raw) if model else str(raw)
        return ({'id': raw, 'model': model, 'name': name}, _clip(name, self.preview_length))

    def _ser_reference(self, field, raw, row):
        if not raw:
            return ({'v': None}, '')
        model, _sep, rid = raw.partition(',')
        rid = int(rid) if rid.isdigit() else None
        name = self.name_of(model, rid) if rid else raw
        return ({'v': raw, 'name': name}, _clip(name, self.preview_length))

    def _ser_binary(self, field, raw, row):
        if not raw:
            return ({'v': None}, '')
        _md5, digest, size = raw.split(':')
        return ({'md5': digest, 'size': int(size)}, f'binary ({int(size):,} bytes)')

    def _ser_json(self, field, raw, row):
        return ({'v': json_safe(raw)}, _clip(canonical_json(raw) if raw else '', self.preview_length))

    _ser_properties = _ser_json
    _ser_properties_definition = _ser_json
