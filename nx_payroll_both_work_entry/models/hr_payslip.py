# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_BOTH_SOURCE = 'both'
_DEFAULT_HOURS_PER_DAY = 8.0


class _PayrollCodeAccessor(dict):
    """
    Dict that also exposes code keys through attribute access.

    Some custom salary rules use `worked_days.CODE` instead of the standard
    `worked_days['CODE']`. This wrapper supports both styles so existing rules
    keep working.
    """

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


class HrPayslip(models.Model):
    """
    Fixes the chicken-and-egg problem in hr.payslip where company_id is
    computed solely from the employee, causing employee_id's domain filter
    to resolve to ('company_id', '=', False) on a new, unsaved payslip —
    which hides every employee that belongs to a company.

    Fix: fall back to the user's current company when no employee is set yet.
    """

    _inherit = 'hr.payslip'

    @api.depends('employee_id')
    def _compute_company_id(self):
        """
        Override to default company_id to the user's current company when no
        employee has been selected yet.  Once an employee is chosen the value
        follows the employee's company as normal.
        """
        for slip in self:
            slip.company_id = slip.employee_id.company_id or self.env.company

    @api.onchange('employee_id')
    def _onchange_employee_id_keep_selection(self):
        """
        Keep the employee selection stable on new payslips.

        The web client can briefly recompute dependent domains before the
        computed company/contract fields settle, which makes the selected
        employee disappear as if the click did nothing.  Updating the company
        and default contract eagerly during onchange keeps the form coherent.
        """
        for slip in self:
            employee = slip.employee_id
            if not employee:
                slip.company_id = self.env.company
                slip.contract_domain_ids = False
                slip.contract_id = False
                slip.struct_id = False
                continue

            slip.company_id = employee.company_id or self.env.company

            contracts = self.env['hr.contract'].search([
                ('company_id', '=', slip.company_id.id),
                ('employee_id', '=', employee.id),
                ('state', 'in', ['open', 'close']),
            ])
            slip.contract_domain_ids = contracts
            open_contracts = contracts.filtered(lambda contract: contract.state == 'open')
            slip.contract_id = (open_contracts[:1] or contracts[:1])._origin
            if slip.contract_id and not slip.struct_id:
                slip.struct_id = (
                    slip.contract_id.structure_type_id.default_struct_id
                    or slip.struct_id
                )

    def _get_localdict(self):
        """Keep worked_days/inputs compatible with attribute-style rule access."""
        localdict = super()._get_localdict()
        worked_days = dict(localdict.get('worked_days', {}))
        for line in self.worked_days_line_ids.filtered('both_threshold_line'):
            if line.both_partial_hours and not line.both_full_day_count:
                worked_days['BOTHH'] = line
            elif line.both_full_day_count:
                worked_days['BOTHD'] = line
            elif line.name and 'Both Threshold - Full Days' in line.name:
                worked_days['BOTHD'] = line
            else:
                worked_days['BOTHH'] = line
        localdict['worked_days'] = _PayrollCodeAccessor(worked_days)
        localdict['inputs'] = _PayrollCodeAccessor(localdict.get('inputs', {}))
        return localdict

    def _get_worked_day_lines_hours_per_day(self):
        self.ensure_one()
        if self.contract_id.work_entry_source != _BOTH_SOURCE:
            return super()._get_worked_day_lines_hours_per_day()
        calendar = (
            self.contract_id.resource_calendar_id
            or self.employee_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        return calendar.hours_per_day if calendar and calendar.hours_per_day else _DEFAULT_HOURS_PER_DAY

    def _get_both_line_amounts(self, full_day_count, partial_hours):
        """Return the draft amounts for Both full-day and partial-hour lines."""
        self.ensure_one()
        contract = self.contract_id
        hourly_cost = contract._get_both_partial_hourly_cost() if contract else 0.0
        full_day_amount = (full_day_count or 0.0) * (contract.contract_wage if contract else 0.0)
        partial_amount = (partial_hours or 0.0) * hourly_cost
        return full_day_amount, partial_amount

    def _get_both_worked_day_lines_values(self, domain=None):
        """
        Build payslip worked-days lines for the Both source.

        Full-threshold days and partial hourly days are returned as separate
        lines so payroll users can see each bucket independently.
        """
        self.ensure_one()
        contract = self.contract_id
        if contract.work_entry_source != _BOTH_SOURCE:
            return []

        work_entry_type = contract._get_both_work_entry_type()
        if not work_entry_type:
            return []

        buckets = contract._get_both_day_buckets(self.date_from, self.date_to)
        if not buckets:
            _logger.info(
                'nx_payroll_both_work_entry: no timesheet hours for %s (%s → %s).',
                contract.employee_id.name,
                self.date_from,
                self.date_to,
            )
            return []

        full_day_hours = 0.0
        full_day_count = 0.0
        partial_hours = 0.0
        partial_days = 0.0

        for bucket in buckets:
            calendar_day_hours = bucket['calendar_day_hours'] or self._get_worked_day_lines_hours_per_day()
            if bucket['is_full_day']:
                full_day_count += 1.0
                full_day_hours += bucket['logged_hours']
            else:
                partial_hours += bucket['entry_hours']
                partial_days += bucket['entry_hours'] / calendar_day_hours

        full_day_amount, partial_amount = self._get_both_line_amounts(full_day_count, partial_hours)

        line_values = []
        if full_day_count:
            line_values.append({
                'sequence': work_entry_type.sequence,
                'work_entry_type_id': work_entry_type.id,
                'number_of_days': self._round_days(work_entry_type, full_day_count),
                'number_of_hours': full_day_hours,
                'amount': full_day_amount,
                'both_threshold_line': True,
                'both_full_day_count': full_day_count,
                'both_partial_hours': 0.0,
            })
        if partial_hours:
            line_values.append({
                'sequence': work_entry_type.sequence + 1,
                'work_entry_type_id': work_entry_type.id,
                'number_of_days': self._round_days(work_entry_type, partial_days),
                'number_of_hours': partial_hours,
                'amount': partial_amount,
                'both_threshold_line': True,
                'both_full_day_count': 0.0,
                'both_partial_hours': partial_hours,
            })
        return line_values

    def _get_worked_day_lines_values(self, domain=None):
        self.ensure_one()
        if self.contract_id.work_entry_source == _BOTH_SOURCE:
            return self._get_both_worked_day_lines_values(domain=domain)
        return super()._get_worked_day_lines_values(domain=domain)

    def _get_worked_day_lines(self, domain=None, check_out_of_contract=True):
        self.ensure_one()
        if self.contract_id.work_entry_source != _BOTH_SOURCE:
            return super()._get_worked_day_lines(
                domain=domain,
                check_out_of_contract=check_out_of_contract,
            )
        return self._get_worked_day_lines_values(domain=domain)

    def _refresh_both_payslip_data(self):
        """
        Rebuild Both-source worked days directly from timesheets.

        This avoids relying on the standard work-entry collector for the final
        payslip lines while still regenerating the underlying work entries.
        """
        for slip in self:
            contract = slip.contract_id
            date_from = fields.Date.to_date(slip.date_from) if slip.date_from else False
            date_to = fields.Date.to_date(slip.date_to) if slip.date_to else False
            if (
                not contract
                or not contract._origin.id
                or contract.work_entry_source != _BOTH_SOURCE
            ):
                continue
            if not date_from or not date_to:
                _logger.debug(
                    'nx_payroll_both_work_entry: skipping payslip refresh for %s '
                    'because the period is incomplete (date_from=%s, date_to=%s).',
                    slip.display_name,
                    slip.date_from,
                    slip.date_to,
                )
                continue
            if date_from > date_to:
                _logger.debug(
                    'nx_payroll_both_work_entry: skipping payslip refresh for %s '
                    'because the period is invalid (date_from=%s, date_to=%s).',
                    slip.display_name,
                    date_from,
                    date_to,
                )
                continue

            contract._unlink_draft_work_entries_in_period(
                date_from,
                date_to,
            )
            slip.worked_days_line_ids.unlink()
            slip.line_ids.unlink()

            generate_from = date_from + relativedelta(days=-1)
            generate_to = date_to + relativedelta(days=1)
            contract.generate_work_entries(
                generate_from,
                generate_to,
                force=True,
            )
            slip.update({
                'worked_days_line_ids': [
                    (0, 0, values)
                    for values in slip._get_both_worked_day_lines_values()
                ],
            })
            slip.worked_days_line_ids._force_both_threshold_amounts()

            if slip.state == 'verify':
                slip.compute_sheet()

    def action_payslip_draft(self):
        result = super().action_payslip_draft()
        both_slips = self.filtered(
            lambda slip: slip.contract_id.work_entry_source == _BOTH_SOURCE
        )
        if both_slips:
            both_slips._refresh_both_payslip_data()
        return result

    @api.depends('employee_id', 'contract_id', 'struct_id', 'date_from', 'date_to')
    def _compute_worked_days_line_ids(self):
        if not self or self.env.context.get('salary_simulation'):
            return

        both_slips = self.filtered(
            lambda slip: slip.contract_id.work_entry_source == _BOTH_SOURCE
            and slip.contract_id._origin.id
            and slip.employee_id
            and slip.date_from
            and slip.date_to
            and slip.contract_id
            and slip.struct_id
            and slip.struct_id.use_worked_day_lines
        )
        if both_slips:
            new_both_slips = both_slips.filtered(lambda slip: not slip._origin.id)
            persisted_both_slips = both_slips - new_both_slips

            for slip in new_both_slips:
                slip.update({
                    'worked_days_line_ids': [(5, 0, 0)],
                })
                slip.update({
                    'worked_days_line_ids': [
                        (0, 0, values)
                        for values in slip._get_both_worked_day_lines_values()
                    ],
                })
                slip.worked_days_line_ids._force_both_threshold_amounts()

            if persisted_both_slips:
                persisted_both_slips.update({'worked_days_line_ids': [(5, 0, 0)]})
                persisted_both_slips._refresh_both_payslip_data()

        other_slips = self - both_slips
        if other_slips:
            return super(HrPayslip, other_slips)._compute_worked_days_line_ids()
        return
