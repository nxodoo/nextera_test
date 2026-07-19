import base64
from operator import itemgetter
from urllib.parse import unquote

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.helpdesk.controllers.portal import CustomerPortal as HelpdeskCustomerPortal
from odoo.addons.portal_my_tabs.controllers.portal import PortalSidebarController
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.website.controllers.main import Website
from odoo.tools import groupby as groupbyelem
from odoo.osv.expression import AND, OR


class NexteraLogin(AuthSignupHome):
    @http.route("/web/login", type="http", auth="none", website=True, sitemap=False)
    def web_login(self, redirect=None, **kw):
        redirect = unquote(redirect) if redirect else redirect
        if request.httprequest.method == "POST" and (
            not redirect or redirect.startswith("/my/") or redirect.startswith("/helpdesk/")
        ):
            login = (kw.get("login") or "").strip()
            user = request.env["res.users"].sudo().search([("login", "=", login)], limit=1)
            redirect = "/my/home" if user.share else "/odoo"
        return super().web_login(redirect=redirect, **kw)


class NexteraWebsiteHome(Website):
    @http.route("/", auth="public", website=True, sitemap=True)
    def index(self, **kw):
        """Route warranty-portal visitors to the right entry point.

        Only the warranty portal website should bypass the standard homepage.
        Other websites keep the default website controller behavior.
        """
        if request.website.portal_mode == "warranty":
            if request.env.user._is_public():
                return request.redirect("/web/login")
            return request.redirect("/my/home")
        return super().index(**kw)


class WarrantyPortal(HelpdeskCustomerPortal):
    def _get_portal_ticket_role(self, user=None):
        user = user or request.env.user
        if user._fields.get("portal_ticket_role"):
            return user.portal_ticket_role or "user"
        partner = user.partner_id
        if partner._fields.get("portal_role"):
            return partner.portal_role or partner.commercial_partner_id.portal_role or "user"
        return "user"

    def _is_portal_only_user(self, user=None):
        user = user or request.env.user
        return user.has_group("base.group_portal") and not user.has_group("base.group_user")

    def _is_portal_ticket_admin(self, user=None):
        user = user or request.env.user
        return not self._is_portal_only_user(user) or self._get_portal_ticket_role(user) == "admin"

    def _can_view_portal_orders(self, user=None):
        return self._is_portal_ticket_admin(user=user)

    def _get_portal_ticket_base_domain(self, user=None):
        user = user or request.env.user
        partner = user.partner_id
        if not partner:
            return [("id", "=", 0)]
        if self._is_portal_ticket_admin(user):
            return [("partner_id.commercial_partner_id", "=", partner.commercial_partner_id.id)]
        return [("partner_id", "=", partner.id)]

    def _check_ticket_portal_access(self, ticket, user=None):
        user = user or request.env.user
        if not self._is_portal_only_user(user):
            return True

        partner = user.partner_id
        if not partner:
            raise AccessError()

        if self._is_portal_ticket_admin(user):
            if ticket.partner_id.commercial_partner_id != partner.commercial_partner_id:
                raise AccessError()
            return True

        if ticket.partner_id != partner:
            raise AccessError()
        return True

    def _is_arabic_portal_request(self):
        """Return whether the current website request is rendered in Arabic.

        The portal can expose the active language through different request
        attributes depending on the rendering path, so we check the website
        language, request context, and user language in order.
        """
        lang_code = ""
        if getattr(request, "lang", False) and getattr(request.lang, "code", False):
            lang_code = request.lang.code
        elif request.context.get("lang"):
            lang_code = request.context["lang"]
        elif request.env.user.lang:
            lang_code = request.env.user.lang
        return bool(lang_code and lang_code.startswith("ar"))

    def _get_partner_warranty_contracts(self, partner=None, states=None):
        """Return company warranty contracts, optionally filtered by state."""
        partner = (partner or request.env.user.partner_id).commercial_partner_id
        domain = [("partner_id", "=", partner.id)]
        if states:
            domain.append(("state", "in", states))
        return request.env["warranty.contract"].sudo().search(
            domain,
            order="start_date desc, create_date desc, id desc",
        )

    def _get_portal_allowed_teams(self):
        """Return only the helpdesk teams linked to the portal company's active contracts."""
        contracts = self._get_partner_warranty_contracts(states=["active"])
        return contracts.mapped("helpdesk_team_ids").filtered(lambda team: team.exists())

    def _get_portal_contract_for_team(self, team, partner=None):
        """Return the newest active contract matching the selected team."""
        partner = (partner or request.env.user.partner_id).commercial_partner_id
        contract = self._get_partner_warranty_contracts(partner=partner, states=["active"]).filtered(
            lambda rec: team in rec.helpdesk_team_ids
        )[:1]
        if contract:
            return contract
        return self._get_partner_warranty_contracts(partner=partner, states=["active"]).filtered(
            lambda rec: not rec.helpdesk_team_ids
        )[:1]

    def _get_latest_portal_active_contract(self, partner=None):
        """Return the newest active warranty contract for the portal company."""
        partner = (partner or request.env.user.partner_id).commercial_partner_id
        return self._get_partner_warranty_contracts(partner=partner, states=["active"])[:1]

    @http.route(["/my/tickets/attachment/<int:attachment_id>"], type="http", auth="user", website=True)
    def portal_ticket_attachment(self, attachment_id, **kwargs):
        """Serve a helpdesk ticket attachment through a stable portal URL."""
        attachment = request.env["ir.attachment"].sudo().browse(attachment_id).exists()
        if not attachment or attachment.res_model != "helpdesk.ticket" or not attachment.res_id:
            return request.not_found()

        ticket = request.env["helpdesk.ticket"].sudo().browse(attachment.res_id).exists()
        if not ticket:
            return request.not_found()

        self._check_ticket_portal_access(ticket)
        disposition = content_disposition(attachment.name or "attachment")
        if kwargs.get("inline"):
            disposition = disposition.replace("attachment;", "inline;", 1)
        return request.make_response(
            attachment.raw or b"",
            headers=[
                ("Content-Type", attachment.mimetype or "application/octet-stream"),
                ("Content-Disposition", disposition),
            ],
        )

    def _prepare_latest_warranty_values(self):
        """Build the shared warranty summary shown in the portal sidebar."""
        partner = request.env.user.partner_id.commercial_partner_id
        Warranty = request.env["warranty.contract"].sudo()
        latest_warranty = Warranty.search([
            ("partner_id", "=", partner.id),
        ], order="id desc", limit=1)
        values = {
            "latest_warranty": latest_warranty,
            "latest_warranty_progress": self._progress_percent(latest_warranty) if latest_warranty else 0.0,
            "latest_warranty_is_tickets_based": bool(
                latest_warranty and latest_warranty.warranty_template_id.duration_type == "tickets_based"
            ),
            "latest_warranty_remaining_tickets": 0,
        }
        if latest_warranty and latest_warranty.total_tickets:
            values["latest_warranty_remaining_tickets"] = max(
                (latest_warranty.total_tickets or 0) - (latest_warranty.used_tickets or 0), 0
            )
        return values

    def _get_in_progress_ticket_domain(self, ticket_domain):
        """Return the domain for tickets in the "in progress" stage.

        The portal used to rely on the English stage label and worked for the
        existing setup. We keep that behavior and add the Arabic equivalent
        instead of broadening the match to every `kanban_state == normal`
        ticket, which also includes newly created tickets.
        """
        progress_domain = OR([
            [("stage_id.name", "ilike", "progress")],
            [("stage_id.name", "ilike", "قيد التنفيذ")],
        ])
        return AND([ticket_domain, progress_domain])

    def _get_prioritized_ticket_recordset(self, ticket_model, ticket_domain, limit=None, offset=0, order="create_date desc, id desc"):
        """Return tickets ordered with in-progress tickets first, then the rest.

        Within each bucket we keep the normal newest-first ordering so the
        portal continues to feel chronological while always prioritizing
        tickets currently being worked on.
        """
        in_progress_domain = self._get_in_progress_ticket_domain(ticket_domain)
        in_progress_tickets = ticket_model.search(in_progress_domain, order=order)
        other_tickets = ticket_model.search(
            AND([ticket_domain, [("id", "not in", in_progress_tickets.ids)]]),
            order=order,
        )
        ordered_ids = (in_progress_tickets.ids + other_tickets.ids)[offset:]
        if limit:
            ordered_ids = ordered_ids[:limit]
        return ticket_model.browse(ordered_ids)

    @http.route(["/my", "/my/"], type="http", auth="user", website=True)
    def portal_my_redirect_home(self, **kwargs):
        return request.redirect("/my/home")

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values.update(self._prepare_latest_warranty_values())
        values["nx_is_arabic"] = self._is_arabic_portal_request()
        values["nx_portal_ticket_role"] = self._get_portal_ticket_role()
        values["nx_portal_is_admin"] = self._is_portal_ticket_admin()
        values["nx_portal_can_view_orders"] = self._can_view_portal_orders()
        return values

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id.commercial_partner_id
        warranty_model = request.env["warranty.contract"].sudo()
        values["warranty_count"] = warranty_model.search_count([
            ("partner_id", "=", partner.id),
        ])
        values["ticket_count"] = 0
        values["ticket_in_progress_count"] = 0
        values["ticket_in_progress_percent"] = 0.0
        values["recent_tickets"] = request.env["helpdesk.ticket"]
        if "helpdesk.ticket" in request.env:
            ticket_model = request.env["helpdesk.ticket"].sudo()
            ticket_domain = self._prepare_helpdesk_tickets_domain()
            if ticket_model.has_access("read"):
                values["ticket_count"] = ticket_model.search_count(ticket_domain)
                in_progress_domain = self._get_in_progress_ticket_domain(ticket_domain)
                values["ticket_in_progress_count"] = ticket_model.search_count(in_progress_domain)
                if values["ticket_count"]:
                    values["ticket_in_progress_percent"] = min(
                        100.0,
                        (values["ticket_in_progress_count"] / values["ticket_count"]) * 100.0,
                    )
                values["recent_tickets"] = self._get_prioritized_ticket_recordset(
                    ticket_model=ticket_model,
                    ticket_domain=ticket_domain,
                    limit=3,
                    order="create_date desc, id desc",
                )
        values["nx_is_arabic"] = self._is_arabic_portal_request()
        return values

    def _prepare_helpdesk_tickets_domain(self):
        user = request.env.user
        # Portal users should only see their customer/company tickets.
        if self._is_portal_only_user(user):
            return self._get_portal_ticket_base_domain(user)
        # Internal users should see their "My Tickets" in portal.
        return [("user_id", "=", user.id)]

    def _prepare_my_tickets_values(self, page=1, date_begin=None, date_end=None, sortby=None, filterby="all", search=None, groupby="none", search_in="name"):
        values = self._prepare_portal_layout_values()
        domain = self._prepare_helpdesk_tickets_domain()
        ticket_model = request.env["helpdesk.ticket"].sudo()

        searchbar_sortings = {
            "create_date desc": {"label": "Newest"},
            "id desc": {"label": "Reference"},
            "name": {"label": "Subject"},
            "user_id": {"label": "Assigned to"},
            "stage_id": {"label": "Stage"},
            "date_last_stage_update desc": {"label": "Last Stage Update"},
        }
        searchbar_filters = {
            "all": {"label": "All", "domain": []},
            "assigned": {"label": "Assigned", "domain": [("user_id", "!=", False)]},
            "unassigned": {"label": "Unassigned", "domain": [("user_id", "=", False)]},
            "open": {"label": "Open", "domain": [("close_date", "=", False)]},
            "closed": {"label": "Closed", "domain": [("close_date", "!=", False)]},
        }
        searchbar_inputs = dict(sorted(self._ticket_get_searchbar_inputs().items(), key=lambda item: item[1]["sequence"]))
        searchbar_groupby = dict(sorted(self._ticket_get_searchbar_groupby().items(), key=lambda item: item[1]["sequence"]))

        if not sortby:
            sortby = "create_date desc"

        domain = AND([domain, searchbar_filters[filterby]["domain"]])

        if date_begin and date_end:
            domain = AND([domain, [("create_date", ">", date_begin), ("create_date", "<=", date_end)]])

        if search and search_in:
            domain = AND([domain, self._ticket_get_search_domain(search_in, search)])

        tickets_count = ticket_model.search_count(domain)
        pager = portal_pager(
            url="/my/tickets",
            url_args={"date_begin": date_begin, "date_end": date_end, "sortby": sortby, "search_in": search_in, "search": search, "groupby": groupby, "filterby": filterby},
            total=tickets_count,
            page=page,
            step=self._items_per_page,
        )

        order = f"{groupby}, {sortby}" if groupby != "none" else sortby
        if groupby == "none" and sortby == "create_date desc":
            tickets = self._get_prioritized_ticket_recordset(
                ticket_model=ticket_model,
                ticket_domain=domain,
                limit=self._items_per_page,
                offset=pager["offset"],
                order="create_date desc, id desc",
            )
        else:
            tickets = ticket_model.search(domain, order=order, limit=self._items_per_page, offset=pager["offset"])
        request.session["my_tickets_history"] = tickets.ids[:100]

        if not tickets:
            grouped_tickets = []
        elif groupby != "none":
            grouped_tickets = [ticket_model.concat(*g) for _, g in groupbyelem(tickets, itemgetter(groupby))]
        else:
            grouped_tickets = [tickets]

        values.update({
            "date": date_begin,
            "grouped_tickets": grouped_tickets,
            "page_name": "ticket",
            "default_url": "/my/tickets",
            "pager": pager,
            "searchbar_sortings": searchbar_sortings,
            "searchbar_filters": searchbar_filters,
            "searchbar_inputs": searchbar_inputs,
            "searchbar_groupby": searchbar_groupby,
            "sortby": sortby,
            "groupby": groupby,
            "search_in": search_in,
            "search": search,
            "filterby": filterby,
        })
        return values

    @http.route(["/my/tickets", "/my/tickets/page/<int:page>"], type="http", auth="user", website=True)
    def my_helpdesk_tickets(self, page=1, date_begin=None, date_end=None, sortby=None, filterby="all", search=None, groupby="none", search_in="name", **kw):
        values = self._prepare_my_tickets_values(page, date_begin, date_end, sortby, filterby, search, groupby, search_in)
        return request.render("helpdesk.portal_helpdesk_ticket", values)

    @http.route([
        "/helpdesk/ticket/<int:ticket_id>",
        "/helpdesk/ticket/<int:ticket_id>/<access_token>",
        "/my/ticket/<int:ticket_id>",
        "/my/ticket/<int:ticket_id>/<access_token>",
    ], type="http", auth="public", website=True)
    def tickets_followup(self, ticket_id=None, access_token=None, **kw):
        try:
            ticket_sudo = self._document_check_access("helpdesk.ticket", ticket_id, access_token)
        except (AccessError, MissingError):
            if not self._is_portal_only_user():
                return request.redirect("/my")
            ticket_sudo = request.env["helpdesk.ticket"].sudo().browse(ticket_id)
            if not ticket_sudo.exists():
                return request.redirect("/my")
        try:
            self._check_ticket_portal_access(ticket_sudo)
        except AccessError:
            return request.redirect("/my")

        values = self._ticket_get_page_view_values(ticket_sudo, access_token, **kw)
        values.update(self._prepare_portal_layout_values())
        values["page_name"] = "ticket"
        return request.render("helpdesk.tickets_followup", values)

    def _progress_percent(self, contract):
        percent = 0.0
        if contract.total_allocated_minutes:
            percent = (contract.used_minutes / contract.total_allocated_minutes) * 100.0
        elif contract.total_tickets:
            percent = (contract.used_tickets / contract.total_tickets) * 100.0
        return max(0.0, min(percent, 100.0))

    def _get_relevant_courses(self):
        if "slide.channel" not in request.env:
            return [], []

        partner = request.env.user.partner_id
        enrolled = partner.sudo().nx_allowed_slide_channel_ids.filtered("website_published")
        return enrolled.sorted(lambda channel: (channel.sequence, channel.id)), request.env["slide.channel"]

    @http.route(["/my/warranties"], type="http", auth="user", website=True)
    def portal_my_warranties(self, **kwargs):
        partner = request.env.user.partner_id.commercial_partner_id
        contracts = self._get_partner_warranty_contracts(partner=partner)
        Ticket = request.env["helpdesk.ticket"].sudo()

        rows = []
        for contract in contracts:
            contract_sudo = contract.sudo()
            tickets = Ticket.search([
                ("warranty_contract_id", "=", contract.id),
                ("partner_id.commercial_partner_id", "=", partner.id),
            ], order="id desc")
            remaining_tickets = 0
            if contract.total_tickets:
                remaining_tickets = max((contract.total_tickets or 0) - (contract.used_tickets or 0), 0)

            rows.append({
                "contract": contract,
                "template_name": contract.warranty_template_id.name,
                "start_date": contract.start_date,
                "end_date": contract.end_date,
                "total_hours": round((contract.total_allocated_minutes or 0) / 60.0, 2),
                "used_hours": round((contract.used_minutes or 0) / 60.0, 2),
                "remaining_hours": round((contract.remaining_minutes or 0) / 60.0, 2),
                "progress": self._progress_percent(contract),
                "is_tickets_based": contract.warranty_template_id.duration_type == "tickets_based",
                "total_tickets": contract.total_tickets or 0,
                "used_tickets": contract.used_tickets or 0,
                "remaining_tickets": remaining_tickets,
                "sale_order_name": contract_sudo.sale_order_id.name or "",
                "helpdesk_team_names": ", ".join(contract_sudo.helpdesk_team_ids.mapped("name")),
                "ticket_count": len(tickets),
                "tickets": tickets,
            })

        values = self._prepare_portal_layout_values()
        values.update({
            "warranties": rows,
            "page_name": "warranties",
        })
        return request.render("nx_warranty_sla.portal_my_warranties", values)

    @http.route(["/my/elearning"], type="http", auth="user", website=True)
    def portal_my_elearning(self, **kwargs):
        enrolled, recommended = self._get_relevant_courses()
        values = self._prepare_portal_layout_values()
        values.update({
            "enrolled_courses": enrolled,
            "recommended_courses": recommended,
            "elearning_installed": "slide.channel" in request.env,
            "page_name": "elearning",
        })
        return request.render("nx_warranty_sla.portal_my_elearning", values)

    @http.route(["/my/knowledge"], type="http", auth="user", website=True)
    def portal_my_knowledge(self, **kwargs):
        allowed_teams = self._get_portal_allowed_teams()
        teams = allowed_teams.filtered(
            lambda rec: rec.website_published and rec.show_knowledge_base
        )
        knowledge_url = "/helpdesk"
        knowledge_teams = []
        for team in teams:
            slug = request.env["ir.http"]._slug(team)
            team_url = "/helpdesk/%s/knowledgebase" % slug
            knowledge_teams.append({
                "team": team,
                "url": team_url,
            })
        if knowledge_teams:
            knowledge_url = knowledge_teams[0]["url"]

        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "knowledge",
            "knowledge_url": knowledge_url,
            "knowledge_teams": knowledge_teams,
        })
        return request.render("nx_warranty_sla.portal_my_knowledge", values)

    @http.route(["/my/tickets/new"], type="http", auth="user", website=True)
    def portal_ticket_new(self, **kwargs):
        partner = request.env.user.partner_id
        teams = self._get_portal_allowed_teams()
        ticket_types = request.env["nx.helpdesk.ticket.type"].sudo().search([("active", "=", True)], order="sequence, id")
        values = self._prepare_portal_layout_values()
        values.update({
            "teams": teams,
            "selected_team_id": teams[:1].id if teams else False,
            "portal_partner_name": partner.name or "",
            "portal_partner_email": partner.email or "",
            "portal_partner_phone": partner.phone or "",
            "ticket_types": ticket_types,
            "error": kwargs.get("error"),
            "page_name": "ticket_new",
        })
        return request.render("nx_warranty_sla.portal_ticket_new", values)

    @http.route(["/my/tickets/create"], type="http", auth="user", website=True, methods=["POST"])
    def portal_ticket_create(self, **post):
        partner = request.env.user.partner_id
        team_id = int(post.get("team_id")) if post.get("team_id", "").isdigit() else False
        team = request.env["helpdesk.team"].sudo().browse(team_id) if team_id else request.env["helpdesk.team"]
        allowed_teams = self._get_portal_allowed_teams()
        if team and team.exists() and team.id not in allowed_teams.ids:
            team = request.env["helpdesk.team"]
        elif (not team or not team.exists()) and allowed_teams:
            team = allowed_teams[:1]

        subject = (post.get("subject") or "").strip()
        description = (post.get("description") or "").strip()
        ticket_type_id = int(post.get("ticket_type_id")) if post.get("ticket_type_id", "").isdigit() else False
        ticket_type = request.env["nx.helpdesk.ticket.type"].sudo().browse(ticket_type_id) if ticket_type_id else request.env["nx.helpdesk.ticket.type"]
        if not subject:
            return request.redirect("/my/tickets/new?error=missing_subject")
        if not ticket_type or not ticket_type.exists() or not ticket_type.active:
            return request.redirect("/my/tickets/new?error=missing_ticket_type")

        contract = self._get_latest_portal_active_contract(partner=partner)
        contract_teams = contract.helpdesk_team_ids if contract else request.env["helpdesk.team"]
        if contract_teams:
            if not team or not team.exists() or team not in contract_teams:
                team = contract_teams[:1]

        ticket = request.env["helpdesk.ticket"].sudo().create({
            "name": subject,
            "description": description or False,
            "ticket_type_id": ticket_type.id,
            "team_id": team.id if team and team.exists() else False,
            "partner_id": partner.id,
            "partner_name": partner.name or "",
            "partner_email": partner.email or "",
            "warranty_contract_id": contract.id if contract else False,
        })
        uploaded_files = request.httprequest.files.getlist("attachment")
        attachments_vals = []
        for uploaded_file in uploaded_files:
            if not uploaded_file or not uploaded_file.filename:
                continue
            attachments_vals.append({
                "name": uploaded_file.filename,
                "datas": base64.b64encode(uploaded_file.read()),
                "res_model": "helpdesk.ticket",
                "res_id": ticket.id,
                "type": "binary",
                "mimetype": uploaded_file.mimetype,
            })
        if attachments_vals:
            request.env["ir.attachment"].sudo().create(attachments_vals)
        return request.redirect("/helpdesk/ticket/%s?created=1" % ticket.id)


class WarrantySalePortal(PortalSidebarController, WarrantyPortal):
    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values.update(self._prepare_latest_warranty_values())
        return values

    @http.route(['/my/orders', '/my/orders/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_orders(self, **kwargs):
        if not self._can_view_portal_orders():
            return request.redirect("/my/home")
        return super().portal_my_orders(**kwargs)

    def _get_page_view_values(self, document, access_token, values, session_history, no_breadcrumbs, **kwargs):
        values = super()._get_page_view_values(
            document, access_token, values, session_history, no_breadcrumbs, **kwargs
        )
        values.update(self._prepare_latest_warranty_values())
        return values

    @http.route(['/my/orders/<int:order_id>'], type='http', auth="public", website=True)
    def portal_order_page(
        self,
        order_id,
        report_type=None,
        access_token=None,
        message=False,
        download=False,
        downpayment=None,
        **kw
    ):
        if not self._can_view_portal_orders():
            return request.redirect("/my/home")
        return super().portal_order_page(
            order_id,
            report_type=report_type,
            access_token=access_token,
            message=message,
            download=download,
            downpayment=downpayment,
            **kw,
        )
