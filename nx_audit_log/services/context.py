# -*- coding: utf-8 -*-
"""Server-side execution context for the audit engine.

Everything here lives in Python ``contextvars``. Nothing can be set from an
Odoo ``context`` dictionary, so JSON-RPC / XML-RPC clients cannot disable
auditing or spoof the execution source.
"""
import contextlib
import hashlib
import inspect
import logging
import uuid
from contextvars import ContextVar

_logger = logging.getLogger(__name__)

# Explicit, code-only audit bypass (never reachable from a client context).
_BYPASS = ContextVar('nx_audit_bypass', default=None)
# Set while the audit engine itself runs: prevents self-auditing recursion.
_GUARD = ContextVar('nx_audit_guard', default=False)
# Name of the privileged internal operation allowed to touch evidence rows.
_PRIVILEGED = ContextVar('nx_audit_privileged', default=None)
# Stack of execution frames: tuples (kind, ref_id, label).
_EXEC = ContextVar('nx_audit_exec', default=())
# Transport metadata for RPC calls (request object is "borrowed" during RPC).
_RPC = ContextVar('nx_audit_rpc', default=None)
# Current semantic action: dict(key, model, method, label).
_ACTION = ContextVar('nx_audit_action', default=None)
# Allows capture while the registry is still loading (module post_init hooks).
_INSTALL_CAPTURE = ContextVar('nx_audit_install_capture', default=False)
# Source of copy() calls: "model:ids".
_COPY = ContextVar('nx_audit_copy', default=None)

EXECUTION_PRIORITY = ('import', 'automated_action', 'cron', 'server_action')

SOURCE_SELECTION = [
    ('web_ui', 'Web UI'),
    ('json_rpc', 'JSON-RPC'),
    ('xml_rpc', 'XML-RPC'),
    ('external_api', 'External API / Controller'),
    ('cron', 'Scheduled Action (Cron)'),
    ('import', 'Import'),
    ('automated_action', 'Automated Action'),
    ('server_action', 'Server Action'),
    ('system', 'System / Internal'),
]

WEB_UI_PREFIXES = (
    '/web', '/odoo', '/mail', '/bus', '/html_editor', '/report', '/discuss',
)
MOBILE_UA_MARKERS = ('odoomobile', 'odoo mobile', 'odooandroid', 'odooios')


# ---------------------------------------------------------------------------
# Bypass / guard / privileged
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def audit_bypass(reason):
    """Disable change capture for the enclosed Python block.

    Only callable from server code. Every use is logged with its caller so
    bypass usage stays diagnosable.
    """
    if not reason:
        raise ValueError("audit_bypass() requires an explicit reason")
    caller = inspect.stack()[2]
    _logger.info("Audit bypass entered: %s (%s:%s)", reason, caller.filename, caller.lineno)
    token = _BYPASS.set(reason)
    try:
        yield
    finally:
        _BYPASS.reset(token)


@contextlib.contextmanager
def capture_during_install():
    """Audit even though the registry is not marked ready.

    Only for post_init hooks of modules depending on nx_audit_log (its tables
    exist then). Evidence must be finalized inside the block (flush_audit).
    """
    token = _INSTALL_CAPTURE.set(True)
    try:
        yield
    finally:
        _INSTALL_CAPTURE.reset(token)


def install_capture_enabled():
    return _INSTALL_CAPTURE.get()


def is_bypassed():
    return _BYPASS.get() is not None or _GUARD.get()


@contextlib.contextmanager
def guarded():
    """Mark code executed by the audit engine itself."""
    token = _GUARD.set(True)
    try:
        yield
    finally:
        _GUARD.reset(token)


def is_guarded():
    return _GUARD.get()


@contextlib.contextmanager
def privileged(operation):
    """Allow a named internal operation to modify evidence rows."""
    token = _PRIVILEGED.set(operation)
    try:
        yield
    finally:
        _PRIVILEGED.reset(token)


def privileged_operation():
    return _PRIVILEGED.get()


# ---------------------------------------------------------------------------
# Execution frames (cron, server action, import, automated action)
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def execution(kind, ref_id=None, label=None):
    token = _EXEC.set(_EXEC.get() + ((kind, ref_id, label),))
    try:
        yield
    finally:
        _EXEC.reset(token)


def execution_stack():
    return _EXEC.get()


def execution_path():
    return ' > '.join(
        f"{kind}:{ref}" if ref else kind for kind, ref, _label in _EXEC.get()
    ) or False


def current_frame(kind):
    for frame in reversed(_EXEC.get()):
        if frame[0] == kind:
            return frame
    return None


# ---------------------------------------------------------------------------
# Semantic actions and copy tracking
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def action_scope(action):
    token = _ACTION.set(action)
    try:
        yield
    finally:
        _ACTION.reset(token)


def current_action():
    return _ACTION.get()


@contextlib.contextmanager
def copy_scope(records):
    token = _COPY.set(f"{records._name}:{','.join(map(str, records.ids))}")
    try:
        yield
    finally:
        _COPY.reset(token)


def current_copy_source():
    return _COPY.get()


# ---------------------------------------------------------------------------
# RPC transport metadata
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def rpc_scope(meta):
    token = _RPC.set(meta)
    try:
        yield
    finally:
        _RPC.reset(token)


def rpc_meta():
    return _RPC.get()


# ---------------------------------------------------------------------------
# Request metadata (trusted, server-derived)
# ---------------------------------------------------------------------------
def _http_request():
    from odoo.http import request
    try:
        return request if request and getattr(request, 'httprequest', None) else None
    except RuntimeError:
        return None


def _hash_session(sid):
    if not sid:
        return False
    return hashlib.sha256(sid.encode()).hexdigest()[:24]


def _claimed_client(user_agent):
    ua = (user_agent or '').lower()
    if any(marker in ua for marker in MOBILE_UA_MARKERS):
        return 'mobile_app'
    if 'mobile' in ua or 'android' in ua or 'iphone' in ua:
        return 'mobile_browser'
    return False


def _transport_from_path(path):
    if path.startswith('/jsonrpc'):
        return 'json_rpc'
    if path.startswith('/xmlrpc'):
        return 'xml_rpc'
    if path.startswith(WEB_UI_PREFIXES):
        return 'web_ui'
    return 'external_api'


def correlation_id():
    """One id per HTTP request / RPC call; callers fall back to the cursor id."""
    meta = _RPC.get()
    if meta:
        return meta['correlation_id']
    req = _http_request()
    if req is not None:
        cid = getattr(req, '_nx_audit_cid', None)
        if not cid:
            cid = uuid.uuid4().hex
            req._nx_audit_cid = cid
        return cid
    return None


def request_meta():
    """Trusted request metadata; never derived from client-provided context."""
    meta = _RPC.get()
    if meta:
        return dict(meta)
    req = _http_request()
    if req is None:
        return {'transport': 'system'}
    httpreq = req.httprequest
    user_agent = (httpreq.user_agent.string or '')[:255] if httpreq.user_agent else ''
    session = getattr(req, 'session', None)
    return {
        'transport': _transport_from_path(httpreq.path or ''),
        'path': (httpreq.path or '')[:255],
        'http_method': httpreq.method,
        'ip_address': httpreq.remote_addr,
        'user_agent': user_agent,
        'claimed_client': _claimed_client(user_agent),
        'session_hash': _hash_session(getattr(session, 'sid', None)),
        'initiating_uid': getattr(session, 'uid', None) or False,
        'correlation_id': correlation_id(),
    }


def build_rpc_meta(httprequest, transport):
    user_agent = (httprequest.user_agent.string or '')[:255] if httprequest.user_agent else ''
    return {
        'transport': transport,
        'path': (httprequest.path or '')[:255],
        'http_method': httprequest.method,
        'ip_address': httprequest.remote_addr,
        'user_agent': user_agent,
        'claimed_client': _claimed_client(user_agent),
        'session_hash': False,
        'initiating_uid': False,
        'correlation_id': uuid.uuid4().hex,
    }


def resolve_source(meta=None):
    """Execution frames win over transport: a cron job is a cron job even
    if it was manually triggered from the web client."""
    kinds = {frame[0] for frame in _EXEC.get()}
    for kind in EXECUTION_PRIORITY:
        if kind in kinds:
            return kind
    meta = meta or request_meta()
    return meta.get('transport') or 'system'
