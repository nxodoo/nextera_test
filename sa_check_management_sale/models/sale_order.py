from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang

GROUP_MANAGER = "sa_check_management.group_check_manager"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    sa_check_warning = fields.Text(compute="_compute_sa_check_warning")

    @api.depends("partner_id", "company_id")
    def _compute_sa_check_warning(self):
        for order in self:
            order.sa_check_warning = order._sa_check_bounce_message()

    def _sa_check_bounce_message(self):
        self.ensure_one()
        if not self.partner_id or self.company_id.check_sale_bounce_policy == "none":
            return ""
        count, amount = self.partner_id.commercial_partner_id._sa_check_bounced(self.company_id)
        if not count:
            return ""
        return _(
            "%(partner)s has %(count)s bounced check(s) not yet resolved, total %(amount)s.",
            partner=self.partner_id.commercial_partner_id.name, count=count,
            amount=formatLang(self.env, amount, currency_obj=self.company_id.currency_id),
        )

    def action_confirm(self):
        self._sa_check_enforce_bounce_policy()
        return super().action_confirm()

    def _sa_check_enforce_bounce_policy(self):
        if self.env.su or self.env.user.has_group(GROUP_MANAGER):
            return
        for order in self.filtered(lambda o: o.company_id.check_sale_bounce_policy == "block"):
            message = order._sa_check_bounce_message()
            if message:
                raise UserError(message + "\n" + _("A Check Manager must confirm this order."))
