# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class CustodyProductLine(models.Model):
    """A single product (lot/serial) held under an employee product custody."""

    _name = "custody.product.line"
    _description = "Custody Product Line"

    custody_id = fields.Many2one(
        'custody.request',
        string="Custody Request",
        required=True,
        ondelete='cascade',
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='custody_id.company_currency_id',
        string="Currency",
    )

    product_id = fields.Many2one(
        'product.product',
        string="Product",
        required=True,
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string="Lot / Serial Number",
        domain="[('product_id', '=', product_id)]",
    )
    available_qty = fields.Float(
        string="Available Qty",
        compute="_compute_available_qty",
    )
    quantity = fields.Float(string="Quantity", default=1.0)
    uom_id = fields.Many2one(
        'uom.uom',
        string="UoM",
        related='product_id.uom_id',
        readonly=True,
    )
    expiry_date = fields.Date(
        string="Expiry Date",
        compute="_compute_expiry",
        store=True,
        readonly=False,
    )
    is_expired = fields.Boolean(
        string="Expired",
        compute="_compute_remaining_period",
    )
    remaining_period = fields.Char(
        string="Remaining Expiry Period",
        compute="_compute_remaining_period",
    )
    unit_cost = fields.Monetary(
        string="Unit Cost",
        compute="_compute_unit_cost",
        store=True,
        readonly=False,
        currency_field='company_currency_id',
    )
    total_value = fields.Monetary(
        string="Total Value",
        compute="_compute_total_value",
        currency_field='company_currency_id',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('returned', 'Returned'),
    ], string="Status", default='draft')

    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    @api.depends('lot_id', 'product_id')
    def _compute_available_qty(self):
        for line in self:
            if line.lot_id:
                line.available_qty = line.lot_id.product_qty
            elif line.product_id:
                line.available_qty = line.product_id.qty_available
            else:
                line.available_qty = 0.0

    @api.depends('lot_id')
    def _compute_expiry(self):
        for line in self:
            if line.lot_id and line.lot_id.expiration_date:
                line.expiry_date = fields.Date.to_date(line.lot_id.expiration_date)
            else:
                line.expiry_date = line.expiry_date or False

    @api.depends('expiry_date')
    def _compute_remaining_period(self):
        today = fields.Date.context_today(self)
        for line in self:
            if not line.expiry_date:
                line.is_expired = False
                line.remaining_period = _("No expiry")
                continue
            delta = (line.expiry_date - today).days
            if delta < 0:
                line.is_expired = True
                line.remaining_period = _("Expired")
            else:
                line.is_expired = False
                years, days = divmod(delta, 365)
                if years >= 1:
                    line.remaining_period = _("%s year(s) remaining") % years
                else:
                    line.remaining_period = _("%s day(s) remaining") % days

    @api.depends('product_id')
    def _compute_unit_cost(self):
        for line in self:
            line.unit_cost = line.product_id.standard_price if line.product_id else 0.0

    @api.depends('quantity', 'unit_cost')
    def _compute_total_value(self):
        for line in self:
            line.total_value = line.quantity * line.unit_cost
