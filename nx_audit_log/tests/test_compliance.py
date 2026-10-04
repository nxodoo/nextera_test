# -*- coding: utf-8 -*-
import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.nx_audit_log.services import context as audit_context
from .test_engine import AuditCase


@tagged('post_install', '-at_install', 'nx_audit')
class TestImmutabilityAndSecurity(AuditCase):

    def _a_log(self):
        partner = self.env['res.partner'].create({'name': 'Evidence'})
        self.flush()
        return self.logs(partner, 'CREATE')

    def test_evidence_is_immutable(self):
        log = self._a_log()
        with self.assertRaises(AccessError):
            log.write({'record_display_name': 'tampered'})
        with self.assertRaises(AccessError):
            log.unlink()
        with self.assertRaises(AccessError):
            log.line_ids.write({'new_value_text': 'tampered'})
        with self.assertRaises(AccessError):
            self.Log.create({'operation': 'CREATE', 'model_name': 'res.partner'})

    def test_audit_user_cannot_see_other_company(self):
        company_b = self.env['res.company'].create({'name': 'Other Co'})
        partner = self.env['res.partner'].create({'name': 'Hidden', 'company_id': company_b.id})
        self.flush()
        auditor = new_test_user(self.env, 'auditor_a', groups='nx_audit_log.group_audit_user',
                                company_id=self.env.company.id)
        visible = self.Log.with_user(auditor).search([('model_name', '=', 'res.partner'),
                                                      ('res_id', '=', partner.id)])
        self.assertFalse(visible)

    def test_restricted_field_lines_are_hidden(self):
        group = self.env['res.groups'].create({'name': 'Payroll secret'})
        log = self._a_log()
        with audit_context.privileged('persist'):
            log.line_ids[:1].sudo().write({'restricted': True, 'required_group_ids': [(6, 0, group.ids)]})
        auditor = new_test_user(self.env, 'auditor_b', groups='nx_audit_log.group_audit_user')
        lines = self.env['audit.log.line'].with_user(auditor).search([('audit_log_id', '=', log.id)])
        self.assertNotIn(log.line_ids[:1], lines)
        auditor.groups_id = [(4, group.id)]
        lines = self.env['audit.log.line'].with_user(auditor).search([('audit_log_id', '=', log.id)])
        self.assertIn(log.line_ids[:1], lines)


@tagged('post_install', '-at_install', 'nx_audit')
class TestIntegrityAndRetention(AuditCase):

    def _sealed_logs(self, count=3):
        partners = self.env['res.partner'].create([{'name': f'Seal {i}'} for i in range(count)])
        self.flush()
        logs = self.Log.search([('model_name', '=', 'res.partner'), ('res_id', 'in', partners.ids)])
        self.env.cr.execute("UPDATE audit_log SET seal_after = now() - interval '1 hour' "
                            "WHERE seal_state = 'unsealed'")
        self.env['audit.log'].invalidate_model()
        self.env['audit.chain']._cron_seal()
        self.env['audit.log'].invalidate_model()
        return logs

    def test_seal_and_verify(self):
        logs = self._sealed_logs()
        self.assertEqual(set(logs.mapped('seal_state')), {'sealed'})
        check = self.env['audit.integrity.check'].create({})._run()
        self.assertEqual(check.state, 'passed', check.violation_ids.mapped('detail'))

    def test_tampering_is_detected(self):
        logs = self._sealed_logs()
        line = logs[0].line_ids[:1]
        self.env.cr.execute("UPDATE audit_log_line SET new_value_json = '{\"v\": \"forged\"}' "
                            "WHERE id = %s", [line.id])
        self.env.cr.execute("UPDATE audit_log SET operation = 'UPDATE' WHERE id = %s", [logs[1].id])
        self.env.invalidate_all()
        check = self.env['audit.integrity.check'].create({})._run()
        self.assertEqual(check.state, 'failed')
        kinds = set(check.violation_ids.mapped('kind'))
        self.assertIn('value_modified', kinds)
        self.assertIn('modified', kinds)

    def test_archive_purge_and_checkpoint_keep_chain_verifiable(self):
        logs = self._sealed_logs(4)
        past = fields.Datetime.now() - timedelta(days=1)
        self.env.cr.execute("UPDATE audit_log SET archive_after = %s, purge_after = NULL, "
                            "prohibit_purge = false WHERE seal_state = 'sealed'", [past])
        self.env.invalidate_all()
        Policy = self.env['audit.retention.policy']
        Policy._cron_retention()
        self.assertFalse(logs.exists())
        archived = self.env['audit.log.archive'].search([('original_id', 'in', logs.ids)])
        self.assertEqual(len(archived), 4)
        check = self.env['audit.integrity.check'].create({})._run()
        self.assertEqual(check.state, 'passed', check.violation_ids.mapped('detail'))
        # purge everything archived, then compaction creates checkpoints
        self.env.cr.execute("UPDATE audit_log_archive SET purge_after = %s", [past])
        self.env.cr.execute("UPDATE audit_log SET purge_after = %s, prohibit_purge = false "
                            "WHERE seal_state = 'sealed'", [past])
        self.env.invalidate_all()
        Policy._cron_retention()
        self.assertTrue(self.env['audit.checkpoint'].search([]))
        check = self.env['audit.integrity.check'].create({})._run()
        self.assertEqual(check.state, 'passed', check.violation_ids.mapped('detail'))

    def test_prohibit_purge_is_respected(self):
        logs = self._sealed_logs(1)
        past = fields.Datetime.now() - timedelta(days=1)
        self.env.cr.execute("UPDATE audit_log SET purge_after = %s, prohibit_purge = true, "
                            "archive_after = NULL WHERE id IN %s", [past, tuple(logs.ids)])
        self.env.invalidate_all()
        self.env['audit.retention.policy']._cron_retention()
        self.assertTrue(logs.exists())


@tagged('post_install', '-at_install', 'nx_audit')
class TestAuthAlertsImport(AuditCase):

    def test_failed_logins_are_aggregated(self):
        meta = {'transport': 'web_ui', 'ip_address': '10.0.0.9'}
        for _i in range(3):
            self.Log._record_failed_login('ghost-login', meta=meta)
        logs = self.Log.search([('operation', '=', 'FAILED_LOGIN'), ('ip_address', '=', '10.0.0.9')])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.attempt_count, 3)
        self.assertTrue(logs.record_display_name.startswith('sha256:'),
                        "unknown logins are stored hashed (could be a mistyped password)")

    def test_group_change_raises_alert(self):
        user = self.env['res.users'].create({'name': 'Escalate', 'login': 'escalate_user'})
        self.flush()
        user.groups_id = [(4, self.env.ref('base.group_system').id)]
        self.flush()
        alert = self.env['audit.alert'].search([('rule_id.name', '=', 'User groups changed')])
        self.assertTrue(alert)
        self.assertEqual(alert[:1].state, 'pending')

    def test_import_dry_run_is_not_an_import(self):
        content = base64.b64decode(base64.b64encode(b'name\nImported One\nImported Two\n'))
        wizard = self.env['base_import.import'].create({
            'res_model': 'res.partner', 'file': content, 'file_type': 'text/csv', 'file_name': 'p.csv'})
        options = {'has_headers': True, 'quoting': '"', 'separator': ',', 'encoding': 'utf-8'}
        wizard.execute_import(['name'], ['name'], options, dryrun=True)
        self.flush()
        self.assertFalse(self.env['audit.batch'].search([('name', '=', 'p.csv')]))
        self.assertFalse(self.Log.search([('record_display_name', '=', 'Imported One')]))
        wizard.execute_import(['name'], ['name'], options, dryrun=False)
        self.flush()
        batch = self.env['audit.batch'].search([('name', '=', 'p.csv')])
        self.assertEqual(batch.batch_type, 'import')
        self.assertEqual(batch.created_count, 2)
        self.assertEqual(set(batch.log_ids.mapped('source')), {'import'})

    def test_redaction_four_eyes_and_execution(self):
        partner = self.env['res.partner'].create({'name': 'Data Subject', 'email': 'subject@example.com'})
        self.flush()
        requester = new_test_user(self.env, 'dpo_one', groups='base.group_user,nx_audit_log.group_audit_admin')
        approver = new_test_user(self.env, 'dpo_two', groups='base.group_user,nx_audit_log.group_audit_admin')
        request = self.env['audit.redaction.request'].with_user(requester).create({
            'name': 'Erasure', 'reason': 'GDPR art. 17', 'model_name': 'res.partner',
            'res_ids': str(partner.id), 'field_names': 'email'})
        request.action_submit()
        with self.assertRaises(UserError):
            request.action_approve()
        request.with_user(approver).action_approve()
        request.with_user(approver).action_execute()
        line = self.line(self.logs(partner, 'CREATE'), 'email')
        self.assertTrue(line.redacted)
        self.assertNotIn('subject@example.com', str(line.new_value_json))
        self.assertTrue(self.Log.search([('operation', '=', 'REDACTION')]))
