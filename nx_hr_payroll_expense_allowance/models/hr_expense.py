import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrExpense(models.Model):
    _inherit = "hr.expense"

    state = fields.Selection(
        selection_add=[
            ("payroll_pending", "Pending Payroll"),
            ("payroll_paid", "Paid via Payroll"),
        ],
    )

    payroll_allowance_payslip_id = fields.Many2one(
        "hr.payslip",
        string="Allowance Payslip",
        readonly=True,
        copy=False,
        tracking=True,
        help="Payslip that includes this expense in the payroll allowance input.",
    )
    payroll_allowance_posted = fields.Boolean(
        string="Posted to Payroll",
        compute="_compute_payroll_allowance_flags",
        store=True,
    )
    payroll_reimbursed_via_payroll = fields.Boolean(
        string="Paid via Payroll",
        readonly=True,
        copy=False,
        tracking=True,
        help="Set when the linked payslip is confirmed (done).",
    )

    @api.depends("payroll_allowance_payslip_id")
    def _compute_payroll_allowance_flags(self):
        for expense in self:
            expense.payroll_allowance_posted = bool(expense.payroll_allowance_payslip_id)

    @api.depends(
        "sheet_id",
        "sheet_id.account_move_ids",
        "sheet_id.state",
        "payroll_allowance_payslip_id",
        "payroll_allowance_payslip_id.state",
        "payroll_reimbursed_via_payroll",
        "payment_mode",
    )
    def _compute_state(self):
        """Insert payroll reimbursement states after Approved for employee-paid expenses only."""
        super()._compute_state()
        for expense in self:
            if expense.payment_mode != "own_account":
                continue
            if expense.payroll_reimbursed_via_payroll:
                expense.state = "payroll_paid"
            elif (
                expense.payroll_allowance_payslip_id
                and expense.payroll_allowance_payslip_id.state in ("draft", "verify")
                and expense.state == "approved"
            ):
                expense.state = "payroll_pending"

    def write(self, vals):
        protected_fields = {
            "date",
            "employee_id",
            "product_id",
            "payment_mode",
            "currency_id",
            "total_amount",
            "total_amount_currency",
            "sheet_id",
        }
        if protected_fields.intersection(vals):
            locked = self.filtered(
                lambda e: e.payroll_reimbursed_via_payroll
                or (
                    e.payroll_allowance_payslip_id
                    and e.payroll_allowance_payslip_id.state in ("done", "paid")
                )
            )
            if locked:
                raise UserError(
                    _("You cannot modify expenses that are already locked on a confirmed payslip.")
                )
        res = super().write(vals)
        if "payroll_allowance_payslip_id" in vals:
            _logger.info(
                "Payroll allowance linkage updated for expenses %s → payslip %s",
                self.ids,
                vals.get("payroll_allowance_payslip_id"),
            )
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_payroll_allowance_locked(self):
        if any(e.payroll_reimbursed_via_payroll for e in self):
            raise UserError(_("You cannot delete an expense reimbursed via payroll."))
        if any(
            e.payroll_allowance_payslip_id and e.payroll_allowance_payslip_id.state in ("done", "paid")
            for e in self
        ):
            raise UserError(_("You cannot delete an expense linked to a confirmed payslip allowance."))

    def action_open_allowance_payslip(self):
        self.ensure_one()
        if not self.payroll_allowance_payslip_id:
            return False
        action = self.env.ref("hr_payroll.action_view_hr_payslip_form").read()[0]
        action.update(
            {
                "views": [(self.env.ref("hr_payroll.view_hr_payslip_form").id, "form")],
                "res_id": self.payroll_allowance_payslip_id.id,
                "view_mode": "form",
            }
        )
        return action
