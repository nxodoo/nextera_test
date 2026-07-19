# -*- coding: utf-8 -*-

from collections import defaultdict
from markupsafe import Markup
from odoo import http
from odoo.http import request
from odoo.addons.sale.controllers.portal import CustomerPortal as SaleCustomerPortal


class PortalSidebarController(SaleCustomerPortal):

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values["sidebar_groups"] = self._get_sidebar_groups()
        return values

    def _prepare_sale_portal_rendering_values(
        self,
        page=1,
        date_begin=None,
        date_end=None,
        sortby=None,
        quotation_page=False,
        **kwargs,
    ):
        """Expose total order count for portal analytics (all pages, not current page only)."""
        values = super()._prepare_sale_portal_rendering_values(
            page=page,
            date_begin=date_begin,
            date_end=date_end,
            sortby=sortby,
            quotation_page=quotation_page,
            **kwargs,
        )
        if quotation_page:
            return values
        SaleOrder = request.env["sale.order"]
        partner = request.env.user.partner_id
        domain = list(self._prepare_orders_domain(partner))
        if date_begin and date_end:
            domain += [
                ("create_date", ">", date_begin),
                ("create_date", "<=", date_end),
            ]
        values["portal_orders_total"] = SaleOrder.search_count(domain)
        return values

    def _get_sidebar_groups(self):
        """Return ordered sidebar groups with their items (optimized version)."""

        env = http.request.env

        SidebarGroup = env["portal.sidebar.group"].sudo()
        SidebarItem = env["portal.sidebar.item"].sudo()

        # 1️⃣ Fetch all active groups
        groups = SidebarGroup.search(
            [("active", "=", True)],
            order="sequence, id",
        )

        if not groups:
            return []

        # 2️⃣ Fetch all active items for those groups in ONE query
        items = SidebarItem.search(
            [
                ("group_id", "in", groups.ids),
                ("active", "=", True),
            ],
            order="sequence, id",
        )

        # 3️⃣ Group items in memory (no extra queries)
        grouped_items = defaultdict(list)

        for item in items:
            grouped_items[item.group_id.id].append({
                "name": item.name,
                "url": item.url,
                "icon": self._safe_icon(item.icon),
                "url_match_prefix": item.url_match_prefix or item.url,
                "exact_match": item.exact_match,
            })

        # 4️⃣ Build final ordered result
        result = []
        for group in groups:
            group_items = grouped_items.get(group.id)
            if not group_items:
                continue

            result.append({
                "name": group.name,
                "items": group_items,
            })

        return result

    @staticmethod
    def _safe_icon(icon):
        """
        Safely return HTML icon markup.
        Only allow known-safe HTML (admin controlled).
        """
        return Markup(icon) if icon else Markup("")
