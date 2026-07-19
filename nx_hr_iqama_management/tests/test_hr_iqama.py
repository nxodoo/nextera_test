import base64
from datetime import timedelta

from odoo import fields
from odoo.tests.common import SavepointCase
from odoo.exceptions import ValidationError


class TestHrIqama(SavepointCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Iqama Test Employee',
            'company_id': cls.env.company.id,
        })

    def test_required_attachments_block_stage_transition(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Residence Permit',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
            'required_document_ids': [
                (0, 0, {
                    'name': 'Passport Copy',
                    'mandatory': True,
                }),
                (0, 0, {
                    'name': 'Visa Copy',
                    'mandatory': True,
                }),
            ],
        })
        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_number': 'IQ-0001',
            'iqama_type_id': iqama_type.id,
        })

        iqama.action_submit_for_review()
        self.assertEqual(iqama.state, 'under_review')

        with self.assertRaises(ValidationError):
            iqama.action_approve()

        for attachment in iqama.attachment_ids.filtered('mandatory'):
            attachment.write({
                'attachment': base64.b64encode(b'test-file'),
                'attachment_filename': 'document.pdf',
            })

        iqama.action_approve()
        self.assertEqual(iqama.state, 'under_processing')

    def test_default_attachment_checklist_is_created(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Employee Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
            'required_document_ids': [
                (0, 0, {
                    'name': 'Employment Contract',
                    'mandatory': True,
                }),
            ],
        })
        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_number': 'IQ-0002',
            'iqama_type_id': iqama_type.id,
        })
        self.assertTrue(iqama.attachment_ids)
        self.assertEqual(iqama.attachment_ids.mapped('document_name'), ['Employment Contract'])

    def test_residency_visa_type_can_be_linked_to_iqama(self):
        current_year = fields.Date.context_today(self.env['hr.iqama']).year
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Work Residency Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
            'active': True,
            'expiry_notification_days': 45,
            'renewable': True,
            'estimated_cost_usd': 2500.0,
            'required_document_ids': [
                (0, 0, {
                    'name': 'Employment Contract',
                    'description': 'Signed employee contract.',
                    'mandatory': True,
                }),
            ],
        })

        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_number': 'IQ-0003',
            'iqama_type_id': iqama_type.id,
        })

        self.assertEqual(iqama.iqama_type_id, iqama_type)
        self.assertEqual(iqama.iqama_type_country_id, iqama_type.country_id)
        self.assertEqual(iqama.iqama_type_duration, 'annual')
        self.assertEqual(iqama_type.required_document_ids.mapped('name'), ['Employment Contract'])
        self.assertEqual(iqama.request_number, f'SA{current_year}001')

    def test_request_sequence_resets_per_country(self):
        current_year = fields.Date.context_today(self.env['hr.iqama']).year
        sa_type = self.env['hr.iqama.type'].create({
            'name': 'Saudi Work Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
        })
        us_type = self.env['hr.iqama.type'].create({
            'name': 'US Work Visa',
            'country_id': self.env.ref('base.us').id,
            'duration': 'annual',
        })

        sa_request_1 = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': sa_type.id,
        })
        sa_request_2 = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': sa_type.id,
        })
        us_request_1 = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': us_type.id,
        })

        self.assertEqual(sa_request_1.request_number, f'SA{current_year}001')
        self.assertEqual(sa_request_2.request_number, f'SA{current_year}002')
        self.assertEqual(us_request_1.request_number, f'US{current_year}001')

    def test_family_member_documents_auto_load_from_type(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Family Residency Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
            'required_document_ids': [
                (0, 0, {
                    'name': 'Passport Copy',
                    'mandatory': True,
                }),
            ],
        })

        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': iqama_type.id,
            'includes_family': True,
        })

        family_member = self.env['hr.iqama.family.member'].create({
            'iqama_id': iqama.id,
            'name': 'Family Member One',
        })

        self.assertEqual(family_member.document_ids.mapped('document_name'), ['Passport Copy'])

    def test_locked_final_state_blocks_edits(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Locked Flow Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
        })
        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': iqama_type.id,
        })

        iqama.with_context(bypass_iqama_lock=True).write({'state': 'cancelled'})

        with self.assertRaises(ValidationError):
            iqama.write({'issue_place': 'Riyadh'})

    def test_expiry_cron_marks_request_expired(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Expired Flow Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
        })
        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': iqama_type.id,
            'expiry_date': fields.Date.context_today(self.env['hr.iqama']) - timedelta(days=1),
        })
        iqama._cron_mark_expired_requests()
        self.assertEqual(iqama.state, 'expired')

    def test_processing_stage_navigation_returns_form_action(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Navigation Flow Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
        })
        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': iqama_type.id,
            'state': 'under_processing',
            'processing_stage': 'iqama_details',
        })

        fees_action = iqama.action_go_to_fees()
        self.assertEqual(iqama.processing_stage, 'fees')
        self.assertEqual(fees_action['res_id'], iqama.id)
        self.assertEqual(fees_action['view_mode'], 'form')

        security_action = iqama.action_go_to_security_review()
        self.assertEqual(iqama.processing_stage, 'security_review')
        self.assertEqual(security_action['res_id'], iqama.id)
        self.assertEqual(security_action['view_mode'], 'form')

    def test_write_creates_history_entry(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'History Flow Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
        })
        iqama = self.env['hr.iqama'].create({
            'employee_id': self.employee.id,
            'company_id': self.env.company.id,
            'iqama_type_id': iqama_type.id,
            'job_title': 'Initial Title',
        })

        iqama.write({'job_title': 'Updated Title'})

        self.assertEqual(len(iqama.history_ids), 1)
        history_line = iqama.history_ids[0]
        self.assertEqual(history_line.field_name, 'Job Title')
        self.assertEqual(history_line.from_value, 'Initial Title')
        self.assertEqual(history_line.to_value, 'Updated Title')
        self.assertEqual(history_line.changed_by_id, self.env.user)

    def test_expiry_date_cannot_be_before_issue_date(self):
        iqama_type = self.env['hr.iqama.type'].create({
            'name': 'Expiry Validation Visa',
            'country_id': self.env.ref('base.sa').id,
            'duration': 'annual',
        })

        with self.assertRaises(ValidationError):
            self.env['hr.iqama'].create({
                'employee_id': self.employee.id,
                'company_id': self.env.company.id,
                'iqama_type_id': iqama_type.id,
                'issue_date': fields.Date.from_string('2026-05-31'),
                'expiry_date': fields.Date.from_string('2026-05-30'),
            })
