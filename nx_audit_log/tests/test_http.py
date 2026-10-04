# -*- coding: utf-8 -*-
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'nx_audit')
class TestBoundaries(HttpCase):
    """Request-boundary behaviour through the real HTTP stack."""

    def _logs(self, **domain):
        self.env.invalidate_all()
        return self.env['audit.log'].search([(k, '=', v) for k, v in domain.items()], order='id')

    def test_call_button_semantic_action_is_linked(self):
        partner = self.env['res.partner'].create({'name': 'Button target'})
        self.authenticate('admin', 'admin')
        self.make_jsonrpc_request('/web/dataset/call_button', {
            'model': 'res.partner', 'method': 'action_archive', 'args': [[partner.id]], 'kwargs': {},
        })
        action = self._logs(operation='ACTION', model_name='res.partner', res_id=partner.id)
        self.assertEqual(action.action_label, 'Archive')
        self.assertEqual(action.source, 'web_ui')
        self.assertTrue(action.ip_address)
        change = action.action_change_ids
        self.assertEqual(change.operation, 'UPDATE')
        self.assertIn('active', change.line_ids.mapped('field_name'))

    def test_client_visible_failure_is_recorded_once(self):
        self.authenticate('admin', 'admin')
        admin_partner = self.env.ref('base.user_admin').partner_id
        response = self.url_open('/web/dataset/call_kw', data=__import__('json').dumps({
            'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
                'model': 'res.partner', 'method': 'unlink', 'args': [[admin_partner.id]], 'kwargs': {}}}),
            headers={'Content-Type': 'application/json'})
        self.assertIn('error', response.json())
        failures = self._logs(operation='FAILED_ATTEMPT', model_name='res.partner', res_id=admin_partner.id)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures.action_method, 'unlink')
        self.assertFalse(self._logs(operation='DELETE', model_name='res.partner', res_id=admin_partner.id))

    def test_jsonrpc_source_cannot_be_spoofed(self):
        uid = self.env.ref('base.user_admin').id
        result = self.make_jsonrpc_request('/jsonrpc', {
            'service': 'object', 'method': 'execute_kw',
            'args': [self.env.cr.dbname, uid, 'admin', 'res.partner', 'create',
                     [{'name': 'From API'}], {'context': {'source': 'mobile', 'audit_bypass': True}}],
        })
        partner_id = result[0] if isinstance(result, list) else result
        log = self._logs(operation='CREATE', model_name='res.partner', res_id=partner_id)
        self.assertEqual(log.source, 'json_rpc')

    def test_backend_assets_compile(self):
        """JS modules transpile inside the real backend bundle; SCSS compiles."""
        import sass
        from odoo.tools.misc import file_path
        bundle = self.env['ir.qweb']._get_asset_bundle('web.assets_backend', css=False, js=True)
        js = bundle.js().raw.decode()
        self.assertIn('nx_audit_log.dashboard', js)
        self.assertIn('nx_audit_log.timeline', js)
        for scss in ('dashboard/audit_dashboard.scss', 'timeline/audit_timeline.scss'):
            with open(file_path(f'nx_audit_log/static/src/{scss}'), encoding='utf-8') as handle:
                self.assertTrue(sass.compile(string=handle.read()))
