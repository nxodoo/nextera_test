from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    has_warranty = fields.Boolean(
        related="product_tmpl_id.has_warranty",
        readonly=True,
    )
    warranty_certain_period = fields.Boolean(
        related="product_tmpl_id.warranty_certain_period",
        readonly=True,
    )
    warranty_template_ids = fields.Many2many(
        related="product_tmpl_id.warranty_template_ids",
        readonly=True,
    )
