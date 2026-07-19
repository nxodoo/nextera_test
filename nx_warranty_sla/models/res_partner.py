from odoo import api, fields, models
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = "res.partner"

    nx_allowed_slide_channel_ids = fields.Many2many(
        "slide.channel",
        "nx_partner_slide_channel_rel",
        "partner_id",
        "channel_id",
        string="Allowed E-Learning Courses",
        help="Courses this contact is allowed to access in eLearning and in the portal.",
    )
    nx_allowed_slide_channel_count = fields.Integer(
        compute="_compute_nx_allowed_slide_channel_count",
        string="Allowed E-Learning Courses",
    )
    warranty_contract_ids = fields.Many2many(
        "warranty.contract",
        compute="_compute_warranty_contract_data",
        string="Warranties",
        readonly=True,
    )
    warranty_contract_count = fields.Integer(compute="_compute_warranty_contract_data")
    warranty_active_count = fields.Integer(compute="_compute_warranty_contract_data")
    warranty_expired_count = fields.Integer(compute="_compute_warranty_contract_data")
    linked_user_count = fields.Integer(compute="_compute_linked_user_count")
    portal_role = fields.Selection(
        selection=[
            ("user", "Portal User"),
            ("admin", "Portal Admin"),
        ],
        string="Portal Ticket Role",
        default="user",
        help="Portal User sees only their own tickets. Portal Admin sees all company tickets and orders.",
    )

    @api.depends("nx_allowed_slide_channel_ids")
    def _compute_nx_allowed_slide_channel_count(self):
        for partner in self:
            partner.nx_allowed_slide_channel_count = len(partner.nx_allowed_slide_channel_ids)

    def _compute_linked_user_count(self):
        user_data = self.env["res.users"].read_group(
            [("partner_id", "child_of", self.commercial_partner_id.ids)],
            ["partner_id"],
            ["partner_id"],
        )
        count_by_partner = {}
        for item in user_data:
            partner_id = item.get("partner_id")
            if not partner_id:
                continue
            partner = self.env["res.partner"].browse(partner_id[0]).commercial_partner_id
            count_by_partner[partner.id] = count_by_partner.get(partner.id, 0) + item["partner_id_count"]
        for partner in self:
            partner.linked_user_count = count_by_partner.get(partner.commercial_partner_id.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._sync_allowed_slide_channels()
        return partners

    def _compute_warranty_contract_data(self):
        WarrantyContract = self.env["warranty.contract"]
        for partner in self:
            domain = [("partner_id", "=", partner.commercial_partner_id.id)]
            contracts = WarrantyContract.search(domain)
            partner.warranty_contract_ids = contracts
            partner.warranty_contract_count = len(contracts)
            partner.warranty_active_count = len(contracts.filtered(lambda c: c.state == "active"))
            partner.warranty_expired_count = len(contracts.filtered(lambda c: c.state == "expired"))

    def write(self, vals):
        res = super().write(vals)
        if "nx_allowed_slide_channel_ids" in vals:
            self._sync_allowed_slide_channels()
        return res

    def _sync_allowed_slide_channels(self):
        """Keep course membership aligned with the contact-course assignment."""
        membership_model = self.env["slide.channel.partner"].sudo().with_context(active_test=False)
        for partner in self:
            assigned_channels = partner.nx_allowed_slide_channel_ids.sudo()
            if assigned_channels:
                assigned_channels.write({
                    "visibility": "members",
                    "enroll": "invite",
                })
                assigned_channels._action_add_members(partner)

            current_memberships = membership_model.search([("partner_id", "=", partner.id)])
            channels_to_remove = current_memberships.mapped("channel_id") - assigned_channels
            if channels_to_remove:
                channels_to_remove._remove_membership(partner.ids)

    def action_view_warranty_contracts(self):
        self.ensure_one()
        if not (
            self.env.user.has_group("nx_warranty_sla.group_warranty_access")
            or self.env.user.has_group("base.group_system")
            or self.env.user.has_group("sales_team.group_sale_salesman")
        ):
            raise AccessError("You are not allowed to open Warranty Contracts. Please ask your administrator to grant Warranty Access.")
        action = self.env.ref("nx_warranty_sla.action_warranty_contract").read()[0]
        action["domain"] = [("partner_id", "=", self.commercial_partner_id.id)]
        action["context"] = {
            "default_partner_id": self.commercial_partner_id.id,
        }
        return action

    def action_view_linked_users(self):
        self.ensure_one()
        action = self.env.ref("base.action_res_users").read()[0]
        action["domain"] = [("partner_id", "child_of", self.commercial_partner_id.id)]
        action["context"] = {
            **self.env.context,
            "default_partner_id": self.id,
            "search_default_filter_no_share": 0,
        }
        return action
