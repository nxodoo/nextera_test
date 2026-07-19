from odoo import fields, models


class HelpdeskTicketCloseFeedbackWizard(models.TransientModel):
    _name = "helpdesk.ticket.close.feedback.wizard"
    _description = "Helpdesk Ticket Close Feedback Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        readonly=True,
    )
    target_stage_id = fields.Many2one(
        "helpdesk.stage",
        string="Target Stage",
        required=True,
        readonly=True,
    )
    final_feedback = fields.Text(
        string="Final Feedback",
        required=True,
    )

    def action_apply(self):
        """Store the final feedback and move the ticket to the requested closing stage."""
        self.ensure_one()
        self.ticket_id.with_context(skip_close_feedback_wizard=True).write({
            "final_feedback": self.final_feedback,
            "stage_id": self.target_stage_id.id,
        })
        return {"type": "ir.actions.act_window_close"}
