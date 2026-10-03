from odoo import _, fields, models
from odoo.exceptions import UserError

RUN_NOW_LIMIT = 300


class CheckDemoWizard(models.TransientModel):
    _name = "check.demo.wizard"
    _description = "Generate Check Demo Data"

    count = fields.Integer(string="Number of Checks", default=1000, required=True)
    incoming_share = fields.Integer(string="Incoming Checks (%)", default=65, required=True)
    months_back = fields.Integer(string="History (Months)", default=12, required=True)
    months_ahead = fields.Integer(string="Future Due Dates (Months)", default=6, required=True)
    seed = fields.Integer(string="Random Seed", default=1, help="The same seed gives the same data.")
    create_users = fields.Boolean(
        string="Create Demo Users", default=True,
        help="One user per check role (clerk, treasury, approver, manager, accountant, auditor, sales reps); "
             "every action in the history is done by the user of its role.",
    )
    user_password = fields.Char(string="Password for Demo Users", default="Demo@1234")

    def action_generate(self):
        self.ensure_one()
        self._validate()
        job = self.env["check.demo.job"].create({
            "requested": self.count, "incoming_share": self.incoming_share,
            "months_back": self.months_back, "months_ahead": self.months_ahead, "seed": self.seed,
            "create_users": self.create_users, "user_password": self.user_password,
        })
        if self.count <= RUN_NOW_LIMIT:
            job.run_now()
        return {
            "type": "ir.actions.act_window",
            "name": _("Demo Data Jobs"),
            "res_model": "check.demo.job",
            "res_id": job.id,
            "view_mode": "form",
        }

    def _validate(self):
        if self.count <= 0:
            raise UserError(_("Ask for at least one check."))
        if not 0 <= self.incoming_share <= 100:
            raise UserError(_("The incoming share is a percentage between 0 and 100."))
        if self.create_users and len(self.user_password or "") < 8:
            raise UserError(_("Use a password of at least 8 characters for the demo users."))
        if self.months_back < 2 or self.months_ahead < 1:
            raise UserError(_("Use at least 2 months of history and 1 month of future due dates."))
