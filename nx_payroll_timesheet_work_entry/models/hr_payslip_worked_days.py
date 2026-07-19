# -*- coding: utf-8 -*-
from odoo import api, models


class HrPayslipWorkedDays(models.Model):
    _inherit = 'hr.payslip.worked_days'

    @api.depends('is_paid', 'is_credit_time', 'number_of_hours', 'payslip_id', 'contract_id.wage', 'payslip_id.sum_worked_hours')
    def _compute_amount(self):
        timesheet_lines = self.filtered(
            lambda line: line.payslip_id.contract_id.work_entry_source == 'timesheet'
        )
        regular_lines = self - timesheet_lines
        if regular_lines:
            super(HrPayslipWorkedDays, regular_lines)._compute_amount()

        for worked_days in timesheet_lines:
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
            hourly_cost = worked_days.contract_id._get_timesheet_hourly_cost()
            worked_days.amount = hourly_cost * worked_days.number_of_hours
