from odoo import http, tools
from odoo.addons.website.controllers.main import QueryURL
from odoo.addons.website_slides.controllers.main import (
    WebsiteSlides,
    handle_wslide_error,
)
from odoo.http import request


class NexteraWebsiteSlides(WebsiteSlides):
    def _is_restricted_portal_user(self):
        """Return whether the current user must be limited to assigned courses only."""
        user = request.env.user
        return user.has_group("base.group_portal") and not user.has_group("base.group_user")

    def _get_restricted_portal_channels(self):
        """Return website-published courses explicitly assigned to the current portal contact."""
        partner = request.env.user.partner_id.sudo()
        return partner.nx_allowed_slide_channel_ids.filtered("website_published")

    def _is_channel_allowed_for_portal_user(self, channel):
        """Return whether the current restricted portal user may access the given course."""
        return not self._is_restricted_portal_user() or channel in self._get_restricted_portal_channels()

    @http.route("/slides", type="http", auth="public", website=True, sitemap=True, readonly=True)
    def slides_channel_home(self, **post):
        if not self._is_restricted_portal_user():
            return super().slides_channel_home(**post)

        channels_all = self._get_restricted_portal_channels().sorted(
            lambda channel: (channel.sequence, channel.id)
        )
        render_values = self._slide_render_context_base()
        render_values.update(self._prepare_user_values(**post))
        render_values.update({
            "channels_my": channels_all,
            "channels_popular": request.env["slide.channel"],
            "channels_newest": request.env["slide.channel"],
            "achievements": request.env["gamification.badge.user"],
            "users": request.env["res.users"],
            "top3_users": tools.lazy(lambda: []),
            "challenges": None,
            "challenges_done": None,
            "search_tags": request.env["slide.channel.tag"],
            "slide_query_url": QueryURL("/slides/all", ["tag"]),
            "slugify_tags": self._slugify_tags,
        })
        return request.render("website_slides.courses_home", render_values)

    @http.route(
        ["/slides/all", "/slides/all/tag/<string:slug_tags>"],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
        readonly=True,
    )
    def slides_channel_all(self, slide_category=None, slug_tags=None, my=False, **post):
        return super().slides_channel_all(
            slide_category=slide_category,
            slug_tags=slug_tags,
            my=my,
            **post,
        )

    def slides_channel_all_values(self, slide_category=None, slug_tags=None, my=False, **post):
        values = super().slides_channel_all_values(
            slide_category=slide_category,
            slug_tags=slug_tags,
            my=my,
            **post,
        )
        if not self._is_restricted_portal_user():
            return values

        allowed_channels = self._get_restricted_portal_channels()
        values["channels"] = values["channels"].filtered(lambda channel: channel in allowed_channels)
        values["search_count"] = len(values["channels"])
        return values

    @http.route(
        [
            "/slides/<int:channel_id>",
            "/slides/<int:channel_id>/category/<int:category_id>",
            "/slides/<int:channel_id>/category/<int:category_id>/page/<int:page>",
            '/slides/<model("slide.channel"):channel>',
            '/slides/<model("slide.channel"):channel>/page/<int:page>',
            '/slides/<model("slide.channel"):channel>/tag/<model("slide.tag"):tag>',
            '/slides/<model("slide.channel"):channel>/tag/<model("slide.tag"):tag>/page/<int:page>',
            '/slides/<model("slide.channel"):channel>/category/<model("slide.slide"):category>',
            '/slides/<model("slide.channel"):channel>/category/<model("slide.slide"):category>/page/<int:page>',
        ],
        type="http",
        auth="public",
        website=True,
        sitemap=WebsiteSlides.sitemap_slide,
        handle_params_access_error=handle_wslide_error,
        readonly=True,
    )
    def channel(
        self,
        channel=False,
        channel_id=False,
        category=None,
        category_id=False,
        tag=None,
        page=1,
        slide_category=None,
        uncategorized=False,
        sorting=None,
        search=None,
        **kw,
    ):
        channel_record = channel
        if channel_id and not channel_record:
            channel_record = request.env["slide.channel"].browse(channel_id).exists()

        if channel_record and not self._is_channel_allowed_for_portal_user(channel_record):
            return self._redirect_to_slides_main("no_rights")

        return super().channel(
            channel=channel,
            channel_id=channel_id,
            category=category,
            category_id=category_id,
            tag=tag,
            page=page,
            slide_category=slide_category,
            uncategorized=uncategorized,
            sorting=sorting,
            search=search,
            **kw,
        )
