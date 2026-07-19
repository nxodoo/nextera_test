from odoo import api, models


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    @api.model
    def _ensure_helpdesk_ticket_project(self, ticket):
        """Ensure the ticket's team has a project so timesheets can be created safely."""
        if not ticket or ticket.project_id or not ticket.team_id or "project_id" not in ticket.team_id._fields:
            return ticket.project_id

        company = ticket.company_id or ticket.team_id.company_id or self.env.user.company_id or self.env.company
        create_project = getattr(ticket.team_id.sudo(), "_create_project", None)
        if not create_project:
            return self.env["project.project"]

        project = create_project(
            ticket.team_id.name,
            bool(getattr(ticket.team_id, "use_helpdesk_sale_timesheet", False)),
            {"company_id": company.id} if company else {},
        )
        ticket.team_id.sudo().write({"project_id": project.id})
        ticket.invalidate_recordset(["project_id", "analytic_account_id"])
        return ticket.team_id.project_id

    @api.model
    def _get_helpdesk_ticket_from_vals_or_context(self, vals):
        """Resolve the related helpdesk ticket for virtual one2many timesheet rows."""
        ticket_id = vals.get("helpdesk_ticket_id") or self.env.context.get("default_helpdesk_ticket_id")
        if not ticket_id and self.env.context.get("active_model") == "helpdesk.ticket":
            ticket_id = self.env.context.get("active_id")
        if not ticket_id:
            return self.env["helpdesk.ticket"]
        return self.env["helpdesk.ticket"].sudo().browse(ticket_id).exists()

    @api.model
    def _prepare_helpdesk_ticket_defaults(self, vals):
        """Fill missing analytic line defaults from the linked helpdesk ticket."""
        ticket = self._get_helpdesk_ticket_from_vals_or_context(vals)
        if not ticket:
            prepared_vals = dict(vals)
            if not prepared_vals.get("company_id"):
                prepared_vals["company_id"] = self.env.company.id
            return prepared_vals

        project = self._ensure_helpdesk_ticket_project(ticket) or ticket.project_id
        company = (
            project.company_id
            or ticket.company_id
            or ticket.team_id.company_id
            or self.env.user.company_id
            or self.env.company
        )
        analytic_account = ticket.analytic_account_id or project.account_id

        prepared_vals = dict(vals)
        if ticket and not prepared_vals.get("helpdesk_ticket_id"):
            prepared_vals["helpdesk_ticket_id"] = ticket.id
        if project and not prepared_vals.get("project_id"):
            prepared_vals["project_id"] = project.id
        if company and not prepared_vals.get("company_id"):
            prepared_vals["company_id"] = company.id
        if analytic_account and not prepared_vals.get("account_id"):
            prepared_vals["account_id"] = analytic_account.id
        return prepared_vals

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = [
            self._prepare_helpdesk_ticket_defaults(vals)
            for vals in vals_list
        ]
        lines = super().create(prepared_vals_list)
        if "helpdesk_ticket_id" not in lines._fields:
            return lines

        tickets = lines.mapped("helpdesk_ticket_id")
        if tickets:
            tickets._recompute_warranty_used_minutes_from_timesheets()
        return lines

    def write(self, vals):
        has_ticket_field = "helpdesk_ticket_id" in self._fields
        if not has_ticket_field:
            return super().write(vals)

        prepared_vals = self._prepare_helpdesk_ticket_defaults(vals)
        needs_sync = "unit_amount" in vals or "helpdesk_ticket_id" in vals
        old_tickets = self.mapped("helpdesk_ticket_id") if needs_sync else self.env["helpdesk.ticket"]

        res = super().write(prepared_vals)

        if not needs_sync:
            return res

        tickets = old_tickets | self.mapped("helpdesk_ticket_id")
        if tickets:
            tickets._recompute_warranty_used_minutes_from_timesheets()

        return res

    def unlink(self):
        has_ticket_field = "helpdesk_ticket_id" in self._fields
        old_tickets = self.mapped("helpdesk_ticket_id") if has_ticket_field else self.env["helpdesk.ticket"]

        res = super().unlink()

        if has_ticket_field and old_tickets:
            old_tickets._recompute_warranty_used_minutes_from_timesheets()

        return res
