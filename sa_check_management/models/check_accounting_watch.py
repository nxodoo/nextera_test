from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .check_banking import CTX_INTERNAL_ACCOUNTING

GROUP_MANAGER = "sa_check_management.group_check_manager"
GROUP_ACCOUNTANT = "sa_check_management.group_check_accountant"


def _checks_of_moves(moves):
    moves = moves.sudo()
    return moves.origin_payment_id.sa_check_id | moves.sa_check_id


class CheckCheck(models.Model):
    _inherit = "check.check"

    accounting_attention = fields.Boolean(
        string="Needs Accounting Review", readonly=True, copy=False, tracking=True,
        help="An entry of this check was changed from Accounting, outside the check workflow.",
    )
    accounting_attention_note = fields.Text(string="What Changed", readonly=True, copy=False)

    def _flag_external_change(self, reason):
        for check in self.sudo():
            note = "\n".join(filter(None, [check.accounting_attention_note, reason]))
            check.write({"accounting_attention": True, "accounting_attention_note": note})
            check._log_event("accounting", note=_("Changed outside the check: %s", reason))
            user = check.responsible_user_id
            if user and user.active and not user.share:
                check.activity_schedule(
                    "mail.mail_activity_data_todo", summary=_("Review the accounting of this check"),
                    note=reason, user_id=user.id,
                )

    def action_open_reallocation_wizard(self):
        self.ensure_one()
        wizard = self.env["check.reallocation.wizard"]._create_for_check(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("Repair Allocations"),
            "res_model": "check.reallocation.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_mark_accounting_reviewed(self):
        if not self.env.su and not (self.env.user.has_group(GROUP_MANAGER) or self.env.user.has_group(GROUP_ACCOUNTANT)):
            raise AccessError(_("Only a Check Manager or Check Accountant can clear the review flag."))
        for check in self:
            check.sudo().write({"accounting_attention": False, "accounting_attention_note": False})
            check._log_event("correction", note=_("Accounting reviewed by %s", self.env.user.name))
        return True


class AccountMove(models.Model):
    _inherit = "account.move"

    def button_draft(self):
        checks = self._sa_checks_to_watch()
        result = super().button_draft()
        checks._flag_external_change(_("Entry %s was reset to draft.", ", ".join(self.mapped("name"))))
        return result

    def button_cancel(self):
        checks = self._sa_checks_to_watch()
        result = super().button_cancel()
        checks._flag_external_change(_("Entry %s was cancelled.", ", ".join(self.mapped("name"))))
        return result

    def _sa_checks_to_watch(self):
        if self.env.context.get(CTX_INTERNAL_ACCOUNTING):
            return self.env["check.check"]
        return _checks_of_moves(self.filtered(lambda move: move.state == "posted"))


class AccountPartialReconcile(models.Model):
    _inherit = "account.partial.reconcile"

    def unlink(self):
        if self.env.context.get(CTX_INTERNAL_ACCOUNTING):
            return super().unlink()
        affected = self._sa_check_allocation_checks()
        result = super().unlink()
        affected._flag_external_change(_("A payment of this check was unreconciled from an invoice or bill."))
        return result

    def _sa_check_allocation_checks(self):
        """Posted checks whose settlement (payment against invoice) this reconciliation is part of."""
        lines = (self.debit_move_id | self.credit_move_id).sudo()
        payments = lines.move_id.origin_payment_id.filtered("sa_check_allocation_id")
        settlement_lines = payments.mapped(lambda payment: payment._seek_for_lines()[1])
        if not (lines & settlement_lines):
            return self.env["check.check"]
        return payments.sa_check_id.filtered(lambda check: check.accounting_status == "posted")
