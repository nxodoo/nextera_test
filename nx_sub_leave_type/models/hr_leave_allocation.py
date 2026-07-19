# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HrLeaveAllocation(models.Model):
    """Extends hr.leave.allocation to support sub leave types.

    An HR officer can attach a Sub Leave Type to any allocation.
    Employees may then request leave using the sub type, and the system
    deducts consumed days from both the sub leave limit and the parent balance.
    """

    _inherit = 'hr.leave.allocation'

    # ── Sub Leave Configuration Fields ───────────────────────────────────────

    sub_leave_type_id = fields.Many2one(
        comodel_name='hr.leave.type',
        string='Sub Leave Type',
        tracking=True,
        help='Leave type that draws its balance from this allocation.',
    )
    sub_leave_days_limit = fields.Float(
        string='Sub Leave Days Limit',
        default=0.0,
        tracking=True,
        help='Maximum total days the employee may consume via the sub leave type.',
    )
    max_days_per_request = fields.Float(
        string='Maximum Days Per Request',
        default=0.0,
        tracking=True,
        help='Maximum days allowed in a single sub leave request. 0 = no limit.',
    )

    # ── Sub Leave Usage Tracking ──────────────────────────────────────────────

    sub_leave_used_days = fields.Float(
        string='Sub Leave Used Days',
        readonly=True,
        default=0.0,
        copy=False,
        help='Cumulative days consumed via the sub leave type from this allocation.',
    )
    sub_leave_remaining_days = fields.Float(
        string='Sub Leave Remaining Days',
        compute='_compute_sub_leave_remaining',
        store=True,
        help='Days still available for sub leave: limit minus used.',
    )

    # ── Computed Fields ───────────────────────────────────────────────────────

    @api.depends('sub_leave_days_limit', 'sub_leave_used_days')
    def _compute_sub_leave_remaining(self):
        for allocation in self:
            allocation.sub_leave_remaining_days = (
                allocation.sub_leave_days_limit - allocation.sub_leave_used_days
            )

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('sub_leave_days_limit', 'number_of_days')
    def _check_sub_leave_days_limit(self):
        """Ensure the sub leave limit does not exceed the total allocated days."""
        for allocation in self:
            if (
                allocation.sub_leave_type_id
                and allocation.sub_leave_days_limit > allocation.number_of_days
            ):
                raise ValidationError(_(
                    'Sub Leave Days Limit (%(limit)s) cannot exceed the total '
                    'allocated days (%(total)s).',
                    limit=allocation.sub_leave_days_limit,
                    total=allocation.number_of_days,
                ))

    @api.constrains('sub_leave_type_id', 'holiday_status_id')
    def _check_sub_type_differs_from_parent(self):
        """Prevent the sub leave type from being the same as the parent type."""
        for allocation in self:
            if (
                allocation.sub_leave_type_id
                and allocation.sub_leave_type_id == allocation.holiday_status_id
            ):
                raise ValidationError(_(
                    'The Sub Leave Type must be different from the parent leave type.'
                ))

    # ── Onchange Helpers ──────────────────────────────────────────────────────

    @api.onchange('sub_leave_type_id')
    def _onchange_sub_leave_type_id(self):
        """Reset sub leave limits when the sub leave type is cleared."""
        if not self.sub_leave_type_id:
            self.sub_leave_days_limit = 0.0
            self.max_days_per_request = 0.0

    # ── Balance Mutation Helpers ──────────────────────────────────────────────

    def _deduct_sub_leave_days(self, days):
        """Deduct consumed sub leave days from this allocation.

        Reduces both the sub leave usage counter and the parent allocation's
        ``number_of_days`` so that the parent leave balance is also affected.

        Args:
            days (float): Number of days to deduct.

        Raises:
            ValidationError: if the deduction would exceed available balances.
        """
        self.ensure_one()
        if self.sub_leave_remaining_days < days:
            raise ValidationError(_('Sub leave balance exceeded.'))

        new_used = self.sub_leave_used_days + days
        new_total = self.number_of_days - days

        self.sudo().write({
            'sub_leave_used_days': new_used,
            'number_of_days': new_total,
        })
        _logger.info(
            'Sub leave deduction: allocation=%s, deducted=%s days, '
            'sub_used=%s, parent_remaining=%s',
            self.id, days, new_used, new_total,
        )

    def _restore_sub_leave_days(self, days):
        """Restore previously deducted sub leave days to this allocation.

        Called when a sub leave request is refused or reset to draft.

        Args:
            days (float): Number of days to restore.
        """
        self.ensure_one()
        restored_used = max(0.0, self.sub_leave_used_days - days)
        restored_total = self.number_of_days + days

        self.sudo().write({
            'sub_leave_used_days': restored_used,
            'number_of_days': restored_total,
        })
        _logger.info(
            'Sub leave restoration: allocation=%s, restored=%s days, '
            'sub_used=%s, parent_total=%s',
            self.id, days, restored_used, restored_total,
        )
