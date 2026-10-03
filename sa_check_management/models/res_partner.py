from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    sa_check_count = fields.Integer(
        string="Checks", compute="_compute_sa_check_count", groups="sa_check_management.group_check_user",
    )

    @api.depends_context("company")
    def _compute_sa_check_count(self):
        Check = self.env["check.check"].sudo()
        for partner in self:
            partner.sa_check_count = Check.search_count([
                ("company_id", "=", self.env.company.id),
                ("partner_id", "child_of", partner.commercial_partner_id.id),
                ("state", "not in", ("draft", "cancelled")),
            ])

    def action_view_partner_checks(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Checks of %s", self.commercial_partner_id.display_name),
            "res_model": "check.check",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("partner_id", "child_of", self.commercial_partner_id.id)],
            "context": {"create": False, "search_default_group_type": 1},
        }

    def action_open_check_statement(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Check Statement"),
            "res_model": "check.partner.statement.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_partner_id": self.commercial_partner_id.id},
        }
