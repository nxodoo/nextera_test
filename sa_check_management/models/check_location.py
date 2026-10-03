from odoo import fields, models


class CheckLocation(models.Model):
    _name = "check.location"
    _description = "Check Custody Location"
    _order = "name"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    location_type = fields.Selection(
        selection=[
            ("safe", "Safe"),
            ("branch", "Branch"),
            ("bank", "Bank"),
            ("person", "Person"),
            ("other", "Other"),
        ],
        required=True, default="safe",
    )
    user_id = fields.Many2one("res.users", string="Responsible Person")
    journal_id = fields.Many2one(
        "account.journal", string="Bank Journal", check_company=True,
        domain="[('type', '=', 'bank')]",
    )
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    note = fields.Text()
