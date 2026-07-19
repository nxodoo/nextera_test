from odoo import _, fields, models


class ResourceCalendarLeaves(models.Model):
    _inherit = "resource.calendar.leaves"

    holiday_greeting_template_id = fields.Many2one(
        "hr.holiday.greeting.template",
        string="Holiday Greeting Template",
        domain="[('active', '=', True), '|', ('company_id', '=', company_id), ('company_id', '=', False)]",
        help="Greeting email template that should be sent automatically for this public holiday.",
    )

    def action_view_greeting_logs(self):
        """Open a popup listing all greeting logs sent for this public holiday."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Greeting Logs: %s") % (self.name or ""),
            "res_model": "hr.holiday.greeting.log",
            "view_mode": "list",
            "domain": [("holiday_id", "=", self.id)],
            "target": "new",
            "context": {"create": False, "delete": False},
        }
