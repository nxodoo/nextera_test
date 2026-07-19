# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_TIMESHEET_SOURCE = 'timesheet'
_DEFAULT_HOURS_PER_DAY = 8.0


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    @api.depends('employee_id')
    def _compute_company_id(self):
        """Keep a valid company even while the draft payslip is incomplete."""
        for slip in self:
            slip.company_id = slip.employee_id.company_id or self.env.company

    @api.depends('contract_id', 'contract_id.work_entry_source')
    def _compute_struct_id(self):
        """Seed Worker Pay only when the payslip has no structure yet."""
        super()._compute_struct_id()
        timesheet_slips = self.filtered(
            lambda p: p.contract_id.work_entry_source == _TIMESHEET_SOURCE and not p.struct_id
        )
        worker_struct = self.env.ref(
            'hr_payroll.structure_worker_001',
            raise_if_not_found=False,
        )
        if timesheet_slips and worker_struct:
            timesheet_slips.struct_id = worker_struct

    def _get_worked_day_lines_hours_per_day(self):
        self.ensure_one()
        if self.contract_id.work_entry_source != _TIMESHEET_SOURCE:
            return super()._get_worked_day_lines_hours_per_day()
        calendar = (
            self.contract_id.resource_calendar_id
            or self.employee_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        return calendar.hours_per_day if calendar and calendar.hours_per_day else _DEFAULT_HOURS_PER_DAY

    def _get_timesheet_worked_day_lines_values(self, domain=None):
        """Build worked days directly from timesheet lines."""
        self.ensure_one()
        contract = self.contract_id
        if contract.work_entry_source != _TIMESHEET_SOURCE:
            return []

        work_entry_type = contract._get_timesheet_work_entry_type()
        if not work_entry_type:
            return []

        hours = contract._get_timesheet_hours_total(self.date_from, self.date_to)
        if not hours:
            _logger.info(
                'nx_payroll_timesheet_work_entry: no timesheet hours for %s (%s → %s).',
                contract.employee_id.name,
                self.date_from,
                self.date_to,
            )
            return []

        hours_per_day = self._get_worked_day_lines_hours_per_day()
        days = round(hours / hours_per_day, 5) if hours_per_day else 0.0
        day_rounded = self._round_days(work_entry_type, days)

        return [{
            'sequence': work_entry_type.sequence,
            'work_entry_type_id': work_entry_type.id,
            'number_of_days': day_rounded,
            'number_of_hours': hours,
        }]

    def _get_worked_day_lines_values(self, domain=None):
        self.ensure_one()
        if self.contract_id.work_entry_source == _TIMESHEET_SOURCE:
            return self._get_timesheet_worked_day_lines_values(domain=domain)
        return super()._get_worked_day_lines_values(domain=domain)

    def _get_worked_day_lines(self, domain=None, check_out_of_contract=True):
        self.ensure_one()
        if self.contract_id.work_entry_source != _TIMESHEET_SOURCE:
            return super()._get_worked_day_lines(
                domain=domain,
                check_out_of_contract=check_out_of_contract,
            )
        return self._get_worked_day_lines_values(domain=domain)

    def _refresh_timesheet_payslip_data(self):
        """Full refresh for persisted Timesheet payslips only."""
        for slip in self:
            if not slip._origin.id:
                continue
            if slip.contract_id.work_entry_source != _TIMESHEET_SOURCE:
                raise UserError(_(
                    'This payslip contract must use Work Entry Source "Timesheet". '
                    'Open the contract and set it, then click Refresh again.'
                ))
            if slip.state not in ('draft', 'verify'):
                raise UserError(_('The payslip must be in Draft or Waiting state.'))
            if not slip.contract_id or not slip.date_from or not slip.date_to:
                continue

            date_from = fields.Date.to_date(slip.date_from)
            date_to = fields.Date.to_date(slip.date_to)
            if not date_from or not date_to:
                continue

            worker_struct = self.env.ref(
                'hr_payroll.structure_worker_001',
                raise_if_not_found=False,
            )
            if worker_struct:
                slip.struct_id = worker_struct

            slip.contract_id._unlink_draft_work_entries_in_period(
                date_from, date_to,
            )
            slip.worked_days_line_ids.unlink()
            slip.line_ids.unlink()

            generate_from = date_from + relativedelta(days=-1)
            generate_to = date_to + relativedelta(days=1)
            slip.contract_id.generate_work_entries(generate_from, generate_to, force=True)
            slip._compute_worked_days_line_ids()

            if slip.state == 'verify':
                slip.compute_sheet()

    def action_payslip_draft(self):
        res = super().action_payslip_draft()
        timesheet_slips = self.filtered(
            lambda p: p.contract_id.work_entry_source == _TIMESHEET_SOURCE
        )
        if timesheet_slips:
            timesheet_slips._refresh_timesheet_payslip_data()
        return res

    @api.depends('employee_id', 'contract_id', 'struct_id', 'date_from', 'date_to')
    def _compute_worked_days_line_ids(self):
        if not self or self.env.context.get('salary_simulation'):
            return

        timesheet_slips = self.filtered(
            lambda p: p.contract_id.work_entry_source == _TIMESHEET_SOURCE
            and p.employee_id
            and p.date_from
            and p.date_to
            and p.contract_id
            and p.contract_id._origin.id
            and p.struct_id
            and p.struct_id.use_worked_day_lines
        )
        other_slips = self - timesheet_slips
        if other_slips:
            super(HrPayslip, other_slips)._compute_worked_days_line_ids()

        for slip in timesheet_slips:
            slip.update({'worked_days_line_ids': [(5, 0, 0)]})
            slip.update({'worked_days_line_ids': slip._get_new_worked_days_lines()})

    def action_refresh_timesheet_worked_days(self):
        self._refresh_timesheet_payslip_data()
        return True
