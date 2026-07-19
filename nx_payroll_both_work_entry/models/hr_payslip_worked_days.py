# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrPayslipWorkedDays(models.Model):
    _inherit = 'hr.payslip.worked_days'

    both_threshold_line = fields.Boolean(
        string='Both Threshold Line',
        help='Set for worked-days lines generated from the Both work entry source.',
    )
    both_full_day_count = fields.Float(
        string='Both Full Day Count',
        help='Number of days that reached the minimum timesheet-hours threshold.',
    )
    both_partial_hours = fields.Float(
        string='Both Partial Hours',
        help='Hours below the minimum threshold that must be paid with hourly cost.',
    )

    def _is_both_threshold_worked_day(self):
        """
        Return True when the line belongs to the custom Both threshold split.

        We primarily rely on the explicit boolean flag, but we also keep a
        fallback based on the payslip source and generated description so saved
        records still compute correctly if the helper fields are incomplete.
        """
        self.ensure_one()
        if self.both_threshold_line:
            return True
        return bool(
            self.payslip_id.contract_id.work_entry_source == 'both'
            and self.name
            and 'Both Threshold - ' in self.name
        )

    def _get_both_threshold_amount(self):
        """Return the exact amount that should be stored on a Both threshold line."""
        self.ensure_one()
        if (
            not self.contract_id
            or self.code == 'OUT'
            or self.is_credit_time
            or not self.is_paid
        ):
            return 0.0

        if self.both_full_day_count:
            is_full_day_line = True
        elif self.both_partial_hours:
            is_full_day_line = False
        else:
            # Fallback for saved rows whose helper fields were not populated.
            is_full_day_line = bool(self.name and 'Both Threshold - Full Days' in self.name)
        if is_full_day_line:
            full_day_amount, _partial_amount = self.payslip_id._get_both_line_amounts(
                self.both_full_day_count or self.number_of_days,
                0.0,
            )
            return full_day_amount

        _full_day_amount, partial_amount = self.payslip_id._get_both_line_amounts(
            0.0,
            self.both_partial_hours or self.number_of_hours,
        )
        return partial_amount

    def _force_both_threshold_amounts(self):
        """
        Persist the custom Both amounts after create/write/recompute.

        Some inherited payroll compute chains still recompute saved rows with
        the generic prorated-wage formula. This helper re-applies the intended
        Both split amounts on the final records so the stored values stay
        aligned with the business rule.
        """
        for worked_days in self.filtered(lambda line: line._is_both_threshold_worked_day()):
            amount = worked_days._get_both_threshold_amount()
            worked_days.with_context(skip_both_threshold_amount_force=True).update({
                'amount': amount,
            })

    @api.depends(
        'is_paid',
        'is_credit_time',
        'number_of_hours',
        'payslip_id',
        'contract_id.wage',
        'payslip_id.sum_worked_hours',
        'both_threshold_line',
        'both_full_day_count',
        'both_partial_hours',
    )
    def _compute_amount(self):
        both_lines = self.filtered(lambda line: line._is_both_threshold_worked_day())
        regular_lines = self - both_lines
        if regular_lines:
            super(HrPayslipWorkedDays, regular_lines)._compute_amount()

        for worked_days in both_lines:
            if worked_days.payslip_id.edited or worked_days.payslip_id.state not in ['draft', 'verify']:
                continue
            if (
                not worked_days.contract_id
                or worked_days.code == 'OUT'
                or worked_days.is_credit_time
                or not worked_days.is_paid
            ):
                worked_days.amount = 0
                continue

            worked_days.amount = worked_days._get_both_threshold_amount()

    @api.depends('work_entry_type_id', 'number_of_days', 'number_of_hours', 'payslip_id', 'both_threshold_line')
    def _compute_name(self):
        both_lines = self.filtered(lambda line: line._is_both_threshold_worked_day())
        regular_lines = self - both_lines
        if regular_lines:
            super(HrPayslipWorkedDays, regular_lines)._compute_name()

        for worked_days in both_lines:
            if worked_days.both_partial_hours and not worked_days.both_full_day_count:
                is_full_day_line = False
            elif worked_days.both_full_day_count:
                is_full_day_line = True
            else:
                # Fallback for saved rows whose helper fields were not populated.
                is_full_day_line = worked_days.number_of_days >= 1.0
            if is_full_day_line:
                worked_days.name = '%s (Both Threshold - Full Days)' % worked_days.work_entry_type_id.name
            else:
                worked_days.name = '%s (Both Threshold - Partial Hours)' % worked_days.work_entry_type_id.name

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._force_both_threshold_amounts()
        return records

    def write(self, vals):
        if self.env.context.get('skip_both_threshold_amount_force'):
            return super().write(vals)
        result = super().write(vals)
        self._force_both_threshold_amounts()
        return result
