/** @odoo-module **/

// Open Tasks service (portal OWL)
// - Uses ORM service (useService('orm')) like the existing LeaveTableApp.
// - Provides pagination, filters, search, sorting, and archive action.

function _fmtDate(str) {
    if (!str) return null;
    const d = new Date(str);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: '2-digit' });
}

const _STATE_LABELS = {
    '01_in_progress': 'In Progress',
    '02_changes_requested': 'Changes Requested',
    '03_approved': 'Approved',
    '04_waiting_normal': 'Waiting',
    '1_done': 'Done',
    '1_canceled': 'Canceled',
};

function _buildDomain({ userId, filterKey, search }) {
    // Base open tasks domain (same as your controller + include active records)
    let domain = [
        ['user_ids', 'in', [userId]],
        ['stage_id.fold', '=', false],
        ['state', 'not in', ['1_done', '1_canceled']],
        ['active', '=', true],
    ];

    // Extra quick filters (optional)
    const today = new Date().toISOString().split('T')[0];
    if (filterKey === 'overdue') {
        domain.push(['date_deadline', '!=', false]);
        domain.push(['date_deadline', '<', today]);
    } else if (filterKey === 'due_soon') {
        // Next 7 days (inclusive)
        const d = new Date();
        d.setDate(d.getDate() + 7);
        const soon = d.toISOString().split('T')[0];
        domain.push(['date_deadline', '!=', false]);
        domain.push(['date_deadline', '>=', today]);
        domain.push(['date_deadline', '<=', soon]);
    } else if (filterKey === 'no_deadline') {
        domain.push(['date_deadline', '=', false]);
    }

    if (search && search.trim()) {
        const q = search.trim();
        domain = [
            '|',
            ['name', 'ilike', q],
            ['project_id.name', 'ilike', q],
            ...domain,
        ];
    }

    return domain;
}

function _buildOrder(sortKey, sortOrder) {
    const dir = sortOrder === 'asc' ? 'asc' : 'desc';
    switch (sortKey) {
        case 'deadline':
            // put nearest deadlines first by default
            return `date_deadline ${dir}, id desc`;
        case 'assign_date':
            return `create_date ${dir}, id desc`;
        case 'stage':
            return `stage_id ${dir}, id desc`;
        default:
            return `id ${dir}`;
    }
}

export async function fetchOpenTasks(orm, {
    userId,
    page = 1,
    pageSize = 10,
    filterKey = '',
    search = '',
    sortKey = 'deadline',
    sortOrder = 'asc',
} = {}) {
    const domain = _buildDomain({ userId, filterKey, search });

    const safePageSize = Math.max(parseInt(pageSize, 10) || 10, 1);
    let safePage = Math.max(parseInt(page, 10) || 1, 1);

    const total = await orm.searchCount('project.task', domain);
    const pages = total ? Math.max(Math.ceil(total / safePageSize), 1) : 1;
    safePage = Math.min(safePage, pages);

    const order = _buildOrder(sortKey, sortOrder);

    const records = await orm.searchRead(
        'project.task',
        domain,
        ['id', 'name', 'project_id', 'stage_id', 'state', 'create_date', 'date_deadline'],
        { order, limit: safePageSize, offset: (safePage - 1) * safePageSize },
    );

    const tasks = records.map((r) => ({
        id: r.id,
        task: r.name || '',
        project: r.project_id ? r.project_id[1] : '',
        stage: r.stage_id ? r.stage_id[1] : '',
        status: _STATE_LABELS[r.state] || r.state || '',
        state: r.state,
        assign_date: _fmtDate(r.create_date),
        deadline: _fmtDate(r.date_deadline),
        raw_deadline: r.date_deadline || null,
    }));

    return { tasks, total, page: safePage, pages };
}

export async function archiveTask(orm, taskId, userId) {
    // Safety: validate the task belongs to the current user (avoid archiving others)
    const allowed = await orm.searchCount('project.task', [
        ['id', '=', taskId],
        ['user_ids', 'in', [userId]],
    ]);
    if (!allowed) {
        return { ok: false, error: 'You are not allowed to archive this task.' };
    }

    try {
        await orm.write('project.task', [taskId], { active: false });
        return { ok: true };
    } catch (e) {
        return { ok: false, error: e.message || String(e) };
    }
}
