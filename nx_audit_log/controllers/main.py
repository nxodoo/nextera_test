# -*- coding: utf-8 -*-
import logging
import xmlrpc.client

from odoo import http
from odoo.addons.base.controllers.rpc import RPC
from odoo.addons.web.controllers.dataset import DataSet
from odoo.addons.web.controllers.session import Session
from odoo.http import request

from ..models.res_users import is_business_failure, record_boundary_failure, write_in_side_cursor
from ..services import context as audit_context
from ..services import observer
from ..services.api import semantic_action
from ..services.rpc_patch import READ_METHODS, register_api_read

_logger = logging.getLogger(__name__)
WRITE_METHODS = {'create', 'write', 'unlink'}


def _target_ids(args):
    if not args:
        return []
    ids = args[0]
    if isinstance(ids, int):
        return [ids]
    if isinstance(ids, (list, tuple)):
        return [i for i in ids if isinstance(i, int)]
    return []


def _remember_call(model, method, args):
    """Boundary metadata used by ir.http._handle_error if the call fails."""
    request._nx_audit_call = {
        'model': model, 'method': method, 'ids': _target_ids(args) if method != 'create' else [],
        'uid': request.session.uid,
    }


class AuditDataSet(DataSet):

    @http.route()
    def call_kw(self, model, method, args, kwargs, path=None):
        if method in WRITE_METHODS:
            _remember_call(model, method, args)
        result = super().call_kw(model, method, args, kwargs, path=path)
        if method in READ_METHODS and method != 'export_data':
            self._register_ui_read(model, method, args, kwargs, result)
        return result

    @http.route()
    def call_button(self, model, method, args, kwargs, path=None):
        _remember_call(model, method, args)
        records = request.env[model].browse(_target_ids(args))
        with semantic_action(records, method):
            return super().call_button(model, method, args, kwargs, path=path)

    @staticmethod
    def _register_ui_read(model, method, args, kwargs, result):
        """UI reads are only logged when a rule explicitly enables read auditing."""
        try:
            plan = observer.get_plan(request.env, model)
            if plan and 'read' in plan['ops']:
                register_api_read(request.env, model, method, args, kwargs, result, api=False)
        except Exception:  # noqa: BLE001
            _logger.debug("nx_audit_log: UI read registration failed", exc_info=True)


class AuditRPC(RPC):
    """XML-RPC / JSON-RPC: the request object is "borrowed" during dispatch,
    so the trusted transport metadata is carried in a context variable."""

    @http.route()
    def xmlrpc_1(self, service):
        return self._nx_audited(service, 'xml_rpc', lambda: super(AuditRPC, self).xmlrpc_1(service))

    @http.route()
    def xmlrpc_2(self, service):
        return self._nx_audited(service, 'xml_rpc', lambda: super(AuditRPC, self).xmlrpc_2(service))

    @http.route()
    def jsonrpc(self, service, method, args):
        return self._nx_audited(service, 'json_rpc',
                                lambda: super(AuditRPC, self).jsonrpc(service, method, args),
                                rpc_method=method, rpc_args=args)

    def _nx_audited(self, service, transport, call, rpc_method=None, rpc_args=None):
        meta = audit_context.build_rpc_meta(request.httprequest, transport)
        with audit_context.rpc_scope(meta):
            try:
                return call()
            except Exception as exc:
                if service == 'object' and is_business_failure(exc):
                    self._nx_record_rpc_failure(transport, rpc_method, rpc_args, exc, meta)
                raise

    @staticmethod
    def _nx_record_rpc_failure(transport, rpc_method, rpc_args, exc, meta):
        try:
            if transport == 'xml_rpc':
                rpc_args, rpc_method = xmlrpc.client.loads(request.httprequest.get_data())
            params = list(rpc_args or [])
            if rpc_method not in ('execute', 'execute_kw') or len(params) < 5:
                return
            db, uid, _pwd, model, method = params[:5]
            call_args = params[5] if len(params) > 5 else []
            from odoo.modules.registry import Registry
            record_boundary_failure(Registry(db), {
                'model': model, 'method': method, 'uid': int(uid),
                'ids': _target_ids(call_args) if method != 'create' else [],
            }, exc, meta)
        except Exception:  # noqa: BLE001
            _logger.debug("nx_audit_log: RPC failure capture failed", exc_info=True)


class AuditSession(Session):

    @http.route()
    def logout(self, redirect='/odoo'):
        self._nx_record_logout()
        return super().logout(redirect=redirect)

    @http.route()
    def destroy(self):
        self._nx_record_logout()
        return super().destroy()

    @staticmethod
    def _nx_record_logout():
        uid = request.session.uid
        if not uid or not request.db:
            return
        meta = audit_context.request_meta()
        login = request.session.login
        write_in_side_cursor(request.registry, lambda env: env['audit.log']._record_auth_event(
            'LOGOUT', uid=uid, login=login, meta=meta))
