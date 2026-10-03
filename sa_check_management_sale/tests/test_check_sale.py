from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sa_check_management.tests.common import CheckBankingCommon


@tagged("post_install", "-at_install", "sa_check_management_sale")
class TestCheckSale(CheckBankingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.account_use_credit_limit = True
        cls.customer.credit_limit = 1000.0
        cls.env.user.groups_id |= cls.env.ref("sales_team.group_sale_salesman")

    def _order(self, amount, user=None):
        model = self.env["sale.order"]
        if user:
            model = model.with_user(user)
        return model.create({
            "partner_id": self.customer.id,
            "order_line": [(0, 0, {"product_id": self.product_a.id, "product_uom_qty": 1,
                                   "price_unit": amount, "tax_id": [(6, 0, [])]})],
        })

    def test_open_checks_count_in_credit_limit(self):
        check, invoice = self._received_check(800.0)
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual), "Check settled the invoice")
        order = self._order(300.0)
        self.assertIn("credit limit", order.partner_credit_warning)
        self.assertIn("not collected yet", order.partner_credit_warning)
        self.company.check_sale_credit_include_checks = False
        order.invalidate_recordset(["partner_credit_warning"])
        self.assertFalse(order.partner_credit_warning)

    def test_collected_checks_leave_the_exposure(self):
        check, _inv = self._received_check(800.0)
        self._deposit(check)
        self._collect(check)
        self.assertAlmostEqual(self.customer._sa_check_open_settled_amount(self.company), 0.0)
        self.assertFalse(self._order(300.0).partner_credit_warning)

    def test_bounced_checks_warn_on_sales_orders(self):
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        self._bounce(check)
        order = self._order(100.0)
        self.assertIn("1 bounced check", order.sa_check_warning)
        self.env["check.legal.wizard"].with_context(default_check_id=check.id).create({
            "case_number": "C-9",
        }).action_confirm()
        order.invalidate_recordset(["sa_check_warning"])
        self.assertIn("1 bounced check", order.sa_check_warning, "Legal cases still count")
        self.company.check_sale_bounce_policy = "none"
        order.invalidate_recordset(["sa_check_warning"])
        self.assertFalse(order.sa_check_warning)

    def test_block_policy_needs_check_manager(self):
        self.company.check_sale_bounce_policy = "block"
        check, _inv = self._received_check(500.0)
        self._deposit(check)
        self._bounce(check)
        salesman = self._new_check_user("sale_rep_check", "group_check_user")
        salesman.groups_id |= self.env.ref("sales_team.group_sale_salesman")
        order = self._order(100.0, user=salesman)
        with self.assertRaises(UserError):
            order.with_user(salesman).action_confirm()
        order.with_env(self.env).action_confirm()  # the test user is a Check Manager
        self.assertEqual(order.state, "sale")

    def test_partner_open_check_counter(self):
        self._received_check(200.0)
        self._received_check(300.0)
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.sa_check_open_count, 2)
        self.assertAlmostEqual(self.customer.sa_check_open_amount, 500.0)
