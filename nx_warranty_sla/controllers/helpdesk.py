from urllib.parse import urlencode

from markupsafe import Markup, escape
from werkzeug.utils import redirect

from odoo import http
from odoo.addons.website_helpdesk.controllers.main import WebsiteHelpdesk
from odoo.http import request


class NexteraWebsiteHelpdesk(WebsiteHelpdesk):
    def _get_default_contactus_team(self):
        """Return the configured Helpdesk team used by the public contact form."""
        return request.env["helpdesk.team"].sudo().search([
            ("is_default_contactus_team", "=", True),
            ("active", "=", True),
        ], limit=1)

    def _build_contactus_ticket_description(self, post):
        """Build the helpdesk ticket description from the website contact form."""
        description = (post.get("description") or "").strip()
        company = (post.get("company") or "").strip()
        blocks = []

        if description:
            blocks.append(
                "<p><strong>Message</strong></p><div>%s</div>" % "<br/>".join(
                    escape(line) for line in description.splitlines()
                )
            )

        contact_details = []
        for label, value in (
            ("Name", post.get("name")),
            ("Email", post.get("email_from")),
            ("Phone", post.get("phone")),
            ("Company", company),
        ):
            cleaned_value = (value or "").strip()
            if cleaned_value:
                contact_details.append(
                    "<li><strong>%s:</strong> %s</li>" % (escape(label), escape(cleaned_value))
                )

        if contact_details:
            blocks.append(
                "<p><strong>Contact Details</strong></p><ul>%s</ul>" % "".join(contact_details)
            )

        return Markup("".join(blocks)) if blocks else False

    def _prepare_contactus_redirect_params(self, post, error):
        """Preserve the entered contact form values when redirecting back with an error."""
        params = {
            "error": error,
            "name": post.get("name", ""),
            "phone": post.get("phone", ""),
            "email_from": post.get("email_from", ""),
            "company": post.get("company", ""),
            "subject": post.get("subject", ""),
        }
        return urlencode(params)

    @http.route(
        ["/helpdesk", "/helpdesk/<model(\"helpdesk.team\"):team>"],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
    )
    def website_helpdesk_teams(self, team=None, **kwargs):
        if team and team.website_published and not kwargs.get("contact_form"):
            return redirect(team.website_url + "/knowledgebase")
        return super().website_helpdesk_teams(team=team, **kwargs)

    @http.route(
        ["/helpdesk/<model(\"helpdesk.team\"):team>/knowledgebase"],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
    )
    def website_helpdesk_knowledge_base(self, team, **kwargs):
        search = kwargs.get("search")
        if search is not None:
            return super().website_helpdesk_knowledge_base(team, **kwargs)
        return request.render(
            "website_helpdesk.knowledge_base",
            self._get_knowledge_base_values(team),
        )

    @http.route(
        ["/contactus/submit"],
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
    )
    def website_contactus_submit(self, **post):
        """Create a helpdesk ticket in the configured default Contact Us team."""
        team = self._get_default_contactus_team()
        subject = (post.get("subject") or "").strip()
        description = (post.get("description") or "").strip()
        email = (post.get("email_from") or "").strip()

        if not team:
            return request.redirect("/contactus?%s" % self._prepare_contactus_redirect_params(post, "no_default_team"))
        if not subject:
            return request.redirect("/contactus?%s" % self._prepare_contactus_redirect_params(post, "missing_subject"))
        if not description:
            return request.redirect("/contactus?%s" % self._prepare_contactus_redirect_params(post, "missing_description"))

        partner = request.env["res.partner"]
        if email:
            partner = request.env["res.partner"].sudo().search([("email", "=ilike", email)], limit=1)

        ticket = request.env["helpdesk.ticket"].sudo().create({
            "name": subject,
            "description": self._build_contactus_ticket_description(post),
            "team_id": team.id,
            "partner_id": partner.id if partner else False,
            "partner_name": (post.get("name") or "").strip(),
            "partner_email": email,
            "partner_phone": (post.get("phone") or "").strip(),
        })
        ticket_number = ticket.ticket_ref or ticket.name or str(ticket.id)
        return request.redirect("/contactus-thank-you?ticket_number=%s" % ticket_number)
