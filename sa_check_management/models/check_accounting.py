from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .check_allocation import CTX_ALLOCATION_SYSTEM_WRITE

POSTING_ACTIONS = frozenset({"receive", "issue"})
REVERSING_ACTIONS = frozenset({"cancel", "return"})
COLLATERAL_PURPOSES = frozenset({"guarantee", "security"})
ACTIVE_PAYMENT_STATES = frozenset({"in_process", "paid"})


class CheckCheck(models.Model):
    _inherit = "check.check"

    commercial_partner_id = fields.Many2one(related="partner_id.commercial_partner_id")
    allocation_account_type = fields.Char(compute="_compute_allocation_account_type")
    allocation_ids = fields.One2many("check.allocation", "check_id", string="Allocations")
    allocated_amount = fields.Monetary(
        currency_field="currency_id", compute="_compute_allocation_totals", store=True,
    )
    unallocated_amount = fields.Monetary(
        currency_field="currency_id", compute="_compute_allocation_totals", store=True,
    )
    payment_ids = fields.One2many("account.payment", "sa_check_id", string="Payments", readonly=True)
    sa_move_ids = fields.One2many("account.move", "sa_check_id", string="Check Entries", readonly=True)
    payment_count = fields.Integer(compute="_compute_payment_count")
    accounting_status = fields.Selection(
        selection=[
            ("none", "Not Posted"),
            ("posted", "Posted"),
            ("reversed", "Reversed"),
            ("not_applicable", "No Accounting"),
        ],
        required=True, default="none", readonly=True, copy=False, tracking=True,
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("check_type")
    def _compute_allocation_account_type(self):
        for check in self:
            check.allocation_account_type = (
                "asset_receivable" if check.check_type == "incoming" else "liability_payable"
            )

    @api.depends("amount", "allocation_ids.amount")
    def _compute_allocation_totals(self):
        for check in self:
            check.allocated_amount = sum(check.allocation_ids.mapped("amount"))
            check.unallocated_amount = check.amount - check.allocated_amount

    @api.depends("payment_ids")
    def _compute_payment_count(self):
        # Check users may have no accounting rights; counting is not a disclosure.
        for check in self:
            check.payment_count = len(check.sudo().payment_ids)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("amount")
    def _check_amount_covers_allocations(self):
        for check in self:
            if check.currency_id.compare_amounts(check.allocated_amount, check.amount) > 0:
                raise ValidationError(_(
                    "Check %(check)s: the amount is lower than its allocations.", check=check.display_name,
                ))

    @api.constrains("purpose")
    def _check_collateral_has_no_allocations(self):
        for check in self:
            if check.purpose in COLLATERAL_PURPOSES and check.allocation_ids:
                raise ValidationError(_("Remove the allocations before making this a guarantee or security check."))

    # ------------------------------------------------------------------
    # Allocation helpers (shared by the Add Invoices wizard and posting)
    # ------------------------------------------------------------------
    def action_open_allocation_wizard(self):
        self.ensure_one()
        wizard = self.env["check.allocation.wizard"]._create_for_check(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("Add Invoices") if self.check_type == "incoming" else _("Add Bills"),
            "res_model": "check.allocation.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def _validate_allocation_editable(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Invoices can only be added while the check is in Draft."))
        if self.purpose in COLLATERAL_PURPOSES:
            raise UserError(_("Guarantee and security checks cannot settle invoices or bills."))

    def _open_allocation_items(self, partner=None, account_type=None):
        """Open receivable/payable items this check may settle, earliest due first.

        Defaults to the check's own partner and direction; endorsement passes the endorsee
        and ``liability_payable`` to list the vendor bills the check can pay.
        """
        self.ensure_one()
        account_type = account_type or self.allocation_account_type
        commercial = (partner or self.partner_id).commercial_partner_id
        sign_operator = ">" if account_type == "asset_receivable" else "<"
        return self.env["account.move.line"].sudo().search([
            ("company_id", "=", self.company_id.id),
            ("partner_id.commercial_partner_id", "=", commercial.id),
            ("account_type", "=", account_type),
            ("parent_state", "=", "posted"),
            ("reconciled", "=", False),
            ("currency_id", "=", self.currency_id.id),
            ("amount_residual_currency", sign_operator, 0),
            ("id", "not in", self.allocation_ids.move_line_id.ids),
        ], order="date_maturity, id")

    def _document_summaries(self, items):
        """One summary per document (invoice/bill) of the given open items, for selection wizards."""
        self.ensure_one()
        reserved = self._reserved_amounts(items)
        grouped = {}
        for item in items:
            grouped.setdefault(item.move_id, []).append(item)
        summaries = []
        for move, move_items in grouped.items():
            open_amount = sum(self._item_available(item, reserved) for item in move_items)
            if open_amount <= 0 or self.currency_id.is_zero(open_amount):
                continue
            summaries.append({
                "move_ref": move.id,
                "document_name": move.name,
                "document_date": move.invoice_date or move.date,
                "date_due": min((item.date_maturity for item in move_items if item.date_maturity), default=False),
                "installment_count": len(move_items),
                "open_amount": open_amount,
            })
        return summaries

    def _distribute_over_items(self, items, amount, reserved):
        """Split ``amount`` over ``items`` (earliest due first) within what each still has open.

        Returns a list of ``(item, share)``; raises if the items cannot absorb the amount.
        """
        self.ensure_one()
        left = amount
        shares = []
        for item in items:
            if self.currency_id.is_zero(left):
                break
            share = min(self._item_available(item, reserved), left)
            if share > 0:
                shares.append((item, share))
                left -= share
        if not self.currency_id.is_zero(left):
            raise UserError(_("The selected documents changed since the list was opened. Reopen it and try again."))
        return shares

    def _reserved_amounts(self, items):
        """Amounts already reserved on these items by other checks that are not posted yet."""
        self.ensure_one()
        reserved = {}
        allocations = self.env["check.allocation"].sudo().search([
            ("move_line_id", "in", items.ids),
            ("check_id", "!=", self.id),
            ("check_id.state", "=", "draft"),
        ])
        for allocation in allocations:
            reserved[allocation.move_line_id.id] = reserved.get(allocation.move_line_id.id, 0.0) + allocation.amount
        return reserved

    @api.model
    def _item_available(self, item, reserved):
        return abs(item.amount_residual_currency) - reserved.get(item.id, 0.0)

    def _validate_allocations_still_open(self):
        """Invoices may have been paid since allocation; never post more than is still open."""
        self.ensure_one()
        for allocation in self.sudo().allocation_ids:
            line = allocation.move_line_id
            open_amount = 0.0 if line.reconciled else abs(line.amount_residual_currency)
            if self.currency_id.compare_amounts(allocation.amount, open_amount) > 0:
                raise UserError(_(
                    "%(document)s now has only %(open)s open; update the check allocations first.",
                    document=line.move_id.display_name, open=self.currency_id.format(open_amount),
                ))

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------
    def _after_transition(self, action):
        super()._after_transition(action)
        if action in POSTING_ACTIONS:
            self._post_check_accounting()
        elif action in REVERSING_ACTIONS:
            self._reverse_check_accounting()

    def _has_accounting_entries(self):
        self.ensure_one()
        return bool(self._active_payments() or self._active_entries(("deposit", "collection", "clearing", "endorsement", "discount")))

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------
    def _post_check_accounting(self, method_line=None, date=None, at_collection=False):
        """Create and reconcile the settlement payments of the check.

        At receipt/issue this follows the company settlement policy. With ``at_collection``
        (settlement at collection/clearing) it posts regardless, on the given bank method line.
        """
        self.ensure_one()
        if not self._creates_entries():
            self._set_accounting_status("not_applicable")
            return
        if not at_collection and self.company_id.check_settlement_policy != "receipt":
            return
        if self._active_payments():
            return
        self._validate_allocations_still_open()
        payments = self._create_payments(method_line, date)
        payments.action_post()
        self._reconcile_allocations()
        self._set_accounting_status("posted")
        self._log_event(
            "accounting",
            note=_("Posted: %(payments)s", payments=", ".join(payments.mapped("name"))),
            source=payments[:1],
        )

    def _creates_entries(self):
        self.ensure_one()
        if self.purpose in COLLATERAL_PURPOSES:
            return False
        if self.purpose == "advance":
            return self.company_id.check_advance_creates_entries
        return True

    def _create_payments(self, method_line=None, date=None):
        self.ensure_one()
        method_line = method_line or self._payment_method_line()
        vals_list = [self._payment_vals(method_line, alloc.amount, alloc, date) for alloc in self.allocation_ids]
        if not self.currency_id.is_zero(self.unallocated_amount):
            vals_list.append(self._payment_vals(method_line, self.unallocated_amount, date=date))
        payments = self.env["account.payment"].sudo().with_company(self.company_id).create(vals_list)
        self._link_allocation_payments(payments)
        return payments

    def _payment_method_line(self):
        self.ensure_one()
        company = self.company_id._sa_check_accounting_setup()
        if self.check_type == "incoming":
            return company._sa_check_incoming_method_line()
        return company._sa_check_outgoing_method_line(self.journal_id)

    def _payment_vals(self, method_line, amount, allocation=None, date=None):
        self.ensure_one()
        incoming = self.check_type == "incoming"
        default_date = self.received_date if incoming else self.issued_date
        vals = {
            "payment_type": "inbound" if incoming else "outbound",
            "partner_type": "customer" if incoming else "supplier",
            "partner_id": self.partner_id.id,
            "amount": amount,
            "currency_id": self.currency_id.id,
            "date": date or default_date or fields.Date.context_today(self),
            "journal_id": method_line.journal_id.id,
            "payment_method_line_id": method_line.id,
            "memo": f"{self.name} - {self.check_number}",
            "company_id": self.company_id.id,
            "sa_check_id": self.id,
        }
        if allocation:
            vals["sa_check_allocation_id"] = allocation.id
            vals["destination_account_id"] = allocation.move_line_id.account_id.id
        return vals

    def _link_allocation_payments(self, payments):
        for payment in payments.filtered("sa_check_allocation_id"):
            payment.sa_check_allocation_id.with_context(**{CTX_ALLOCATION_SYSTEM_WRITE: True}).write({
                "payment_id": payment.id,
            })

    def _reconcile_allocations(self):
        self.ensure_one()
        for allocation in self.sudo().allocation_ids:
            counterpart = allocation.payment_id._seek_for_lines()[1]
            (counterpart + allocation.move_line_id).sudo().reconcile()

    # ------------------------------------------------------------------
    # Reversal
    # ------------------------------------------------------------------
    def _reverse_check_accounting(self, include_payments=True, entry_types=("deposit",)):
        """Reverse settlement payments and/or open check entries; originals stay posted."""
        self.ensure_one()
        payments = self._active_payments() if include_payments else self.env["account.payment"]
        entries = self._active_entries(entry_types)
        moves = (payments.move_id | entries).sudo()
        if not moves:
            return
        reversal_date = fields.Date.context_today(self)
        reversals = moves._reverse_moves(
            default_values_list=[{"date": reversal_date, "ref": _("Reversal of %s", move.name)} for move in moves],
            cancel=True,
        )
        if payments:
            payments.write({"state": "canceled"})
            self._set_accounting_status("reversed")
        self._log_event(
            "accounting",
            note=_("Reversed: %(moves)s", moves=", ".join(reversals.mapped("name"))),
            source=(payments or entries)[:1],
        )

    def _active_entries(self, entry_types):
        """Posted check entries (deposit, collection...) that were not reversed and are not reversals."""
        self.ensure_one()
        return self.sudo().sa_move_ids.filtered(
            lambda move: move.state == "posted"
            and move.sa_check_entry_type in entry_types
            and not move.reversal_move_ids
            and not move.reversed_entry_id
        )

    def _active_payments(self):
        self.ensure_one()
        return self.sudo().payment_ids.filtered(
            lambda payment: payment.state in ACTIVE_PAYMENT_STATES and payment.move_id.state == "posted"
        )

    def _set_accounting_status(self, status):
        self.ensure_one()
        self.sudo().write({"accounting_status": status})

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_payments(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_account_payments")
        action.update({
            "domain": [("sa_check_id", "=", self.id)],
            "context": {"create": False},
        })
        return action
