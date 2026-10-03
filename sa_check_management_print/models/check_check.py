from odoo import _, api, fields, models
from odoo.exceptions import UserError

GROUP_TREASURY = "sa_check_management.group_check_treasury"
GROUP_MANAGER = "sa_check_management.group_check_manager"
PRINTABLE_STATES = frozenset({"approved", "issued"})


class CheckEvent(models.Model):
    _inherit = "check.event"

    event_type = fields.Selection(selection_add=[("printed", "Printed")], ondelete={"printed": "cascade"})


class CheckCheck(models.Model):
    _inherit = "check.check"

    print_count = fields.Integer(string="Times Printed", readonly=True, copy=False)
    last_printed_date = fields.Datetime(readonly=True, copy=False)
    amount_in_words = fields.Char(compute="_compute_amount_in_words")

    @api.depends("amount", "currency_id", "journal_id")
    def _compute_amount_in_words(self):
        for check in self:
            layout = check._print_layout() if check.journal_id else self.env["check.print.layout"]
            if layout and check.amount:
                check.amount_in_words = layout._amount_words(check.amount, check.currency_id)
            else:
                check.amount_in_words = False

    def _print_layout(self):
        self.ensure_one()
        return self.env["check.print.layout"].sudo()._for_journal(self.journal_id)

    def action_print_check(self):
        self.ensure_one()
        self._validate_printable()
        layout = self._print_layout()
        reprint = bool(self.print_count)
        self.sudo().write({"print_count": self.print_count + 1, "last_printed_date": fields.Datetime.now()})
        self._log_event("printed", note=_("Reprinted (copy %s)", self.print_count) if reprint
                        else _("Printed with layout %s", layout.name))
        report = self.env.ref("sa_check_management_print.action_report_check_print")
        return report.with_context(sa_check_layout_id=layout.id).report_action(self)

    def _validate_printable(self):
        self.ensure_one()
        if self.env.su:
            return
        if not self.env.user.has_group(GROUP_TREASURY):
            raise UserError(_("Only Treasury Officers can print checks."))
        if self.check_type != "outgoing":
            raise UserError(_("Only outgoing checks can be printed."))
        ready = self.state in PRINTABLE_STATES or (self.state == "draft" and not self.approval_required)
        if not ready:
            raise UserError(_("Check %(check)s must be approved before printing.", check=self.display_name))
        if not self.check_number or not self.journal_id:
            raise UserError(_("Set the bank journal and check number before printing."))
        if not self._print_layout():
            raise UserError(_("No check layout is configured for %(journal)s.", journal=self.journal_id.display_name))
        if self.print_count and not self.env.user.has_group(GROUP_MANAGER):
            raise UserError(_("Check %(check)s was already printed; only a Check Manager can reprint it.",
                              check=self.display_name))


class ReportCheckPrint(models.AbstractModel):
    _name = "report.sa_check_management_print.report_check_print"
    _description = "Printed Check"

    @api.model
    def _get_report_values(self, docids, data=None):
        checks = self.env["check.check"].browse(docids)
        forced = self.env["check.print.layout"].browse(self.env.context.get("sa_check_layout_id")).exists()
        rows = []
        for check in checks:
            layout = forced or check._print_layout()
            if not layout:
                raise UserError(_("No check layout is configured for %(journal)s.", journal=check.journal_id.display_name))
            rows.append({
                "check": check,
                "layout": layout,
                "date": (check.due_date or check.issue_date).strftime(layout.date_format),
                "payee": check.partner_id.name,
                "figures": layout._amount_figures(check.amount, check.currency_id),
                "words": layout._amount_words(check.amount, check.currency_id),
            })
        return {"docs": checks, "rows": rows}


class ReportCheckLayoutTest(models.AbstractModel):
    _name = "report.sa_check_management_print.report_check_layout_test"
    _description = "Check Layout Test Page"

    @api.model
    def _get_report_values(self, docids, data=None):
        layouts = self.env["check.print.layout"].browse(docids)
        currency = self.env.company.currency_id
        sample = 250000.0
        return {
            "docs": layouts,
            "rows": [{
                "layout": layout,
                "date": fields.Date.context_today(self).strftime(layout.date_format),
                "payee": _("Beneficiary Name Sample Co."),
                "figures": layout._amount_figures(sample, currency),
                "words": layout._amount_words(sample, currency),
            } for layout in layouts],
        }
