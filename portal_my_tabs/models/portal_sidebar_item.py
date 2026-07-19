# -*- coding: utf-8 -*-

from markupsafe import Markup
from odoo import models, fields, api


class PortalSidebarItem(models.Model):
    _name = 'portal.sidebar.item'
    _description = 'Portal Sidebar Item'
    _order = 'sequence, id'

    name = fields.Char(string='Label', required=True, translate=True)
    url = fields.Char(string='URL', required=True)
    icon = fields.Text(
        string='SVG Icon',
        help='Paste a raw SVG element to display as the link icon.',
    )
    icon_preview = fields.Html(
        string='Icon Preview', compute='_compute_icon_preview',
        sanitize=False,
    )
    group_id = fields.Many2one(
        'portal.sidebar.group', string='Group',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    url_match_prefix = fields.Char(
        string='URL Match Prefix',
        help='Used for active-link highlighting. '
             'If empty, the URL field value is used.',
    )
    exact_match = fields.Boolean(
        string='Exact URL Match',
        default=False,
        help='If checked, the link is highlighted only when the current path '
             'exactly matches the URL (e.g. /my). Otherwise prefix matching is used.',
    )

    def _get_icon_markup(self):
        """Return the icon as a Markup object so QWeb renders it as raw HTML."""
        self.ensure_one()
        return Markup(self.icon) if self.icon else Markup('')

    @api.depends('icon')
    def _compute_icon_preview(self):
        for record in self:
            if record.icon:
                record.icon_preview = Markup(
                    '<div style="display:inline-flex;align-items:center;justify-content:center;'
                    'width:48px;height:48px;border-radius:8px;background:#f4f4f5;">'
                    '%s</div>'
                ) % Markup(record.icon)
            else:
                record.icon_preview = False

    @api.model
    def _get_sidebar_data(self):
        """Return sidebar structure as plain dicts for template rendering.
        Called from the QWeb template as a fallback when the controller
        has not already provided sidebar_groups in the render values.
        """
        groups = self.env['portal.sidebar.group'].sudo().search(
            [('active', '=', True)],
            order='sequence, id',
        )
        result = []
        for group in groups:
            items = self.sudo().search(
                [('group_id', '=', group.id), ('active', '=', True)],
                order='sequence, id',
            )
            if not items:
                continue
            result.append({
                'name': group.name,
                'items': [{
                    'name': item.name,
                    'url': item.url,
                    'icon': Markup(item.icon) if item.icon else Markup(''),
                    'url_match_prefix': item.url_match_prefix or item.url,
                    'exact_match': item.exact_match,
                } for item in items],
            })
        return result

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

    @api.onchange('url')
    def _onchange_url(self):
        if self.url and not self.url_match_prefix:
            self.url_match_prefix = self.url

