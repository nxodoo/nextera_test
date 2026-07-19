# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PortalSidebarGroup(models.Model):
    _name = 'portal.sidebar.group'
    _description = 'Portal Sidebar Group'
    _order = 'sequence, id'

    name = fields.Char(string='Group Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    item_ids = fields.One2many(
        'portal.sidebar.item', 'group_id', string='Items',
    )

    def _clear_sidebar_cache(self):
        """Clear the QWeb view cache so portal pages reflect sidebar changes."""
        self.env.registry.clear_cache('default', 'templates')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._clear_sidebar_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._clear_sidebar_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self._clear_sidebar_cache()
        return res

