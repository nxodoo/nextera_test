from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from .common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management")
class TestCheckEndorsement(CheckBankingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_vendor = cls.env["res.partner"].create({"name": "Other Vendor"})

    def _endorse(self, check, vendor=None, bills=(), user=None):
        model = self.env["check.endorsement.wizard"]
        if user:
            model = model.with_user(user)
        wizard = model.with_context(default_check_id=check.id).create({"partner_id": (vendor or self.vendor).id})
        wizard._onchange_partner_id()
        for bill, amount in bills:
            wizard.line_ids.filtered(lambda line: line.document_name == bill.name).write({
                "selected": True, "amount": amount,
            })
        wizard.action_confirm()
        return wizard

    def _vendor_open_debit(self, check):
        lines = self._entries(check, "endorsement").line_ids.filtered(
            lambda line: line.partner_id == check.endorsed_partner_id and line.balance > 0
        )
        return sum(lines.mapped("amount_residual"))

    # ------------------------------------------------------------------
    # Endorsement
    # ------------------------------------------------------------------
    def test_endorse_settles_vendor_bill(self):
        check, invoice = self._received_check(1000.0)
        bill = self._bill(1000.0)
        self._endorse(check, bills=[(bill, 1000.0)])
        self.assertEqual(check.state, "endorsed")
        self.assertEqual(check.endorsed_partner_id, self.vendor)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual), "Customer side stays settled")
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        self.assertFalse(check._open_holding_lines())
        self.assertEqual(check.endorsement_line_ids.mapped("state"), ["active"])
        self.assertIn("endorsed", check.event_ids.mapped("event_type"))

    def test_partial_endorsement_leaves_vendor_advance(self):
        check, _inv = self._received_check(1000.0)
        bill = self._bill(600.0)
        self._endorse(check, bills=[(bill, 600.0)])
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))
        self.assertAlmostEqual(self._vendor_open_debit(check), 400.0)

    def test_endorse_without_bills_is_vendor_advance(self):
        check, _inv = self._received_check(500.0)
        self._endorse(check)
        self.assertAlmostEqual(self._vendor_open_debit(check), 500.0)

    def test_installments_of_vendor_bill(self):
        split = self.env["account.payment.term"].create({
            "name": "50/50 vendor",
            "line_ids": [(0, 0, {"value": "percent", "value_amount": 50.0, "nb_days": 0}),
                         (0, 0, {"value": "percent", "value_amount": 50.0, "nb_days": 30})],
        })
        vendor = self.env["res.partner"].create({"name": "Split Vendor", "property_supplier_payment_term_id": split.id})
        bill = self._bill(1000.0, partner=vendor)
        check, _inv = self._received_check(700.0)
        self._endorse(check, vendor=vendor, bills=[(bill, 700.0)])
        self.assertAlmostEqual(bill.amount_residual, 300.0)
        self.assertEqual(sorted(check.endorsement_line_ids.mapped("amount")), [200.0, 500.0])

    def test_endorsement_wizard_lists_only_endorsee_bills(self):
        check, _inv = self._received_check(500.0)
        bill = self._bill(300.0)
        self._bill(200.0, partner=self.other_vendor)
        self._invoice(100.0, partner=self.vendor)
        wizard = self.env["check.endorsement.wizard"].with_context(default_check_id=check.id).create({
            "partner_id": self.vendor.id,
        })
        wizard._onchange_partner_id()
        self.assertEqual(wizard.line_ids.mapped("document_name"), [bill.name])

    def test_endorsement_wizard_through_form(self):
        """The bill lines are created by an onchange: they must survive the web client save."""
        check, _inv = self._received_check(1000.0)
        bill = self._bill(700.0)
        model = self.env["check.endorsement.wizard"].with_user(self.check_treasury)
        with Form(model.with_context(default_check_id=check.id)) as form:
            form.partner_id = self.vendor
            with form.line_ids.edit(0) as line:
                line.selected = True
                self.assertAlmostEqual(line.amount, 700.0)
            wizard = form.save()
        self.assertEqual(wizard.line_ids.document_name, bill.name)
        wizard.action_confirm()
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))

    def test_bills_cannot_exceed_check(self):
        check, _inv = self._received_check(1000.0)
        first, second = self._bill(800.0), self._bill(800.0)
        with self.assertRaises(UserError):
            self._endorse(check, bills=[(first, 800.0), (second, 800.0)])
        self.assertEqual(check.state, "received")

    def test_cannot_endorse_back_to_drawer(self):
        check, _inv = self._received_check(300.0)
        with self.assertRaises(UserError):
            self._endorse(check, vendor=self.customer)

    def test_only_received_payment_checks_can_be_endorsed(self):
        draft = self._create_incoming(check_number=self._next_number(), amount=100.0)
        with self.assertRaises(UserError):
            self._endorse(draft)
        deposited, _inv = self._received_check(100.0)
        self._deposit(deposited)
        with self.assertRaises(UserError):
            self._endorse(deposited)
        guarantee, _inv = self._received_check(100.0, allocate=False, purpose="guarantee")
        with self.assertRaises(UserError):
            self._endorse(guarantee)

    def test_endorse_with_settlement_at_collection(self):
        self.company.check_settlement_policy = "collection"
        check, invoice = self._received_check(800.0)
        self.assertFalse(check.payment_ids)
        bill = self._bill(800.0)
        self._endorse(check, bills=[(bill, 800.0)])
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))

    def test_endorsed_check_bounces_back(self):
        check, invoice = self._received_check(1000.0)
        bill = self._bill(1000.0)
        self._endorse(check, bills=[(bill, 1000.0)])
        self._bounce(check)
        self.assertEqual(check.state, "bounced")
        self.assertEqual(check.bounce_count, 1)
        self.assertAlmostEqual(invoice.amount_residual, 1000.0)
        self.assertAlmostEqual(bill.amount_residual, 1000.0)
        self.assertEqual(check.endorsement_line_ids.mapped("state"), ["reversed"])
        self._deposit(check)
        self.assertEqual(check.state, "under_collection")
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_endorsed_bounce_fee_not_allowed_without_bank(self):
        check, _inv = self._received_check(300.0)
        self._endorse(check)
        with self.assertRaises(UserError):
            self._bounce(check, fee=10.0)

    def test_returned_by_endorsee(self):
        check, invoice = self._received_check(600.0)
        bill = self._bill(600.0)
        self._endorse(check, bills=[(bill, 600.0)])
        with self.assertRaises(AccessError):
            self._wizard(check, "unendorse", user=self.check_treasury, reason="Not presented").action_confirm()
        self._wizard(check, "unendorse", user=self.check_manager, reason="Not presented").action_confirm()
        self.assertEqual(check.state, "received")
        self.assertFalse(check.endorsed_partner_id)
        self.assertAlmostEqual(bill.amount_residual, 600.0)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self._endorse(check, vendor=self.other_vendor)
        self.assertEqual(check.endorsed_partner_id, self.other_vendor)

    def test_endorsed_check_is_closed(self):
        check, _inv = self._received_check(200.0)
        self._endorse(check)
        check.action_archive()
        self.assertFalse(check.active)

    def test_treasury_without_accounting_rights_can_endorse(self):
        check, invoice = self._received_check(400.0)
        bill = self._bill(400.0)
        self._endorse(check, bills=[(bill, 400.0)], user=self.check_treasury)
        self.assertTrue(bill.currency_id.is_zero(bill.amount_residual))

    # ------------------------------------------------------------------
    # Guarantee checks
    # ------------------------------------------------------------------
    def test_guarantee_check_has_no_entries_and_expiry(self):
        past = self.today - timedelta(days=1)
        check, _inv = self._received_check(
            5000.0, allocate=False, purpose="guarantee",
            guarantee_expiry_date=past, guarantee_description="Tender 2026/14",
        )
        self.assertEqual(check.accounting_status, "not_applicable")
        self.assertTrue(check.is_guarantee_expired)
        found = self.env["check.check"].search([("is_guarantee_expired", "=", True), ("id", "=", check.id)])
        self.assertEqual(found, check)
        not_found = self.env["check.check"].search([("is_guarantee_expired", "=", False), ("id", "=", check.id)])
        self.assertFalse(not_found)

    def test_release_guarantee_requires_manager(self):
        check, _inv = self._received_check(5000.0, allocate=False, purpose="guarantee")
        with self.assertRaises(AccessError):
            self._wizard(check, "release", user=self.check_treasury, reason="Contract done", recipient="Client").action_confirm()
        self._wizard(check, "release", user=self.check_manager, reason="Contract done", recipient="Client").action_confirm()
        self.assertEqual(check.state, "returned")
        self.assertEqual(check.return_recipient, "Client")
        self.assertFalse(check.payment_ids)
        self.assertIn("released", check.event_ids.mapped("event_type"))

    def test_return_is_blocked_for_guarantee(self):
        check, _inv = self._received_check(5000.0, allocate=False, purpose="guarantee")
        with self.assertRaises(UserError):
            self._wizard(check, "return", reason="x", recipient="y").action_confirm()

    def test_release_is_only_for_guarantees(self):
        check, _inv = self._received_check(300.0)
        with self.assertRaises(UserError):
            self._wizard(check, "release", user=self.check_manager, reason="x", recipient="y").action_confirm()

    def test_invoke_guarantee_then_collect(self):
        check, _inv = self._received_check(2000.0, allocate=False, purpose="guarantee")
        self._wizard(check, "invoke", user=self.check_manager, reason="Customer defaulted").action_confirm()
        self.assertEqual(check.state, "received")
        self.assertEqual(check.purpose, "payment")
        self.assertEqual(check.accounting_status, "posted")
        self.assertAlmostEqual(check.payment_ids.amount, 2000.0)
        self.assertIn("invoked", check.event_ids.mapped("event_type"))
        self._deposit(check)
        self._collect(check)
        self.assertEqual(check.state, "collected")

    def test_outgoing_guarantee_release_and_invoke(self):
        released = self._create_outgoing(check_number=self._next_number(), amount=3000.0, purpose="guarantee")
        released.action_issue()
        self.assertEqual(released.accounting_status, "not_applicable")
        self._wizard(released, "deliver", recipient="Tender committee").action_confirm()
        with self.assertRaises(UserError):
            released._apply_clear(self.today)
        self._wizard(released, "release", user=self.check_manager, reason="Tender closed",
                     recipient="Our courier").action_confirm()
        self.assertEqual(released.state, "returned")

        invoked = self._create_outgoing(check_number=self._next_number(), amount=3000.0, purpose="guarantee")
        invoked.action_issue()
        self._wizard(invoked, "deliver", recipient="Landlord").action_confirm()
        self._wizard(invoked, "invoke", user=self.check_manager, reason="Penalty applied").action_confirm()
        self.assertEqual(invoked.purpose, "payment")
        self.assertEqual(invoked.accounting_status, "posted")
        self._bank_match(invoked._open_holding_lines())
        self.assertEqual(invoked.state, "cleared")
