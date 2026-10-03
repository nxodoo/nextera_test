from odoo import models

CHECK_LAYOUT_REPORTS = (
    "sa_check_management_print.report_check_print",
    "sa_check_management_print.report_check_layout_test",
)


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def get_paperformat(self):
        """Check reports use the paper size of the layout they are printed with."""
        layout_id = self.env.context.get("sa_check_layout_id")
        if layout_id and self.report_name in CHECK_LAYOUT_REPORTS:
            layout = self.env["check.print.layout"].sudo().browse(layout_id).exists()
            if layout.paperformat_id:
                return layout.paperformat_id
        return super().get_paperformat()
