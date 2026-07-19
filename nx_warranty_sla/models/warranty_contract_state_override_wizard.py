from odoo import api, fields, models


class WarrantyContractStateOverrideWizard(models.TransientModel):
    _name = "warranty.contract.state.override.wizard"
    _description = "Warranty Contract State Override Wizard"

    contract_id = fields.Many2one("warranty.contract", required=True, readonly=True)
    target_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("active", "Active"),
            ("need_to_be_extended", "Need To Be Extended"),
            ("not_extended", "Not Extended"),
            ("expired", "Expired"),
        ],
        required=True,
        readonly=True,
    )
    computed_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("active", "Active"),
            ("need_to_be_extended", "Need To Be Extended"),
            ("not_extended", "Not Extended"),
            ("expired", "Expired"),
        ],
        required=True,
        readonly=True,
    )
    message = fields.Text(readonly=True)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        contract = self.env["warranty.contract"].browse(self.env.context.get("default_contract_id"))
        target_state = self.env.context.get("default_target_state")
        computed_state = self.env.context.get("default_computed_state")
        if contract and target_state and computed_state and "message" in fields_list:
            defaults["message"] = (
                "This contract is being manually set to '%s', but based on its current dates and usage "
                "the automatic lifecycle will move it to '%s'. Do you want to keep the manual state anyway?"
            ) % (
                dict(self._fields["target_state"].selection).get(target_state, target_state),
                dict(self._fields["computed_state"].selection).get(computed_state, computed_state),
            )
        return defaults

    def action_confirm_override(self):
        self.ensure_one()
        self.contract_id.with_context(skip_auto_lifecycle_state=True).write({"state": self.target_state})
        return {"type": "ir.actions.act_window_close"}
