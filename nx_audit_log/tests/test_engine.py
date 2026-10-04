# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from odoo.addons.nx_audit_log.services.api import flush_audit, semantic_action


class AuditCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['audit.log']
        cls.Rule = cls.env['audit.rule']
        cls.partner_rule = cls.Rule.search([('model_id.model', '=', 'res.partner')], limit=1)
        cls.partner_rule.write({'derived_policy': 'all', 'op_read': False})

    def flush(self):
        flush_audit(self.env)

    def logs(self, records, operation=None):
        domain = [('model_name', '=', records._name), ('res_id', 'in', records.ids)]
        if operation:
            domain.append(('operation', '=', operation))
        return self.Log.search(domain, order='id')

    def line(self, log, field_name, change_type=None):
        lines = log.line_ids.filtered(lambda l: l.field_name == field_name)
        if change_type:
            lines = lines.filtered(lambda l: l.change_type == change_type)
        return lines


@tagged('post_install', '-at_install', 'nx_audit')
class TestCrud(AuditCase):

    def test_create_update_delete(self):
        partner = self.env['res.partner'].create({'name': 'ABC Trading'})
        self.flush()
        created = self.logs(partner, 'CREATE')
        self.assertEqual(len(created), 1)
        self.assertEqual(self.line(created, 'name').new_value_text, 'ABC Trading')

        partner.name = 'XYZ Trading'
        self.flush()
        update = self.logs(partner, 'UPDATE')
        self.assertEqual(len(update), 1)
        name_line = self.line(update, 'name')
        self.assertEqual((name_line.old_value_text, name_line.new_value_text), ('ABC Trading', 'XYZ Trading'))
        self.assertEqual(name_line.change_origin, 'direct')

        partner_id = partner.id
        partner.unlink()
        self.flush()
        deleted = self.Log.search([('model_name', '=', 'res.partner'), ('res_id', '=', partner_id),
                                   ('operation', '=', 'DELETE')])
        self.assertEqual(len(deleted), 1)
        self.assertEqual(deleted.record_display_name, 'XYZ Trading')
        self.assertEqual(deleted.sudo().delete_snapshot['name']['v'], 'XYZ Trading')

    def test_same_value_write_is_not_logged(self):
        partner = self.env['res.partner'].create({'name': 'Same'})
        self.flush()
        partner.write({'name': 'Same'})
        self.flush()
        self.assertFalse(self.logs(partner, 'UPDATE'))

    def test_create_then_writes_aggregate_into_one_event(self):
        partner = self.env['res.partner'].create({'name': 'Draft'})
        partner.write({'name': 'Step 1'})
        partner.write({'name': 'Step 2', 'ref': 'R1'})
        partner.write({'comment': '<p>note</p>'})
        self.flush()
        logs = self.logs(partner)
        self.assertEqual(logs.mapped('operation'), ['CREATE'])
        self.assertEqual(self.line(logs, 'name').new_value_text, 'Step 2')

    def test_repeated_writes_keep_first_before_and_final_after(self):
        partner = self.env['res.partner'].create({'name': 'Origin'})
        self.flush()
        partner.write({'name': 'Middle'})
        partner.write({'name': 'Final'})
        self.flush()
        update = self.logs(partner, 'UPDATE')
        self.assertEqual(len(update), 1)
        line = self.line(update, 'name')
        self.assertEqual((line.old_value_text, line.new_value_text), ('Origin', 'Final'))

    def test_bulk_write_has_per_record_values_and_batch(self):
        partners = self.env['res.partner'].create([{'name': f'P{i}'} for i in range(120)])
        self.flush()
        partners.write({'ref': 'BULK'})
        self.flush()
        updates = self.Log.search([('model_name', '=', 'res.partner'), ('res_id', 'in', partners.ids),
                                   ('operation', '=', 'UPDATE')])
        self.assertEqual(len(updates), 120)
        self.assertEqual(len(updates.mapped('batch_id')), 1)
        self.assertEqual(updates.mapped('batch_id').batch_type, 'bulk_write')

    def test_savepoint_rollback_produces_no_evidence(self):
        partner = self.env['res.partner'].create({'name': 'Stable'})
        self.flush()
        try:
            with self.env.cr.savepoint():
                partner.write({'name': 'Rolled back'})
                self.env['res.partner'].create({'name': 'Ghost'})
                raise ValueError('abort')
        except ValueError:
            pass
        self.flush()
        self.assertFalse(self.logs(partner, 'UPDATE'))
        self.assertFalse(self.Log.search([('record_display_name', '=', 'Ghost')]))

    def test_rule_deactivation_stops_auditing(self):
        self.partner_rule.active = False
        partner = self.env['res.partner'].create({'name': 'Silent'})
        self.flush()
        self.assertFalse(self.logs(partner))

    def test_configuration_change_is_audited(self):
        self.partner_rule.write({'snapshot_policy': 'full'})
        config = self.Log.search([('operation', '=', 'CONFIG'), ('model_name', '=', 'audit.rule'),
                                  ('res_id', '=', self.partner_rule.id)])
        self.assertTrue(config)
        self.assertIn('snapshot_policy', config.line_ids.mapped('field_name'))


@tagged('post_install', '-at_install', 'nx_audit')
class TestRelations(AuditCase):

    def test_many2one_shows_names(self):
        abc = self.env['res.partner'].create({'name': 'ABC Company', 'is_company': True})
        xyz = self.env['res.partner'].create({'name': 'XYZ Company', 'is_company': True})
        contact = self.env['res.partner'].create({'name': 'Contact', 'parent_id': abc.id})
        self.flush()
        contact.parent_id = xyz
        self.flush()
        line = self.line(self.logs(contact, 'UPDATE'), 'parent_id')
        self.assertEqual((line.old_value_text, line.new_value_text), ('ABC Company', 'XYZ Company'))
        self.assertEqual(line.new_value_json['id'], xyz.id)

    def test_many2many_added_and_removed_separately(self):
        Tag = self.env['res.partner.category']
        old_tag, new_tag = Tag.create({'name': 'Old'}), Tag.create({'name': 'New'})
        partner = self.env['res.partner'].create({'name': 'Tagged', 'category_id': [(6, 0, old_tag.ids)]})
        self.flush()
        partner.category_id = [(6, 0, new_tag.ids)]
        self.flush()
        update = self.logs(partner, 'UPDATE')
        self.assertEqual(self.line(update, 'category_id', 'add').new_value_text, 'New')
        self.assertEqual(self.line(update, 'category_id', 'remove').old_value_text, 'Old')

    def test_derived_stored_compute_is_classified(self):
        company = self.env['res.partner'].create({'name': 'Parent Co', 'is_company': True})
        contact = self.env['res.partner'].create({'name': 'Child'})
        self.flush()
        contact.parent_id = company
        self.flush()
        update = self.logs(contact, 'UPDATE')
        self.assertEqual(self.line(update, 'parent_id').change_origin, 'direct')
        derived = self.line(update, 'commercial_partner_id')
        self.assertTrue(derived)
        self.assertEqual(derived.change_origin, 'derived')
        self.assertEqual(derived.new_value_text, 'Parent Co')

    def test_direct_only_policy_drops_derived(self):
        self.partner_rule.derived_policy = 'direct'
        company = self.env['res.partner'].create({'name': 'Parent Co', 'is_company': True})
        contact = self.env['res.partner'].create({'name': 'Child'})
        self.flush()
        contact.parent_id = company
        self.flush()
        update = self.logs(contact, 'UPDATE')
        self.assertFalse(self.line(update, 'commercial_partner_id'))

    def test_database_set_null_is_captured(self):
        company = self.env['res.partner'].create({'name': 'Gone Co', 'is_company': True})
        contact = self.env['res.partner'].create({'name': 'Orphan', 'parent_id': company.id})
        self.flush()
        company.unlink()
        self.flush()
        update = self.logs(contact, 'UPDATE')
        line = self.line(update, 'parent_id')
        self.assertTrue(line, "set null done by PostgreSQL must be evidenced")
        self.assertEqual(line.change_type, 'clear')
        self.assertEqual(line.old_value_text, 'Gone Co')

    def test_database_cascade_and_m2m_cleanup(self):
        Tag = self.env['res.partner.category']
        self.Rule.create({'name': 'Tags', 'model_id': self.env['ir.model']._get_id('res.partner.category')})
        parent = Tag.create({'name': 'Parent tag'})
        child = Tag.create({'name': 'Child tag', 'parent_id': parent.id})
        partner = self.env['res.partner'].create({'name': 'Holder', 'category_id': [(6, 0, child.ids)]})
        self.flush()
        child_id = child.id
        parent.unlink()
        self.flush()
        child_delete = self.Log.search([('model_name', '=', 'res.partner.category'),
                                        ('res_id', '=', child_id), ('operation', '=', 'DELETE')])
        self.assertTrue(child_delete, "cascade delete done by PostgreSQL must be evidenced")
        self.assertEqual(child_delete.change_origin, 'database_fk')
        removal = self.line(self.logs(partner, 'UPDATE'), 'category_id', 'remove')
        self.assertEqual(removal.old_value_text, 'Parent tag / Child tag')
        self.assertEqual(removal.change_origin, 'database_fk')

    def test_m2m_inverse_side_is_captured(self):
        group = self.env['res.groups'].create({'name': 'Audit test group'})
        user = self.env['res.users'].create({'name': 'Inv', 'login': 'inverse_user'})
        self.flush()
        group.write({'users': [(4, user.id)]})
        self.flush()
        user_update = self.logs(user, 'UPDATE')
        self.assertEqual(self.line(user_update, 'groups_id', 'add').new_value_json['ids'], [group.id])


@tagged('post_install', '-at_install', 'nx_audit')
class TestScopeAndPrivacy(AuditCase):

    def test_domain_before_or_after(self):
        Tag = self.env['res.partner.category']
        self.Rule.create({'name': 'Color 5 tags', 'domain': "[('color', '=', 5)]",
                          'model_id': self.env['ir.model']._get_id('res.partner.category')})
        tag = Tag.create({'name': 'T', 'color': 5})
        self.flush()
        tag.color = 1       # before matches, after does not -> audited
        self.flush()
        tag.color = 2       # neither matches -> not audited
        self.flush()
        updates = self.logs(tag, 'UPDATE')
        self.assertEqual(len(updates), 1)
        self.assertEqual(self.line(updates, 'color').new_value_text, '1')

    def test_password_is_never_stored(self):
        user = self.env['res.users'].create({'name': 'Secret', 'login': 'secret_user'})
        self.flush()
        user.password = 'Sup3r-Secret!'
        self.flush()
        line = self.line(self.logs(user, 'ACTION'), 'password')
        self.assertTrue(line.masked)
        self.assertEqual(line.new_value_text, '[changed - value not stored]')
        self.env.cr.execute("SELECT count(*) FROM audit_log_line WHERE new_value_json::text LIKE %s "
                            "OR new_value_text LIKE %s", ['%Sup3r%', '%Sup3r%'])
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_secret_system_parameter_is_masked(self):
        self.env['ir.config_parameter'].set_param('my.api_secret', 'abc123')
        self.env['ir.config_parameter'].set_param('my.public_flag', 'yes')
        self.flush()
        secret = self.Log.search([('model_name', '=', 'ir.config_parameter'),
                                  ('record_display_name', '=', 'my.api_secret')])
        public = self.Log.search([('model_name', '=', 'ir.config_parameter'),
                                  ('record_display_name', '=', 'my.public_flag')])
        self.assertTrue(self.line(secret, 'value').masked)
        self.assertEqual(self.line(public, 'value').new_value_text, 'yes')

    def test_client_context_cannot_bypass_or_spoof(self):
        partner = self.env['res.partner'].with_context(
            audit_bypass=True, nx_audit_bypass=True, source='mobile').create({'name': 'Spoof'})
        self.flush()
        log = self.logs(partner, 'CREATE')
        self.assertTrue(log)
        self.assertNotEqual(log.source, 'mobile')

    def test_translation_change_records_language(self):
        self.env['res.lang']._activate_lang('fr_FR')
        Tag = self.env['res.partner.category']
        self.Rule.create({'name': 'Tags', 'model_id': self.env['ir.model']._get_id('res.partner.category')})
        tag = Tag.create({'name': 'Hello'})
        self.flush()
        tag.with_context(lang='fr_FR').name = 'Bonjour'
        self.flush()
        line = self.line(self.logs(tag, 'UPDATE'), 'name')
        self.assertEqual(line.lang, 'fr_FR')
        self.assertEqual(line.new_value_text, 'Bonjour')

    def test_company_change_visible_to_both_companies(self):
        company_a = self.env['res.company'].create({'name': 'Company A'})
        company_b = self.env['res.company'].create({'name': 'Company B'})
        partner = self.env['res.partner'].create({'name': 'Moving', 'company_id': company_a.id})
        self.flush()
        partner.company_id = company_b
        self.flush()
        update = self.logs(partner, 'UPDATE')
        self.assertEqual(set(update.visible_company_ids.ids), {company_a.id, company_b.id})
        self.assertFalse(update.is_shared)

    def test_shared_record_is_flagged(self):
        partner = self.env['res.partner'].create({'name': 'Shared contact'})
        self.flush()
        self.assertTrue(self.logs(partner, 'CREATE').is_shared)

    def test_semantic_action_links_changes(self):
        partner = self.env['res.partner'].create({'name': 'Action target'})
        self.flush()
        with semantic_action(partner, 'action_mark_vip', 'Mark VIP'):
            partner.write({'ref': 'VIP'})
        self.flush()
        action = self.Log.search([('operation', '=', 'ACTION'), ('res_id', '=', partner.id),
                                  ('model_name', '=', 'res.partner')])
        self.assertEqual(action.action_label, 'Mark VIP')
        self.assertEqual(action.action_change_ids.mapped('operation'), ['UPDATE'])

    def test_export_is_logged(self):
        partners = self.env['res.partner'].create([{'name': 'E1'}, {'name': 'E2'}])
        partners.export_data(['name', 'email'])
        self.flush()
        export = self.Log.search([('operation', '=', 'EXPORT'), ('model_name', '=', 'res.partner')],
                                 order='id desc', limit=1)
        self.assertEqual(export.record_count, 2)
        self.assertEqual(export.fields_json, ['email', 'name'])
