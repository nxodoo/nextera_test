from odoo import _, fields, models

from .check_banking import CTX_INTERNAL_ACCOUNTING
from .check_check import CTX_STATE_TRANSITION
from .check_deposit import CTX_DEPOSIT_SYSTEM_WRITE

IMPORT_STATES = {
    "incoming": ("received", "under_collection", "bounced"),
    "outgoing": ("issued", "delivered"),
}
POSTING_STATES = frozenset({"received", "under_collection", "issued", "delivered"})


class CheckCheck(models.Model):
    _inherit = "check.check"

    is_imported = fields.Boolean(readonly=True, copy=False, help="Created by the legacy check import.")

    def _import_into_state(self, state, journal=None, deposit_date=None, post_entries=True):
        """Put a freshly created draft check in its real current state, with one Imported event."""
        self.ensure_one()
        date = self.issue_date
        # A deposit only accepts received checks: hold the check as received until it is in its deposit.
        vals = {"state": "received" if state == "under_collection" else state, "is_imported": True}
        vals["received_date" if self.check_type == "incoming" else "issued_date"] = date
        if self.check_type == "outgoing" and state == "delivered":
            vals["delivered_date"] = date
        self.with_context(**{CTX_STATE_TRANSITION: True}).write(vals)
        self._log_event("imported", old_state="draft", new_state=state, note=_("Imported from a legacy system"))
        internal = self.with_context(**{CTX_INTERNAL_ACCOUNTING: True})
        if post_entries and state in POSTING_STATES:
            internal._post_check_accounting(date=date, at_collection=True)
        elif not post_entries or not self._creates_entries():
            internal._set_accounting_status("none" if self._creates_entries() else "not_applicable")
        if state == "under_collection":
            self._import_open_deposit(journal, deposit_date or date)
            self.with_context(**{CTX_STATE_TRANSITION: True}).write({"state": "under_collection"})

    def _import_open_deposit(self, journal, date):
        self.ensure_one()
        deposit = self.env["check.deposit"].create({
            "journal_id": journal.id,
            "date": date,
            "company_id": self.company_id.id,
            "line_ids": [fields.Command.create({"check_id": self.id})],
        })
        deposit._set_state("confirmed")
        location = self.env["check.location"]._bank_location(journal)
        self._move_custody(location, _("Imported as deposited at %s", journal.sudo().display_name))
        return deposit.line_ids.with_context(**{CTX_DEPOSIT_SYSTEM_WRITE: True})
