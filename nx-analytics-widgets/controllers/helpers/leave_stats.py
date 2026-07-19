# -*- coding: utf-8 -*-


def _sum_map_by_status(records):
    """Map holiday_status_id to aggregated number_of_days from read_group payload."""
    return {
        rec['holiday_status_id'][0]: (
            rec.get('number_of_days_sum')
            if rec.get('number_of_days_sum') is not None
            else rec.get('number_of_days', 0.0)
        )
        for rec in records
        if rec.get('holiday_status_id')
    }


def build_leave_maps(env, employee_id):
    """Return allocation/taken maps grouped by leave type for one employee."""
    if not employee_id:
        return {}, {}

    allocation_data = env['hr.leave.allocation'].sudo().read_group(
        [
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
        ],
        ['number_of_days:sum'],
        ['holiday_status_id'],
    )

    taken_data = env['hr.leave'].sudo().read_group(
        [
            ('employee_id', '=', employee_id),
            ('state', 'in', ['confirm', 'validate', 'validate1']),
        ],
        ['number_of_days:sum'],
        ['holiday_status_id'],
    )

    return _sum_map_by_status(allocation_data), _sum_map_by_status(taken_data)


def get_leave_state_counts(leave_model, employee_id):
    """Return pending and approved leave counts for one employee."""
    if not employee_id:
        return 0, 0

    state_data = leave_model.read_group(
        [
            ('employee_id', '=', employee_id),
            ('state', 'in', ['confirm', 'validate', 'validate1']),
        ],
        ['state'],
        ['state'],
        lazy=False,
    )

    state_count_map = {
        rec.get('state'): rec.get('state_count', rec.get('__count', 0))
        for rec in state_data
        if rec.get('state')
    }

    pending_count = state_count_map.get('confirm', 0)
    approved_count = state_count_map.get('validate', 0) + state_count_map.get('validate1', 0)
    return pending_count, approved_count

