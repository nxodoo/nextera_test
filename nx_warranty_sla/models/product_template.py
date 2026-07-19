from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    has_warranty = fields.Boolean(
        string="Has Warranty",
        default=False,
    )
    warranty_certain_period = fields.Boolean(
        string="Certain Period",
        help="When enabled for service products, sale order lines must define warranty start and end dates.",
    )
    warranty_template_ids = fields.Many2many(
        "warranty.template",
        "product_warranty_template_rel",
        "product_tmpl_id",
        "warranty_template_id",
        string="Warranty Templates",
        help="Templates used to create warranty contracts when a sale order is confirmed.",
    )

    @api.constrains("has_warranty", "warranty_template_ids")
    def _check_has_warranty_templates(self):
        for rec in self:
            if rec.has_warranty and not rec.warranty_template_ids:
                raise ValidationError(_("At least one Warranty Template is required when Has Warranty is enabled."))

    @api.constrains("warranty_certain_period", "type")
    def _check_warranty_certain_period_service_only(self):
        for rec in self:
            if rec.warranty_certain_period and rec.type != "service":
                raise ValidationError(_("Certain Period can only be enabled for service products."))
