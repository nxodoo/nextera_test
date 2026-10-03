from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .amount_to_words import amount_to_arabic, amount_to_english

POSITION_FIELDS = (
    "date_top", "date_left", "payee_top", "payee_left", "payee_width", "amount_top", "amount_left",
    "words_top", "words_left", "words_width", "crossing_top", "crossing_left",
)


class CheckPrintLayout(models.Model):
    _name = "check.print.layout"
    _description = "Check Print Layout"
    _order = "sequence, name"
    _check_company_auto = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    bank_id = fields.Many2one("res.bank", string="Bank")
    journal_ids = fields.Many2many(
        "account.journal", string="Used For", check_company=True, domain="[('type', '=', 'bank')]",
        help="Bank journals whose outgoing checks print with this layout.",
    )
    is_default = fields.Boolean(string="Company Default", help="Used for journals without a specific layout.")

    page_width = fields.Float(string="Check Width (mm)", default=175.0)
    page_height = fields.Float(string="Check Height (mm)", default=80.0)
    offset_x = fields.Float(string="Printer Offset Right (mm)", help="Shift everything right (negative: left).")
    offset_y = fields.Float(string="Printer Offset Down (mm)", help="Shift everything down (negative: up).")
    font_size = fields.Float(string="Font Size (pt)", default=11.0)
    date_format = fields.Char(default="%d/%m/%Y", required=True)
    words_language = fields.Selection(
        selection=[("ar", "Arabic"), ("en", "English")], string="Amount in Words", default="ar", required=True,
    )

    date_top = fields.Float(default=8.0)
    date_left = fields.Float(default=132.0)
    payee_top = fields.Float(default=22.0)
    payee_left = fields.Float(default=22.0)
    payee_width = fields.Float(default=110.0)
    amount_top = fields.Float(default=22.0)
    amount_left = fields.Float(default=138.0)
    words_top = fields.Float(default=33.0)
    words_left = fields.Float(default=22.0)
    words_width = fields.Float(default=145.0)
    print_crossing = fields.Boolean(string="Print Crossing")
    crossing_text = fields.Char(default="للمستفيد الأول")
    crossing_top = fields.Float(default=4.0)
    crossing_left = fields.Float(default=6.0)

    paperformat_id = fields.Many2one("report.paperformat", readonly=True, copy=False, ondelete="set null")

    @api.constrains(*POSITION_FIELDS, "page_width", "page_height", "font_size")
    def _check_dimensions(self):
        for layout in self:
            if layout.page_width <= 0 or layout.page_height <= 0 or layout.font_size <= 0:
                raise ValidationError(_("Layout %s: size and font must be positive.", layout.name))
            if any(layout[name] < 0 for name in POSITION_FIELDS):
                raise ValidationError(_("Layout %s: positions cannot be negative.", layout.name))

    @api.constrains("is_default", "company_id")
    def _check_single_default(self):
        for layout in self.filtered("is_default"):
            if self.search_count([("id", "!=", layout.id), ("company_id", "=", layout.company_id.id),
                                  ("is_default", "=", True)], limit=1):
                raise ValidationError(_("Only one default check layout per company."))

    @api.model_create_multi
    def create(self, vals_list):
        layouts = super().create(vals_list)
        layouts._sync_paperformat()
        return layouts

    def write(self, vals):
        result = super().write(vals)
        if {"page_width", "page_height", "name"}.intersection(vals):
            self._sync_paperformat()
        return result

    def _sync_paperformat(self):
        Paperformat = self.env["report.paperformat"].sudo()
        for layout in self:
            vals = {
                "name": _("Check: %s", layout.name),
                "format": "custom",
                "page_width": round(layout.page_width),
                "page_height": round(layout.page_height),
                "orientation": "Portrait",
                "margin_top": 0, "margin_bottom": 0, "margin_left": 0, "margin_right": 0,
                "header_line": False, "header_spacing": 0, "dpi": 96, "disable_shrinking": True,
            }
            if layout.paperformat_id:
                layout.paperformat_id.sudo().write(vals)
            else:
                layout.sudo().paperformat_id = Paperformat.create(vals)

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------
    def _style(self, top, left, width=None, extra=""):
        self.ensure_one()
        style = (f"position:absolute;top:{top + self.offset_y:.2f}mm;left:{left + self.offset_x:.2f}mm;"
                 f"font-size:{self.font_size:.1f}pt;white-space:nowrap;")
        if width:
            style += f"width:{width:.2f}mm;white-space:normal;"
        return style + extra

    def _amount_words(self, amount, currency):
        self.ensure_one()
        if self.words_language == "en":
            return amount_to_english(amount, currency)
        return amount_to_arabic(amount, currency)

    @api.model
    def _amount_figures(self, amount, currency):
        return f"#{amount:,.{currency.decimal_places}f}#"

    @api.model
    def _for_journal(self, journal):
        layout = self.search([("journal_ids", "in", journal.ids)], limit=1)
        return layout or self.search([("company_id", "=", journal.company_id.id), ("is_default", "=", True)], limit=1)

    def action_print_test(self):
        self.ensure_one()
        report = self.env.ref("sa_check_management_print.action_report_check_layout_test")
        return report.with_context(sa_check_layout_id=self.id).report_action(self)
