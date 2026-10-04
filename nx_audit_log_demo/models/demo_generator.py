# -*- coding: utf-8 -*-
"""Demo evidence is produced by *running real business operations* through
the audit engine (no fake audit rows). Afterwards the demo events are moved
to dedicated ``demo-*`` hash chains, back-dated over two weeks and sealed, so
uninstalling the demo removes them without touching any real chain.
"""
import base64
import logging
import random
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.nx_audit_log.services import accumulator as acc_module
from odoo.addons.nx_audit_log.services import context as audit_context
from odoo.addons.nx_audit_log.services.api import flush_audit, semantic_action
from odoo.addons.nx_audit_log.services.rpc_patch import register_api_read

_logger = logging.getLogger(__name__)

MODULE = 'nx_audit_log_demo'
FRAME = ('demo', 'nx_audit_demo', 'Audit demo data')
DEMO_PATH = 'demo:nx_audit_demo'
DONE_PARAM = 'nx_audit_log_demo.generated'
DAYS_SPREAD = 14

CUSTOMERS = [
    ('Al Nour Trading', 'Cairo', '+20 2 2735 1100'),
    ('Delta Foods Distribution', 'Alexandria', '+20 3 4870 220'),
    ('Riyadh Medical Supplies', 'Riyadh', '+966 11 465 9000'),
    ('Gulf Steel Works', 'Dammam', '+966 13 812 4400'),
    ('Nile Pharma', 'Giza', '+20 2 3571 9910'),
    ('Red Sea Logistics', 'Jeddah', '+966 12 667 3020'),
    ('Sahara Construction', 'Cairo', '+20 2 2290 4455'),
    ('Oasis Retail Group', 'Riyadh', '+966 11 293 7788'),
]
CONTACTS = ['Ahmed Hassan', 'Mona Adel', 'Khaled Saeed', 'Sara Mahmoud', 'Omar Fathy',
            'Nour El-Din', 'Yasmin Ali', 'Fahad Al-Otaibi']
IPS = ['196.219.14.20', '41.33.120.7', '94.97.11.150', '156.204.33.12']
UA_DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0 Safari/537.36'
UA_MOBILE = 'Mozilla/5.0 (Linux; Android 14) OdooMobile/18.0'


class NxAuditDemo(models.AbstractModel):
    _name = 'nx.audit.demo'
    _description = 'Audit Log demo data generator'

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    @api.model
    def _cron_generate(self):
        self._generate_once()
        cron = self.env.ref(f'{MODULE}.cron_generate_demo', raise_if_not_found=False)
        if cron:
            cron.sudo().active = False

    @api.model
    def action_generate(self):
        if not self.env.user.has_group('nx_audit_log.group_audit_admin'):
            raise UserError(_("Only audit administrators can generate demo data."))
        generated = self._generate_once()
        message = _("Demo evidence generated.") if generated else _(
            "Demo data already exists. Uninstall the demo module to remove it.")
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'message': message, 'type': 'success' if generated else 'warning',
                           'next': {'type': 'ir.actions.client', 'tag': 'nx_audit_log.dashboard'}}}

    @api.model
    def _generate_once(self):
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param(DONE_PARAM):
            return False
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        (self.with_user(admin) if admin else self).sudo()._generate()
        return True

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def _generate(self):
        random.seed(18)
        # Clean execution stack: the demo is launched by a cron / server
        # action, but each scenario simulates its own transport and source.
        token = audit_context._EXEC.set((FRAME,))
        try:
            direct_logs = self._run_scenarios()
        finally:
            audit_context._EXEC.reset(token)
        demo_logs = self._collect_demo_logs(direct_logs)
        self._relocate_and_backdate(demo_logs)
        self._seal_and_verify()
        _logger.info("nx_audit_log_demo: %s demo audit events generated", len(demo_logs))

    def _run_scenarios(self):
        users = self._setup_users()
        tags = self._setup_tags()
        customers = self._scenario_customers(tags)
        self._scenario_team_edits(users, customers, tags)
        self._scenario_semantic_actions(users, customers)
        self._scenario_deletions(customers)
        self._scenario_bulk(users)
        self._scenario_import()
        self._scenario_data_access(users)
        self._scenario_automation(customers)
        self._scenario_security(users)
        direct_logs = self._scenario_authentication(users)
        direct_logs |= self._scenario_failures(users, customers)
        self._scenario_privacy(customers)
        self.env['ir.config_parameter'].sudo().set_param(DONE_PARAM, fields.Datetime.now())
        self._checkpoint()
        return direct_logs

    def _checkpoint(self):
        """Finalize pending evidence, then start a fresh transport context."""
        flush_audit(self.env)
        acc_module.drop_accumulator(self.env.cr)

    def _remember(self, records, prefix):
        Data = self.env['ir.model.data'].sudo()
        for record in records:
            Data.create({'module': MODULE, 'name': f'{prefix}_{record.id}',
                         'model': record._name, 'res_id': record.id, 'noupdate': True})
        return records

    @staticmethod
    def _meta(transport, ip=None, ua=UA_DESKTOP, claimed=False):
        return {
            'transport': transport, 'path': '/web/dataset/call_kw' if transport == 'web_ui' else '/jsonrpc',
            'http_method': 'POST', 'ip_address': ip or random.choice(IPS), 'user_agent': ua,
            'claimed_client': claimed, 'session_hash': uuid.uuid4().hex[:24],
            'initiating_uid': False, 'correlation_id': uuid.uuid4().hex,
        }

    def _as_web(self, ip=None, ua=UA_DESKTOP, claimed=False):
        return audit_context.rpc_scope(self._meta('web_ui', ip, ua, claimed))

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _setup_users(self):
        with self._as_web():
            groups = [(6, 0, [self.env.ref('base.group_user').id,
                              self.env.ref('base.group_partner_manager').id,
                              self.env.ref('base.group_allow_export').id])]
            users = self.env['res.users'].with_context(no_reset_password=True).create([
                {'name': 'Hany Sales (demo)', 'login': 'demo.sales@nextera.demo', 'groups_id': groups},
                {'name': 'Rania Accountant (demo)', 'login': 'demo.accountant@nextera.demo',
                 'groups_id': groups},
            ])
            self._remember(users, 'user')
            self._remember(users.partner_id, 'user_partner')
            users[0].password = 'Demo-Only-Password-1'
        self._checkpoint()
        return users

    def _setup_tags(self):
        with audit_context.guarded():
            rule = self.env['audit.rule'].create({
                'name': 'Demo: contact tags',
                'model_id': self.env['ir.model']._get_id('res.partner.category'),
            })
            self._remember(rule, 'rule')
        with self._as_web():
            Tag = self.env['res.partner.category']
            region = Tag.create({'name': 'Region (demo)'})
            tags = {
                'region': region,
                'cairo': Tag.create({'name': 'Cairo', 'parent_id': region.id}),
                'riyadh': Tag.create({'name': 'Riyadh', 'parent_id': region.id}),
                'vip': Tag.create({'name': 'VIP (demo)', 'color': 3}),
                'wholesale': Tag.create({'name': 'Wholesale (demo)', 'color': 5}),
                'retail': Tag.create({'name': 'Retail (demo)', 'color': 7}),
            }
            for key, tag in tags.items():
                self._remember(tag, f'tag_{key}')
        self._checkpoint()
        return tags

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------
    def _scenario_customers(self, tags):
        Partner = self.env['res.partner']
        customers = Partner
        with self._as_web():
            for index, (name, city, phone) in enumerate(CUSTOMERS):
                region = tags['riyadh'] if phone.startswith('+966') else tags['cairo']
                kind = tags['wholesale'] if index % 2 else tags['retail']
                company = Partner.create({
                    'name': name, 'is_company': True, 'city': city, 'phone': phone,
                    'email': f"info@{name.split()[0].lower()}.demo",
                    'category_id': [(6, 0, (region | kind).ids)],
                })
                contact = Partner.create({
                    'name': CONTACTS[index], 'parent_id': company.id, 'function': 'Purchasing Manager',
                    'email': f"{CONTACTS[index].split()[0].lower()}@{name.split()[0].lower()}.demo",
                })
                customers |= self._remember(company | contact, f'partner_{index}')
        self._checkpoint()
        return customers.filtered('is_company')

    def _scenario_team_edits(self, users, customers, tags):
        sales, accountant = users
        with self._as_web(ip=IPS[0]):
            for company in customers[:4].with_user(sales):
                company.write({'phone': company.phone.replace(' ', '-'),
                               'category_id': [(4, tags['vip'].id)]})
        self._checkpoint()
        with self._as_web(ip=IPS[1], ua=UA_MOBILE, claimed='mobile_app'):
            customers[4].with_user(sales).write({'street': '12 Tahrir St.', 'zip': '11511'})
        self._checkpoint()
        with self._as_web(ip=IPS[2]):
            contact = customers[0].child_ids[:1].with_user(accountant)
            contact.write({'parent_id': customers[1].id, 'function': 'Finance Manager'})
            customers[2].with_user(accountant).write({
                'category_id': [(3, tags['wholesale'].id), (3, tags['retail'].id), (4, tags['vip'].id)]})
            customers[3].with_user(accountant).write({'vat': 'SA300012345600003', 'ref': 'CUST-0004'})
        self._checkpoint()
        with self._as_web(ip=IPS[3]):
            tags['vip'].with_context(lang='en_US').write({'name': 'Key Account (demo)', 'color': 1})
        self._checkpoint()

    def _scenario_semantic_actions(self, users, customers):
        sales = users[0]
        with self._as_web(ip=IPS[0]):
            target = customers[5].with_user(sales)
            with semantic_action(target, 'action_archive'):
                target.action_archive()
        self._checkpoint()
        with self._as_web(ip=IPS[0]):
            with semantic_action(target, 'action_unarchive'):
                target.action_unarchive()
        self._checkpoint()

    def _scenario_deletions(self, customers):
        with self._as_web(ip=IPS[2]):
            # contacts keep existing: PostgreSQL sets parent_id to NULL (database cascade evidence)
            doomed = customers[6]
            doomed.unlink()
        self._checkpoint()
        with self._as_web(ip=IPS[2]):
            # deleting the parent tag cascades to its children and unlinks them from partners
            self.env['res.partner.category'].search([('name', '=', 'Region (demo)')]).unlink()
        self._checkpoint()

    def _scenario_bulk(self, users):
        Partner = self.env['res.partner']
        with self._as_web(ip=IPS[1]):
            leads = Partner.create([{'name': f'Prospect {i:03d} (demo)', 'city': 'Cairo'}
                                    for i in range(1, 121)])
            self._remember(leads, 'lead')
        self._checkpoint()
        with self._as_web(ip=IPS[1]):
            leads.with_user(users[0]).write({'ref': 'CAMPAIGN-Q4', 'comment': '<p>Autumn campaign</p>'})
        self._checkpoint()

    def _scenario_import(self):
        rows = ['name,city,email'] + [
            f'Imported Customer {i} (demo),{city},import{i}@customers.demo'
            for i, city in enumerate(['Cairo', 'Riyadh', 'Jeddah', 'Mansoura', 'Tanta'], start=1)]
        wizard = self.env['base_import.import'].create({
            'res_model': 'res.partner', 'file': '\n'.join(rows).encode(), 'file_type': 'text/csv',
            'file_name': 'customers_october_demo.csv'})
        options = {'has_headers': True, 'quoting': '"', 'separator': ',', 'encoding': 'utf-8'}
        with self._as_web(ip=IPS[0]):
            wizard.execute_import(['name', 'city', 'email'], ['name', 'city', 'email'], options, dryrun=True)
            result = wizard.execute_import(['name', 'city', 'email'], ['name', 'city', 'email'], options)
        self._remember(self.env['res.partner'].browse(result.get('ids') or []), 'imported')
        self._checkpoint()

    def _scenario_data_access(self, users):
        accountant = users[1]
        Partner = self.env['res.partner'].with_user(accountant)
        with self._as_web(ip=IPS[2]):
            Partner.search([('name', 'like', '(demo)')], limit=80).export_data(['name', 'email', 'phone', 'vat'])
        self._checkpoint()
        with audit_context.rpc_scope(self._meta('json_rpc', ip='185.220.101.4', ua='python-requests/2.32')):
            ids = Partner.search([], limit=200).ids or [0]
            fake_page = [{'id': ids[i % len(ids)]} for i in range(850)]
            register_api_read(Partner.env, 'res.partner', 'search_read', [[]],
                              {'fields': ['name', 'email', 'phone', 'street']}, fake_page, api=True)
        self._checkpoint()

    def _scenario_automation(self, customers):
        with audit_context.execution('cron', 'demo_sync', 'Nightly CRM sync (demo)'):
            for company in customers[:3]:
                company.write({'comment': f'<p>Credit score refreshed: {random.randint(560, 820)}</p>'})
        self._checkpoint()
        with audit_context.execution('server_action', 'demo_action', 'Normalize phones (demo)'):
            customers[7].write({'phone': customers[7].phone.replace(' ', '')})
        self._checkpoint()
        with audit_context.rpc_scope(self._meta('json_rpc', ip='10.20.0.15', ua='ERP-Connector/2.1')):
            customers[1].write({'ref': 'ERP-55012', 'website': 'https://delta-foods.demo'})
        self._checkpoint()

    def _scenario_security(self, users):
        sales = users[0]
        system = self.env.ref('base.group_system')
        with self._as_web(ip=IPS[3]):
            sales.write({'groups_id': [(4, system.id)]})       # privilege escalation -> alert
        self._checkpoint()
        with self._as_web(ip=IPS[3]):
            sales.write({'groups_id': [(3, system.id)]})       # reverted
        self._checkpoint()
        with self._as_web(ip=IPS[3]):
            ICP = self.env['ir.config_parameter']
            secret = ICP.create({'key': 'demo.payment_gateway.api_secret', 'value': 'sk_demo_123'})
            public = ICP.create({'key': 'demo.portal.welcome_banner', 'value': 'Welcome'})
            secret.value = 'sk_demo_456'
            public.value = 'Welcome to Nextera'
            self._remember(secret | public, 'param')
        self._checkpoint()

    def _scenario_authentication(self, users):
        Log = self.env['audit.log']
        logs = Log
        extra = {'execution_path': DEMO_PATH}
        for user, ip in ((users[0], IPS[0]), (users[1], IPS[2]), (users[0], IPS[1])):
            logs |= Log._record_auth_event('LOGIN', uid=user.id, login=user.login,
                                           meta=self._meta('web_ui', ip), extra=dict(
                                               extra, action_method='password', action_label='mfa: default'))
        attacker = self._meta('web_ui', ip='203.0.113.77', ua='curl/8.4')
        for _attempt in range(12):
            logs |= Log._record_failed_login('admin', meta=attacker)
        logs |= Log._record_failed_login('Pa$$w0rd-typed-in-login', meta=self._meta('web_ui', IPS[1]))
        logs |= Log._record_auth_event('LOGOUT', uid=users[1].id, login=users[1].login,
                                       meta=self._meta('web_ui', IPS[2]), extra=extra)
        return logs

    def _scenario_failures(self, users, customers):
        Log = self.env['audit.log']
        logs = Log._record_failure(
            'res.partner', 'unlink', customers[:1].ids, users[0].id,
            "AccessError: You are not allowed to delete 'Contact' records.",
            meta=self._meta('web_ui', IPS[0]))
        logs |= Log._record_failure(
            'res.partner', 'write', customers[2:3].ids, users[1].id,
            'ValidationError: The VAT number is not valid for Saudi Arabia.',
            meta=self._meta('web_ui', IPS[2]))
        return logs

    def _scenario_privacy(self, customers):
        request = self.env['audit.redaction.request'].create({
            'name': '[Demo] Erasure request - former contact',
            'reason': 'Data subject request (GDPR art. 17 / PDPL). Demo only.',
            'legal_reference': 'DSR-2026-0042',
            'model_name': 'res.partner',
            'res_ids': ','.join(map(str, customers[0].child_ids.ids)) or '0',
            'field_names': 'email,phone',
        })
        self._remember(request, 'redaction')

    # ------------------------------------------------------------------
    # Relocation to demo chains, back-dating, sealing
    # ------------------------------------------------------------------
    def _collect_demo_logs(self, direct_logs):
        engine_logs = self.env['audit.log'].sudo().search([('execution_path', 'like', DEMO_PATH)])
        return (engine_logs | direct_logs.sudo()).filtered(lambda log: log.seal_state == 'unsealed')

    def _relocate_and_backdate(self, logs):
        """Move demo events to their own chains and spread them over two weeks.

        Done in SQL on unsealed demo rows only: evidence immutability is an
        ORM rule; this is controlled seeding of demo data.
        """
        now = fields.Datetime.now()
        by_request = {}
        for log in logs.sorted('id'):
            by_request.setdefault(log.correlation_id or f'log{log.id}', []).append(log.id)
        groups = list(by_request.values())
        cr = self.env.cr
        recent_from = int(len(groups) * 0.7)   # last 30% of the story happens today
        for position, ids in enumerate(groups):
            if position >= recent_from:
                span = max(len(groups) - recent_from, 1)
                when = now - timedelta(hours=20 * (len(groups) - position) / span,
                                       minutes=random.randint(1, 30))
            else:
                age = DAYS_SPREAD * (recent_from - position) / max(recent_from, 1)
                when = now - timedelta(days=age, minutes=random.randint(0, 600))
            cr.execute("""
                UPDATE audit_log
                   SET event_datetime = %s,
                       event_datetime_last = CASE WHEN event_datetime_last IS NULL THEN NULL ELSE %s END,
                       chain_key = 'demo-' || chain_key,
                       seal_after = %s
                 WHERE id IN %s AND seal_state = 'unsealed' AND chain_key NOT LIKE 'demo-%%'
            """, [when, when, now - timedelta(minutes=1), tuple(ids)])
            cr.execute("UPDATE audit_log_line SET event_datetime = %s WHERE audit_log_id IN %s",
                       [when, tuple(ids)])
        self.env['audit.log'].invalidate_model()
        self.env['audit.log.line'].invalidate_model()

    def _seal_and_verify(self):
        self.env['audit.chain'].sudo()._cron_seal()
        self.env['audit.integrity.check'].sudo().create({'name': '[Demo] Integrity verification'})._run()
