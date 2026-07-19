from dateutil.relativedelta import relativedelta

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    warranty_contract_ids = fields.One2many("warranty.contract", "sale_order_id", string="Warranty Contracts")
    warranty_contract_count = fields.Integer(compute="_compute_warranty_contract_count")

    def _compute_warranty_contract_count(self):
        for order in self:
            order.warranty_contract_count = len(order.warranty_contract_ids)

    def action_confirm(self):
        self._validate_certain_period_lines()
        res = super().action_confirm()
        self._create_warranty_contracts_from_lines()
        return res

    def _validate_certain_period_lines(self):
        """Ensure certain-period warranty products have valid dates before confirmation."""
        for order in self:
            warranty_lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id and l.product_id.has_warranty
            )
            for line in warranty_lines.filtered(lambda l: not l.warranty_template_id):
                raise ValidationError(_("Please select a Warranty Template for each warranty product line."))
            for line in warranty_lines.filtered(lambda l: l.product_id.warranty_certain_period):
                if not line.warranty_start_date or not line.warranty_end_date:
                    raise ValidationError(_("Start Date and End Date are required when Certain Period is enabled."))
                if line.warranty_end_date < line.warranty_start_date:
                    raise ValidationError(_("End Date cannot be before Start Date."))

    def _create_warranty_contracts_from_lines(self):
        WarrantyContract = self.env["warranty.contract"]
        for order in self:
            partner = order.partner_id.commercial_partner_id
            confirmation_dt = (
                order.confirmation_date
                if "confirmation_date" in order._fields and order.confirmation_date
                else order.date_order
            )
            start_date = fields.Date.to_date(confirmation_dt) or fields.Date.context_today(order)
            for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id and l.product_uom_qty > 0):
                if not line.product_id.has_warranty:
                    continue

                templates = line.warranty_template_id or line.product_id.warranty_template_ids[:1]
                if not templates:
                    continue

                for template in templates:
                    exists = WarrantyContract.search_count([
                        ("sale_order_line_id", "=", line.id),
                        ("warranty_template_id", "=", template.id),
                    ])
                    if exists:
                        continue

                    line_start_date = line.warranty_start_date or start_date
                    end_date = False
                    if line.product_id.warranty_certain_period:
                        line_start_date = line.warranty_start_date
                        end_date = line.warranty_end_date
                    elif template.duration_type in ("months", "fixed_dates"):
                        # Priority: line End Date -> line Duration -> template Duration
                        # This keeps SO dates as-is when user manually sets End Date.
                        if line.warranty_end_date:
                            end_date = line.warranty_end_date
                        elif (line.warranty_duration_months or 0) > 0:
                            end_date = line_start_date + relativedelta(months=line.warranty_duration_months)
                        elif template.duration_months > 0:
                            end_date = line_start_date + relativedelta(months=template.duration_months)
                    elif template.duration_type == "tickets_based":
                        end_date = False

                    WarrantyContract.create({
                        "partner_id": partner.id,
                        "sale_order_id": order.id,
                        "sale_order_line_id": line.id,
                        "product_id": line.product_id.id,
                        "warranty_template_id": template.id,
                        "start_date": line_start_date,
                        "end_date": end_date,
                        "state": "draft",
                    })

    def action_view_warranty_contracts(self):
        self.ensure_one()
        action = self.env.ref("nx_warranty_sla.action_warranty_contract").read()[0]
        action["domain"] = [("sale_order_id", "=", self.id)]
        action["context"] = {
            "default_sale_order_id": self.id,
            "default_partner_id": self.partner_id.commercial_partner_id.id,
        }
        return action
