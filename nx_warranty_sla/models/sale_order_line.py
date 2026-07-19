from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    product_has_warranty = fields.Boolean(
        related="product_id.has_warranty",
        readonly=True,
    )
    available_warranty_template_ids = fields.Many2many(
        related="product_id.warranty_template_ids",
        readonly=True,
    )
    warranty_template_id = fields.Many2one(
        "warranty.template",
        string="Warranty Template",
        domain="[('id', 'in', available_warranty_template_ids)]",
    )
    warranty_certain_period = fields.Boolean(
        related="product_id.warranty_certain_period",
        readonly=True,
    )
    warranty_start_date = fields.Date(string="Start Date")
    warranty_end_date = fields.Date(string="End Date")
    warranty_duration_months = fields.Integer(string="Duration")

    def _get_primary_warranty_template(self):
        self.ensure_one()
        if self.warranty_template_id:
            return self.warranty_template_id
        templates = self.product_id.warranty_template_ids.filtered(
            lambda t: t.duration_type in ("months", "fixed_dates")
        )
        return templates[:1]

    @api.onchange("product_id")
    def _onchange_product_set_warranty_dates(self):
        for line in self:
            if not line.product_id or not line.product_id.has_warranty:
                line.warranty_template_id = False
                line.warranty_start_date = False
                line.warranty_end_date = False
                line.warranty_duration_months = 0
                continue

            if line.warranty_template_id not in line.product_id.warranty_template_ids:
                line.warranty_template_id = line.product_id.warranty_template_ids[:1]

            template = line._get_primary_warranty_template()
            if not template:
                line.warranty_template_id = False
                line.warranty_start_date = False
                line.warranty_end_date = False
                line.warranty_duration_months = 0
                continue

            start_date = line.warranty_start_date or fields.Date.to_date(line.order_id.date_order) or fields.Date.context_today(line)
            line.warranty_start_date = start_date
            line.warranty_duration_months = max(template.duration_months or 0, 0)
            if line.warranty_duration_months > 0:
                line.warranty_end_date = start_date + relativedelta(months=line.warranty_duration_months)
            elif template.duration_type == "fixed_dates":
                line.warranty_end_date = line.warranty_end_date or False

    @api.onchange("warranty_template_id")
    def _onchange_warranty_template_id(self):
        for line in self:
            template = line._get_primary_warranty_template()
            if not template:
                line.warranty_duration_months = 0
                line.warranty_end_date = False
                continue

            line.warranty_duration_months = max(template.duration_months or 0, 0)
            if template.duration_type == "tickets_based":
                line.warranty_end_date = False
                continue

            start_date = line.warranty_start_date or fields.Date.to_date(line.order_id.date_order) or fields.Date.context_today(line)
            line.warranty_start_date = start_date
            if line.warranty_duration_months > 0:
                line.warranty_end_date = start_date + relativedelta(months=line.warranty_duration_months)

    @api.onchange("warranty_start_date", "warranty_duration_months")
    def _onchange_warranty_start_or_duration(self):
        for line in self:
            if line.warranty_start_date and line.warranty_duration_months > 0:
                line.warranty_end_date = line.warranty_start_date + relativedelta(months=line.warranty_duration_months)
            elif line.warranty_duration_months <= 0:
                line.warranty_end_date = False

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_warranty_contract_sync"):
            return res
        if "warranty_start_date" in vals or "warranty_end_date" in vals:
            self._sync_warranty_contract_dates()
        return res

    def _sync_warranty_contract_dates(self):
        """Keep linked warranty contracts aligned with manually edited SO line dates."""
        contracts = self.env["warranty.contract"].search([("sale_order_line_id", "in", self.ids)])
        for line in self:
            line_contracts = contracts.filtered(lambda contract: contract.sale_order_line_id == line)
            if not line_contracts:
                continue
            line_contracts.with_context(skip_sale_line_sync=True).write({
                "start_date": line.warranty_start_date,
                "end_date": line.warranty_end_date,
            })
