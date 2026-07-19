from odoo import api, fields, models


class HelpdeskTeam(models.Model):
    _inherit = "helpdesk.team"

    is_default_contactus_team = fields.Boolean(
        string="Default Contact Us Team",
        help="Website Contact Us requests will create helpdesk tickets in this team.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Keep only one default team flagged for website contact requests."""
        teams = super().create(vals_list)
        teams.filtered("is_default_contactus_team")._clear_other_contactus_defaults()
        return teams

    def write(self, vals):
        """Ensure the default Contact Us team flag stays unique."""
        result = super().write(vals)
        if vals.get("is_default_contactus_team"):
            self.filtered("is_default_contactus_team")._clear_other_contactus_defaults()
        return result

    def _clear_other_contactus_defaults(self):
        """Unset the Contact Us default flag on all teams except the current ones."""
        if not self:
            return
        other_teams = self.search([
            ("id", "not in", self.ids),
            ("is_default_contactus_team", "=", True),
        ])
        if other_teams:
            other_teams.write({"is_default_contactus_team": False})
