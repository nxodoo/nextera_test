from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.sa_check_management.tests.common import CheckAccountingCommon

from ..models.amount_to_words import amount_to_arabic, amount_to_english, number_to_arabic_words


@tagged("post_install", "-at_install", "sa_check_management_print")
class TestCheckPrint(CheckAccountingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.egp = cls.env.ref("base.EGP")
        cls.egp.active = True
        cls.layout = cls.env["check.print.layout"].create({
            "name": "Test Bank Layout", "journal_ids": [(6, 0, cls.bank_journal.ids)],
            "page_width": 180.0, "page_height": 82.0,
        })

    def _approved_outgoing(self, amount=250000.0, number="200001"):
        self.company.check_outgoing_approval_required = True
        check = self._create_outgoing(amount=amount, check_number=number)
        check.action_submit()
        check.with_user(self.check_approver).action_approve()
        return check

    # ------------------------------------------------------------------
    # Amount in words
    # ------------------------------------------------------------------
    def test_arabic_numbers(self):
        expected = {
            1: "واحد", 11: "أحد عشر", 21: "واحد وعشرون", 200: "مائتان", 1001: "ألف وواحد",
            2000: "ألفان", 3000: "ثلاثة آلاف", 12000: "اثنا عشر ألف", 200000: "مائتا ألف",
            250000: "مائتان وخمسون ألف", 2500000: "مليونان وخمسمائة ألف", 3000000: "ثلاثة ملايين",
        }
        for number, words in expected.items():
            self.assertEqual(number_to_arabic_words(number), words, number)

    def test_arabic_amount_with_currency(self):
        self.assertEqual(amount_to_arabic(250000, self.egp), "فقط مائتان وخمسون ألف جنيه مصري لا غير")
        self.assertEqual(
            amount_to_arabic(1250.25, self.egp),
            "فقط ألف ومائتان وخمسون جنيه مصري وخمسة وعشرون قرشاً لا غير",
        )

    def test_english_amount(self):
        self.assertEqual(
            amount_to_english(1250.25, self.egp),
            "One Thousand Two Hundred And Fifty Egyptian Pounds and Twenty-Five Piasters Only",
        )

    # ------------------------------------------------------------------
    # Layouts
    # ------------------------------------------------------------------
    def test_layout_owns_its_paper_format(self):
        paper = self.layout.paperformat_id
        self.assertEqual((paper.format, paper.page_width, paper.page_height), ("custom", 180, 82))
        self.layout.page_height = 90.0
        self.assertEqual(paper.page_height, 90)

    def test_one_default_layout_per_company(self):
        self.env["check.print.layout"].search([("is_default", "=", True)]).is_default = False
        self.env["check.print.layout"].create({"name": "Default A", "is_default": True})
        with self.assertRaises(ValidationError):
            self.env["check.print.layout"].create({"name": "Default B", "is_default": True})

    def test_journal_layout_then_company_default(self):
        self.assertEqual(self.env["check.print.layout"]._for_journal(self.bank_journal), self.layout)
        other_journal = self.company_data["default_journal_bank"].copy({"name": "Other Bank", "code": "OTB"})
        default = self.env["check.print.layout"].search([("is_default", "=", True)], limit=1)
        self.assertEqual(self.env["check.print.layout"]._for_journal(other_journal), default)

    def test_report_uses_layout_paper_format(self):
        report = self.env.ref("sa_check_management_print.action_report_check_print")
        self.assertEqual(report.with_context(sa_check_layout_id=self.layout.id).get_paperformat(),
                         self.layout.paperformat_id)
        self.assertNotEqual(report.get_paperformat(), self.layout.paperformat_id)

    def test_layout_test_page_renders(self):
        html, _fmt = self.env["ir.actions.report"].with_context(sa_check_layout_id=self.layout.id)._render_qweb_html(
            "sa_check_management_print.report_check_layout_test", self.layout.ids,
        )
        self.assertIn("180.0mm", html.decode())

    # ------------------------------------------------------------------
    # Printing a check
    # ------------------------------------------------------------------
    def test_print_approved_check(self):
        check = self._approved_outgoing(250000.0)
        action = check.with_user(self.check_treasury).action_print_check()
        action = action.get("context", {}).get("report_action", action)  # companies without a logo get a dialog first
        self.assertEqual(action["report_name"], "sa_check_management_print.report_check_print")
        self.assertEqual(action["context"]["sa_check_layout_id"], self.layout.id)
        self.assertEqual(check.print_count, 1)
        self.assertIn("printed", check.event_ids.mapped("event_type"))
        html, _fmt = self.env["ir.actions.report"].with_context(sa_check_layout_id=self.layout.id)._render_qweb_html(
            "sa_check_management_print.report_check_print", check.ids,
        )
        html = html.decode()
        self.assertIn("#250,000.00#", html)
        self.assertIn(check.partner_id.name, html)
        self.assertIn(check.due_date.strftime("%d/%m/%Y"), html)

    def test_reprint_requires_manager(self):
        check = self._approved_outgoing()
        check.with_user(self.check_treasury).action_print_check()
        with self.assertRaises(UserError):
            check.with_user(self.check_treasury).action_print_check()
        check.with_user(self.check_manager).action_print_check()
        self.assertEqual(check.print_count, 2)

    def test_print_rules(self):
        self.company.check_outgoing_approval_required = True
        pending = self._create_outgoing(check_number="300001")
        pending.action_submit()
        with self.assertRaises(UserError):
            pending.with_user(self.check_treasury).action_print_check()
        incoming = self._create_incoming()
        with self.assertRaises(UserError):
            incoming.with_user(self.check_treasury).action_print_check()
        approved = self._approved_outgoing(number="300002")
        with self.assertRaises(UserError):
            approved.with_user(self.check_user).action_print_check()

    def test_amount_in_words_on_form(self):
        check = self._create_outgoing(amount=2000.0)
        self.assertTrue(check.amount_in_words.startswith("فقط ألفان"))
