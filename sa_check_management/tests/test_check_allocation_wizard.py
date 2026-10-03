from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import CheckAccountingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckAllocationWizard(CheckAccountingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.split_term = cls.env["account.payment.term"].create({
            "name": "50/50 Check Test",
            "line_ids": [
                Command.create({"value": "percent", "value_amount": 50.0, "nb_days": 0}),
                Command.create({"value": "percent", "value_amount": 50.0, "nb_days": 30}),
            ],
        })
        cls.installment_customer = cls.env["res.partner"].create({
            "name": "Installment Customer",
            "property_payment_term_id": cls.split_term.id,
        })

    def _open_wizard(self, check, user=None):
        record = check.with_user(user) if user else check
        action = record.action_open_allocation_wizard()
        return self.env["check.allocation.wizard"].with_user(user or self.env.user).browse(action["res_id"])

    def _wizard_line(self, wizard, document):
        return wizard.line_ids.filtered(lambda line: line.document_name == document.name)

    def _select(self, wizard, document, amount):
        line = self._wizard_line(wizard, document)
        line.write({"selected": True, "amount": amount})
        return line

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    def test_lists_only_open_documents_of_partner(self):
        listed = self._invoice(500.0)
        already_allocated = self._invoice(300.0)
        self._invoice(400.0, partner=self.other_customer)
        self._invoice(200.0, currency=self.eur)
        self.init_invoice("out_refund", partner=self.customer, amounts=[100.0], taxes=[], post=True)
        self._bill(150.0, partner=self.customer)
        check = self._create_incoming(amount=2000.0)
        self._allocate(check, already_allocated, 300.0)
        wizard = self._open_wizard(check)
        self.assertEqual(wizard.line_ids.mapped("document_name"), [listed.name])
        self.assertAlmostEqual(wizard.available_amount, 1700.0)

    def test_outgoing_lists_vendor_bills(self):
        bill = self._bill(450.0)
        self._invoice(300.0, partner=self.vendor)
        check = self._create_outgoing(amount=450.0)
        wizard = self._open_wizard(check)
        self.assertEqual(wizard.line_ids.mapped("document_name"), [bill.name])
        self._select(wizard, bill, 450.0)
        wizard.action_confirm()
        check.action_issue()
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))

    def test_reserved_amount_on_other_draft_check_is_excluded(self):
        invoice = self._invoice(1000.0)
        first = self._create_incoming(check_number="R-1", amount=600.0)
        self._allocate(first, invoice, 600.0)
        second = self._create_incoming(check_number="R-2", amount=1000.0)
        wizard = self._open_wizard(second)
        self.assertAlmostEqual(self._wizard_line(wizard, invoice).open_amount, 400.0)

    # ------------------------------------------------------------------
    # Distribution
    # ------------------------------------------------------------------
    def test_installments_distributed_earliest_first(self):
        invoice = self._invoice(1000.0, partner=self.installment_customer)
        check = self._create_incoming(amount=700.0, partner_id=self.installment_customer.id)
        wizard = self._open_wizard(check)
        line = self._select(wizard, invoice, 700.0)
        self.assertEqual(line.installment_count, 2)
        wizard.action_confirm()
        allocations = check.allocation_ids.sorted(lambda a: a.date_maturity)
        self.assertEqual(allocations.mapped("amount"), [500.0, 200.0])
        self.assertLess(allocations[0].date_maturity, allocations[1].date_maturity)
        check.action_receive()
        self.assertAlmostEqual(invoice.amount_residual, 300.0)

    def test_selecting_defaults_amount(self):
        invoice = self._invoice(1000.0)
        check = self._create_incoming(amount=600.0)
        wizard = self._open_wizard(check)
        with Form(wizard) as form:
            index = wizard.line_ids.ids.index(self._wizard_line(wizard, invoice).id)
            with form.line_ids.edit(index) as line:
                line.selected = True
                self.assertAlmostEqual(line.amount, 600.0)
                line.selected = False
                self.assertAlmostEqual(line.amount, 0.0)

    def test_selection_cannot_exceed_check(self):
        first, second = self._invoice(400.0), self._invoice(400.0)
        check = self._create_incoming(amount=500.0)
        wizard = self._open_wizard(check)
        self._select(wizard, first, 400.0)
        self._select(wizard, second, 400.0)
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(check.allocation_ids)

    def test_amount_cannot_exceed_open_amount(self):
        invoice = self._invoice(1000.0)
        check = self._create_incoming(amount=2000.0)
        wizard = self._open_wizard(check)
        self._select(wizard, invoice, 1200.0)
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_requires_a_selection(self):
        self._invoice(1000.0)
        check = self._create_incoming(amount=1000.0)
        with self.assertRaises(UserError):
            self._open_wizard(check).action_confirm()

    def test_stale_wizard_is_detected(self):
        invoice = self._invoice(1000.0)
        check = self._create_incoming(check_number="S-1", amount=1000.0)
        wizard = self._open_wizard(check)
        other = self._create_incoming(check_number="S-2", amount=800.0)
        self._allocate(other, invoice, 800.0)
        self._select(wizard, invoice, 1000.0)
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(check.allocation_ids)

    # ------------------------------------------------------------------
    # Guards and access
    # ------------------------------------------------------------------
    def test_wizard_requires_draft_payment_check(self):
        received = self._create_incoming(check_number="G-1", amount=100.0)
        received.action_receive()
        with self.assertRaises(UserError):
            received.action_open_allocation_wizard()
        guarantee = self._create_incoming(check_number="G-2", amount=100.0, purpose="guarantee")
        with self.assertRaises(UserError):
            guarantee.action_open_allocation_wizard()

    def test_non_billing_user_can_add_invoices(self):
        self.assertFalse(self.check_user.has_group("account.group_account_invoice"))
        invoice = self._invoice(800.0)
        check = self._create_incoming(env=self.env(user=self.check_user), amount=800.0)
        wizard = self._open_wizard(check, user=self.check_user)
        self.assertEqual(wizard.line_ids.mapped("document_name"), [invoice.name])
        self._select(wizard, invoice, 800.0)
        wizard.action_confirm()
        allocation = check.with_user(self.check_user).allocation_ids
        self.assertEqual(allocation.document_name, invoice.name)
        self.assertAlmostEqual(allocation.line_residual, 800.0)
        self.assertEqual(allocation.create_uid, self.check_user)
        check.with_user(self.check_user).action_receive()
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_user_can_remove_allocation_in_draft(self):
        invoice = self._invoice(500.0)
        check = self._create_incoming(env=self.env(user=self.check_user), amount=500.0)
        wizard = self._open_wizard(check, user=self.check_user)
        self._select(wizard, invoice, 500.0)
        wizard.action_confirm()
        check.with_user(self.check_user).allocation_ids.unlink()
        self.assertFalse(check.allocation_ids)

    # ------------------------------------------------------------------
    # Posting safety
    # ------------------------------------------------------------------
    def test_posting_rejects_allocations_no_longer_open(self):
        invoice = self._invoice(1000.0)
        first = self._create_incoming(check_number="P-1", amount=1000.0)
        second = self._create_incoming(check_number="P-2", amount=1000.0)
        self._allocate(first, invoice, 1000.0)
        self._allocate(second, invoice, 1000.0)
        first.action_receive()
        with self.assertRaises(UserError):
            second.action_receive()
        second.invalidate_recordset()
        self.assertEqual(second.state, "draft")
        self.assertFalse(second.payment_ids)
