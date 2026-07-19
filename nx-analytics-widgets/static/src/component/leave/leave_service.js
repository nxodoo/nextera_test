/** @odoo-module **/

// ── State helpers ────────────────────────────────────────────────────────────
const _STATE_LABELS = {
    draft:     'Draft',
    confirm:   'Pending',
    validate1: 'Partial Approval',
    validate:  'Approved',
    refuse:    'Refused',
};

const _STATE_MAP = {
    draft:    ['draft'],
    pending:  ['confirm'],
    partial:  ['validate1'],
    approved: ['validate'],
    refused:  ['refuse'],
};

const _CANCELLABLE_STATES = new Set(['draft', 'confirm']);

// ── Domain builder ───────────────────────────────────────────────────────────
function _buildDomain(employeeId, userId, stateFilter, search) {
    // Base: records belonging to this user's employee (or user as fallback)
    let domain = employeeId
        ? [['employee_id', '=', employeeId]]
        : [['user_id', '=', userId]];

    // State filter
    if (stateFilter && _STATE_MAP[stateFilter]) {
        domain.push(['state', 'in', _STATE_MAP[stateFilter]]);
    }

    // Live search over leave type name OR description
    if (search && search.trim()) {
        domain = [
            '|',
            ['holiday_status_id.name', 'ilike', search.trim()],
            ['name', 'ilike', search.trim()],
            ...domain,
        ];
    }

    return domain;
}

// ── Date formatter ───────────────────────────────────────────────────────────
function _fmtDate(str) {
    if (!str) return null;
    const d = new Date(str);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: '2-digit' });
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Fetch the current user's employee id.
 * Returns null when no employee record is linked.
 * @param {Object} orm  - Odoo ORM service (useService("orm"))
 * @param {number} userId
 * @returns {Promise<number|null>}
 */
export async function fetchEmployeeId(orm, userId) {
    const rows = await orm.searchRead(
        'hr.employee',
        [['user_id', '=', userId]],
        ['id'],
        { limit: 1 },
    );
    return rows.length ? rows[0].id : null;
}

/**
 * Fetch a page of leaves.
 * @param {Object} orm
 * @param {Object} params
 * @param {number}  params.employeeId
 * @param {number}  params.userId
 * @param {number}  params.page
 * @param {number}  params.pageSize
 * @param {string}  params.stateFilter  '' | 'draft' | 'pending' | 'partial' | 'approved' | 'refused'
 * @param {string}  params.sortOrder    'asc' | 'desc'
 * @param {string}  params.search
 * @returns {Promise<{leaves, total, page, pages}>}
 */
export async function fetchLeaves(orm, {
    employeeId, userId,
    page = 1, pageSize = 10,
    stateFilter = '', sortOrder = 'desc', search = '',
} = {}) {
    const domain = _buildDomain(employeeId, userId, stateFilter, search);
    const safePageSize = Math.max(parseInt(pageSize, 10), 1);
    let safePage = Math.max(parseInt(page, 10), 1);

    const total = await orm.searchCount('hr.leave', domain);
    const pages = total ? Math.max(Math.ceil(total / safePageSize), 1) : 1;
    safePage = Math.min(safePage, pages);

    const order = `date_from ${sortOrder === 'asc' ? 'asc' : 'desc'}`;
    const records = await orm.searchRead(
        'hr.leave',
        domain,
        ['id', 'holiday_status_id', 'name', 'date_from', 'date_to',
         'number_of_days', 'number_of_hours', 'state'],
        { order, limit: safePageSize, offset: (safePage - 1) * safePageSize },
    );

    const leaves = records.map(r => ({
        id:          r.id,
        leave_type:  r.holiday_status_id ? r.holiday_status_id[1] : '',
        description: r.name || '',
        date_from:   _fmtDate(r.date_from),
        date_to:     _fmtDate(r.date_to),
        days:        Math.round(r.number_of_days * 100) / 100,
        hours:       Math.round((r.number_of_hours || 0) * 100) / 100,
        state:       r.state,
        state_label: _STATE_LABELS[r.state] || r.state,
        can_cancel:  _CANCELLABLE_STATES.has(r.state),
    }));

    return { leaves, total, page: safePage, pages };
}

/**
 * Cancel (refuse) a leave request by id.
 * @param {Object} orm
 * @param {number} leaveId
 * @returns {Promise<{ok: boolean, error?: string}>}
 */
export async function cancelLeave(orm, leaveId) {
    try {
        await orm.call('hr.leave', 'action_refuse', [[leaveId]]);
        return { ok: true };
    } catch (e) {
        return { ok: false, error: e.message || String(e) };
    }
}
