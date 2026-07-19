# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    """Extends hr.leave to enforce sub leave rules and dual-balance deduction.

    When an employee requests a leave whose type is configured as a Sub Leave
    Type in a validated parent allocation, the system:
      1. Validates the per-request day limit.
      2. Validates the sub leave remaining balance.
      3. Validates the parent leave remaining balance.
      4. On approval, deducts from both the sub leave limit and the parent
         allocation's total days.
      5. On refusal or reset-to-draft, restores the deducted days.
    """

    _inherit = 'hr.leave'

    # ── Sub Leave Tracking Fields ─────────────────────────────────────────────

    parent_allocation_id = fields.Many2one(
        comodel_name='hr.leave.allocation',
        string='Parent Leave Allocation',
        readonly=True,
        copy=False,
        help='The parent allocation from which sub leave balance was deducted.',
    )
    is_sub_leave = fields.Boolean(
        string='Is Sub Leave',
        compute='_compute_is_sub_leave',
        store=False,
        help='True when this leave type is configured as a sub type in a parent allocation.',
    )
    sub_leave_remaining_display = fields.Float(
        string='Sub Leave Remaining',
        compute='_compute_sub_leave_remaining_display',
        store=False,
        help='Remaining sub leave days available before this request.',
    )

    # ── Computed Fields ───────────────────────────────────────────────────────

    @api.depends('holiday_status_id', 'employee_id', 'state')
    def _compute_is_sub_leave(self):
        for leave in self:
            leave.is_sub_leave = bool(leave._find_parent_allocation())

    @api.depends('holiday_status_id', 'employee_id')
    def _compute_sub_leave_remaining_display(self):
        for leave in self:
            allocation = leave._find_parent_allocation()
            leave.sub_leave_remaining_display = (
                allocation.sub_leave_remaining_days if allocation else 0.0
            )

    # ── Lookup Helpers ────────────────────────────────────────────────────────

    def _find_parent_allocation(self):
        """Find the validated parent allocation that maps this leave type as sub leave.

        Searches for an approved allocation belonging to the same employee
        where ``sub_leave_type_id`` matches this request's leave type.

        Returns:
            hr.leave.allocation: First matching allocation, or empty recordset.
        """
        self.ensure_one()
        if not self.holiday_status_id or not self.employee_id:
            return self.env['hr.leave.allocation']

        return self.env['hr.leave.allocation'].search([
            ('employee_id', '=', self.employee_id.id),
            ('sub_leave_type_id', '=', self.holiday_status_id.id),
            ('state', '=', 'validate'),
        ], limit=1)

    def _get_parent_available_days(self, parent_allocation):
        """Return the actual available days remaining on the parent allocation.

        Computes: parent allocation number_of_days minus all validated direct
        leave requests of the parent type (sub leave deductions are already
        reflected in number_of_days via _deduct_sub_leave_days).

        Args:
            parent_allocation (hr.leave.allocation): The parent allocation record.

        Returns:
            float: Available days on the parent allocation.
        """
        self.ensure_one()
        used_direct = sum(
            self.env['hr.leave'].search([
                ('employee_id', '=', self.employee_id.id),
                ('holiday_status_id', '=', parent_allocation.holiday_status_id.id),
                ('state', '=', 'validate'),
                ('id', '!=', self._origin.id or 0),
            ]).mapped('number_of_days')
        )
        return parent_allocation.number_of_days - used_direct

    # ── Validation Helpers ────────────────────────────────────────────────────

    def _validate_sub_leave_limits(self, parent_allocation):
        """Validate this sub leave request against all configured limits.

        Checks (in order):
          1. Maximum days per single request.
          2. Sub leave remaining balance.
          3. Parent leave remaining balance.

        Args:
            parent_allocation (hr.leave.allocation): The parent allocation.

        Raises:
            ValidationError: on the first violated rule.
        """
        self.ensure_one()
        days = self.number_of_days

        # 1. Per-request maximum
        max_per_request = parent_allocation.max_days_per_request
        if max_per_request > 0 and days > max_per_request:
            raise ValidationError(_(
                'Maximum allowed days per request is %(max)s days.',
                max=int(max_per_request),
            ))

        # 2. Sub leave balance
        if days > parent_allocation.sub_leave_remaining_days:
            raise ValidationError(_('Sub leave balance exceeded.'))

        # 3. Parent leave balance
        parent_available = self._get_parent_available_days(parent_allocation)
        if days > parent_available:
            raise ValidationError(_('Insufficient parent leave balance.'))

    # ── Odoo Validity Override ────────────────────────────────────────────────

    def _check_validity(self):
        """Override to bypass the standard allocation check for sub leave types.

        In Odoo 17 the balance check moved from _check_holidays (removed) to
        _check_validity, which is called from create() and action_confirm().
        Sub leave requests draw from a parent allocation rather than their own
        dedicated allocation, so we exclude them from the standard check.
        Our custom validation is applied in _validate_sub_leave_limits instead.
        """
        non_sub_leaves = self.filtered(lambda l: not l._find_parent_allocation())
        if non_sub_leaves:
            super(HrLeave, non_sub_leaves)._check_validity()

    # ── Workflow Overrides ────────────────────────────────────────────────────

    def action_confirm(self):
        """Extend confirm action to run sub leave limit checks early.

        Raises:
            ValidationError: if any limit is violated for a sub leave request.
        """
        for leave in self:
            parent_allocation = leave._find_parent_allocation()
            if parent_allocation:
                leave._validate_sub_leave_limits(parent_allocation)
        return super().action_confirm()

    def action_validate(self, check_state=True):
        """Extend validation to deduct from the parent allocation for sub leaves.

        Collects parent allocations before calling super so that if Odoo's
        own validation raises, no deduction takes place. After a successful
        super() call, deductions are applied and the parent allocation link
        is recorded on each leave.

        Args:
            check_state (bool): Passed through to super; controls whether the
                current state is validated before transition (default True).

        Returns:
            Action dict returned by super().action_validate().
        """
        # Collect sub leave data before state transition
        sub_leave_data = []
        for leave in self:
            if leave.state in ('validate',):
                continue
            parent_allocation = leave._find_parent_allocation()
            if parent_allocation:
                leave._validate_sub_leave_limits(parent_allocation)
                sub_leave_data.append((leave, parent_allocation))

        result = super().action_validate(check_state=check_state)

        # Apply deductions after successful validation
        for leave, parent_allocation in sub_leave_data:
            leave._apply_sub_leave_deduction(parent_allocation)

        return result

    def action_refuse(self):
        """Restore parent allocation days when a validated sub leave is refused."""
        # Snapshot before state change: only restore validated/validate1 leaves
        restorable = [
            (leave, leave.parent_allocation_id)
            for leave in self
            if leave.parent_allocation_id and leave.state in ('validate', 'validate1')
        ]

        result = super().action_refuse()

        for leave, parent_allocation in restorable:
            if parent_allocation.exists():
                parent_allocation._restore_sub_leave_days(leave.number_of_days)
                leave.sudo().write({'parent_allocation_id': False})
                _logger.info(
                    'Sub leave days restored after refusal: leave=%s, days=%s, '
                    'allocation=%s',
                    leave.id, leave.number_of_days, parent_allocation.id,
                )

        return result

    def _reset_draft(self):
        """Restore parent allocation days when a sub leave is reset to draft."""
        restorable = [
            (leave, leave.parent_allocation_id)
            for leave in self
            if leave.parent_allocation_id
        ]

        result = super()._reset_draft()

        for leave, parent_allocation in restorable:
            if parent_allocation.exists():
                parent_allocation._restore_sub_leave_days(leave.number_of_days)
                leave.sudo().write({'parent_allocation_id': False})
                _logger.info(
                    'Sub leave days restored after reset to draft: leave=%s, '
                    'days=%s, allocation=%s',
                    leave.id, leave.number_of_days, parent_allocation.id,
                )

        return result

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _apply_sub_leave_deduction(self, parent_allocation):
        """Apply the dual deduction: sub limit counter + parent allocation days.

        Args:
            parent_allocation (hr.leave.allocation): The parent allocation.
        """
        self.ensure_one()
        parent_allocation._deduct_sub_leave_days(self.number_of_days)
        self.sudo().write({'parent_allocation_id': parent_allocation.id})
        _logger.info(
            'Sub leave deduction applied: leave=%s, days=%s, allocation=%s',
            self.id, self.number_of_days, parent_allocation.id,
        )
