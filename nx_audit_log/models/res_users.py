# -*- coding: utf-8 -*-
"""Authentication events.

Odoo authenticates in its own short-lived cursors and an AccessDenied rolls
them back, so authentication evidence is written in a separate cursor that
commits independently. Failures are aggregated (see audit.log
``_record_failed_login``) so brute force cannot flood the audit tables.
"""
import functools
import logging

from odoo import SUPERUSER_ID, api, models
from odoo.exceptions import AccessDenied

from ..services import context as audit_context
from ..services import observer
from ..services.serializer import MASK_SECRET

_logger = logging.getLogger(__name__)


def write_in_side_cursor(registry, callback):
    """Run ``callback(env)`` in an independent, committed transaction."""
    if 'audit.log' not in registry or not registry.ready:
        return
    try:
        with registry.cursor() as cr, audit_context.guarded():
            callback(api.Environment(cr, SUPERUSER_ID, {}))
    except Exception:  # noqa: BLE001 - authentication must never fail because of auditing
        _logger.warning("nx_audit_log: could not record authentication event", exc_info=True)


class ResUsers(models.Model):
    _inherit = 'res.users'

    @classmethod
    def authenticate(cls, db, credential, user_agent_env):
        meta = audit_context.request_meta()
        try:
            auth_info = super().authenticate(db, credential, user_agent_env)
        except AccessDenied:
            login = credential.get('login') if isinstance(credential, dict) else None
            ctype = credential.get('type') if isinstance(credential, dict) else 'unknown'
            write_in_side_cursor(cls.pool, lambda env: env['audit.log']._record_failed_login(
                login, meta=meta, credential_type=ctype))
            raise
        write_in_side_cursor(cls.pool, lambda env: env['audit.log']._record_auth_event(
            'LOGIN', uid=auth_info.get('uid'), login=credential.get('login'), meta=meta,
            extra={'action_method': auth_info.get('auth_method'),
                   'action_label': f"mfa: {auth_info.get('mfa')}" if auth_info.get('mfa') else False}))
        return auth_info

    @classmethod
    def check(cls, db, uid, passwd):
        try:
            return super().check(db, uid, passwd)
        except AccessDenied:
            meta = audit_context.request_meta()
            write_in_side_cursor(cls.pool, lambda env: env['audit.log']._record_failed_login(
                env['res.users'].sudo().browse(uid).exists().login or f'uid:{uid}',
                meta=meta, credential_type='rpc_password_or_apikey'))
            raise

    def _set_encrypted_password(self, uid, pw):
        """Odoo stores passwords with raw SQL: record the fact, never the value."""
        result = super()._set_encrypted_password(uid, pw)
        user = self.browse(uid)
        if not audit_context.is_bypassed():
            observer.record_event(
                self.env, 'action', key=f'password:{uid}:{id(pw)}', model='res.users', ids=[uid],
                method='_set_password', label='Password changed',
                display_name=user.sudo().login, lines=[{
                    'field_name': 'password', 'field_label': 'Password', 'field_type': 'char',
                    'model_name': 'res.users', 'change_type': 'change', 'change_origin': 'direct',
                    'old_value_json': {'masked': True}, 'new_value_json': {'masked': True},
                    'old_value_text': MASK_SECRET, 'new_value_text': MASK_SECRET, 'masked': True,
                }])
        return result

    def _register_hook(self):
        super()._register_hook()
        self._nx_audit_wrap_totp()

    def _nx_audit_wrap_totp(self):
        """Wrap auth_totp's second-factor check when that module is installed.

        Done on the final registry class so it works regardless of module
        load order (no hard dependency on auth_totp).
        """
        cls = type(self)
        original = getattr(cls, '_totp_check', None)
        if original is None or getattr(original, '_nx_audit_wrapped', False):
            return

        @functools.wraps(original)
        def _totp_check(user, code):
            meta = audit_context.request_meta()
            try:
                result = original(user, code)
            except AccessDenied:
                write_in_side_cursor(user.pool, lambda env: env['audit.log']._record_failed_login(
                    user.login, meta=meta, credential_type='totp'))
                raise
            write_in_side_cursor(user.pool, lambda env: env['audit.log']._record_auth_event(
                'MFA', uid=user.id, login=user.login, meta=meta,
                extra={'action_method': 'totp', 'action_label': 'Second factor verified'}))
            return result

        _totp_check._nx_audit_wrapped = True
        cls._totp_check = _totp_check


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _handle_error(cls, exception):
        """Client-visible failures, recorded after the business transaction failed."""
        try:
            cls._nx_audit_record_failure(exception)
        except Exception:  # noqa: BLE001
            _logger.debug("nx_audit_log: failure capture failed", exc_info=True)
        return super()._handle_error(exception)

    @classmethod
    def _nx_audit_record_failure(cls, exception):
        from odoo.http import request
        call = getattr(request, '_nx_audit_call', None) if request else None
        if not call or not is_business_failure(exception):
            return
        registry, meta = request.registry, audit_context.request_meta()
        cr = request.env.cr if request.env else None
        if cr is None or cr.closed:
            record_boundary_failure(registry, call, exception, meta)
            return
        # Record only once the failed business transaction is really rolled
        # back (the request cursor is closed right after this handler).
        cr.postrollback.add(lambda: record_boundary_failure(registry, call, exception, meta))


def is_business_failure(exception):
    from psycopg2 import errors as pg_errors
    from odoo.exceptions import AccessError, MissingError, RedirectWarning, UserError
    business = (UserError, RedirectWarning, AccessError, MissingError, AccessDenied,
                pg_errors.SerializationFailure, pg_errors.LockNotAvailable)
    return isinstance(exception, business)


def record_boundary_failure(registry, call, exception, meta):
    reason = f"{type(exception).__name__}: {exception}"
    write_in_side_cursor(registry, lambda env: env['audit.log']._record_failure(
        call['model'], call['method'], call.get('ids'), call.get('uid'), reason, meta=meta))
