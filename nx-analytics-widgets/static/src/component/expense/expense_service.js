/** @odoo-module **/

// ── Expense ORM Service ──────────────────────────────────────────────────────
// Uses the ORM service (useService('orm')) for portal OWL component.
// Provides pagination, filters, search, sorting, and delete action.

function _fmtDate(str) {
    if (!str) return null;
    const d = new Date(str);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: '2-digit' });
}

const _STATE_LABELS = {
    draft:     'To Report',
    reported:  'To Submit',
    submitted: 'Submitted',
    approved:  'Approved',
    done:      'Done',
    refused:   'Refused',
};

const _PAYMENT_MODE_LABELS = {
    own_account:     'Employee (to reimburse)',
    company_account: 'Company',
};

const _STATE_MAP = {
    draft:     ['draft'],
    reported:  ['reported'],
    submitted: ['submitted'],
    approved:  ['approved'],
    done:      ['done'],
    refused:   ['refused'],
};

const _DELETABLE_STATES = new Set(['draft', 'reported']);

// ── Resolve employee id from user ────────────────────────────────────────────
export async function fetchEmployeeId(orm, userId) {
    const rows = await orm.searchRead(
        'hr.employee',
        [['user_id', '=', userId]],
        ['id'],
        { limit: 1 },
    );
    return rows.length ? rows[0].id : null;
}

// ── Domain builder ───────────────────────────────────────────────────────────
function _buildDomain(employeeId, userId, stateFilter, search) {
    let domain = employeeId
        ? [['employee_id', '=', employeeId]]
        : [['employee_id.user_id', '=', userId]];

    if (stateFilter && _STATE_MAP[stateFilter]) {
        domain.push(['state', 'in', _STATE_MAP[stateFilter]]);
    }

    if (search && search.trim()) {
        const q = search.trim();
        domain = [
            '|',
            ['name', 'ilike', q],
            ['product_id.name', 'ilike', q],
            ...domain,
        ];
    }

    return domain;
}

// ── Sort order builder ───────────────────────────────────────────────────────
function _buildOrder(sortKey, sortOrder) {
    const dir = sortOrder === 'asc' ? 'asc' : 'desc';
    switch (sortKey) {
        case 'date':
            return `date ${dir}, id desc`;
        case 'amount':
            return `total_amount_currency ${dir}, id desc`;
        case 'state':
            return `state ${dir}, id desc`;
        default:
            return `date ${dir}, id desc`;
    }
}

// ── Fetch expenses ───────────────────────────────────────────────────────────
export async function fetchExpenses(orm, {
    employeeId, userId,
    page = 1, pageSize = 10,
    stateFilter = '', search = '',
    sortKey = 'date', sortOrder = 'desc',
} = {}) {
    const domain = _buildDomain(employeeId, userId, stateFilter, search);

    const safePageSize = Math.max(parseInt(pageSize, 10) || 10, 1);
    let safePage = Math.max(parseInt(page, 10) || 1, 1);

    const total = await orm.searchCount('hr.expense', domain);
    const pages = total ? Math.max(Math.ceil(total / safePageSize), 1) : 1;
    safePage = Math.min(safePage, pages);

    const order = _buildOrder(sortKey, sortOrder);

    const records = await orm.searchRead(
        'hr.expense',
        domain,
        [
            'id', 'name', 'date', 'product_id',
            'total_amount_currency', 'currency_id',
            'payment_mode', 'state',
        ],
        { order, limit: safePageSize, offset: (safePage - 1) * safePageSize },
    );

    const expenses = records.map((r) => ({
        id:            r.id,
        description:   r.name || '',
        date:          _fmtDate(r.date),
        raw_date:      r.date || null,
        category:      r.product_id ? r.product_id[1] : '',
        amount:        Math.round((r.total_amount_currency || 0) * 100) / 100,
        currency:      r.currency_id ? r.currency_id[1] : '',
        paid_by:       _PAYMENT_MODE_LABELS[r.payment_mode] || r.payment_mode || '',
        payment_mode:  r.payment_mode || '',
        state:         r.state,
        state_label:   _STATE_LABELS[r.state] || r.state,
        can_edit:      r.state === 'draft',
        can_delete:    _DELETABLE_STATES.has(r.state),
    }));

    return { expenses, total, page: safePage, pages };
}

// ── Fetch form lookup data (categories, currencies, taxes, accounts, vendors) ─
export async function fetchExpenseFormData(orm) {
    const [categories, currencies, taxes, accounts, vendors] = await Promise.all([
        orm.searchRead(
            'product.product',
            [['can_be_expensed', '=', true]],
            ['id', 'name'],
            { order: 'name asc' },
        ),
        orm.searchRead(
            'res.currency',
            [['active', '=', true]],
            ['id', 'name', 'symbol'],
            { order: 'name asc' },
        ),
        orm.searchRead(
            'account.tax',
            [['type_tax_use', '=', 'purchase']],
            ['id', 'name'],
            { order: 'name asc' },
        ),
        orm.searchRead(
            'account.account',
            [['deprecated', '=', false]],
            ['id', 'name'],
            { order: 'name asc' },
        ),
        orm.searchRead(
            'res.partner',
            [['supplier_rank', '>', 0]],
            ['id', 'name'],
            { order: 'name asc' },
        ),
    ]);
    return { categories, currencies, taxes, accounts, vendors };
}

// ── Fetch single expense for view / edit ─────────────────────────────────────
export async function fetchExpenseDetail(orm, expenseId, employeeId) {
    const records = await orm.searchRead(
        'hr.expense',
        [['id', '=', expenseId], ['employee_id', '=', employeeId]],
        [
            'id', 'name', 'date', 'product_id',
            'total_amount_currency', 'currency_id',
            'payment_mode', 'state',
            'tax_ids', 'account_id', 'vendor_id',
            'employee_id',
        ],
        { limit: 1 },
    );
    if (!records.length) return null;
    const r = records[0];
    return {
        id:            r.id,
        name:          r.name || '',
        date:          r.date || '',
        product_id:    r.product_id ? r.product_id[0] : false,
        product_name:  r.product_id ? r.product_id[1] : '',
        amount:        r.total_amount_currency || 0,
        currency_id:   r.currency_id ? r.currency_id[0] : false,
        currency_name: r.currency_id ? r.currency_id[1] : '',
        payment_mode:  r.payment_mode || 'own_account',
        state:         r.state,
        state_label:   _STATE_LABELS[r.state] || r.state,
        tax_ids:       r.tax_ids || [],
        account_id:    r.account_id ? r.account_id[0] : false,
        account_name:  r.account_id ? r.account_id[1] : '',
        vendor_id:     r.vendor_id ? r.vendor_id[0] : false,
        vendor_name:   r.vendor_id ? r.vendor_id[1] : '',
        can_edit:      r.state === 'draft',
    };
}

// ── Create expense ───────────────────────────────────────────────────────────
export async function createExpense(orm, employeeId, vals) {
    try {
        const data = {
            name:                  vals.name,
            product_id:            vals.product_id || false,
            total_amount_currency: parseFloat(vals.amount) || 0,
            date:                  vals.date || false,
            currency_id:           vals.currency_id || false,
            payment_mode:          vals.payment_mode || 'own_account',
            employee_id:           employeeId,
        };
        if (vals.tax_ids && vals.tax_ids.length) {
            data.tax_ids = [[6, 0, vals.tax_ids]];
        } else {
            data.tax_ids = [[5, 0, 0]];
        }
        if (vals.account_id) {
            data.account_id = vals.account_id;
        }
        if (vals.payment_mode === 'company_account' && vals.vendor_id) {
            data.vendor_id = vals.vendor_id;
        }
        const expenseId = await orm.create('hr.expense', [data]);
        return { ok: true, id: expenseId };
    } catch (e) {
        return { ok: false, error: e.message || String(e) };
    }
}

// ── Update expense ───────────────────────────────────────────────────────────
export async function updateExpense(orm, expenseId, employeeId, vals) {
    // Safety: only draft expenses can be edited
    const allowed = await orm.searchCount('hr.expense', [
        ['id', '=', expenseId],
        ['employee_id', '=', employeeId],
        ['state', '=', 'draft'],
    ]);
    if (!allowed) {
        return { ok: false, error: 'This expense cannot be edited.' };
    }
    try {
        const data = {
            name:                  vals.name,
            product_id:            vals.product_id || false,
            total_amount_currency: parseFloat(vals.amount) || 0,
            date:                  vals.date || false,
            currency_id:           vals.currency_id || false,
            payment_mode:          vals.payment_mode || 'own_account',
        };
        if (vals.tax_ids && vals.tax_ids.length) {
            data.tax_ids = [[6, 0, vals.tax_ids]];
        } else {
            data.tax_ids = [[5, 0, 0]];
        }
        if (vals.account_id) {
            data.account_id = vals.account_id;
        } else {
            data.account_id = false;
        }
        if (vals.payment_mode === 'company_account' && vals.vendor_id) {
            data.vendor_id = vals.vendor_id;
        } else {
            data.vendor_id = false;
        }
        await orm.write('hr.expense', [expenseId], data);
        return { ok: true };
    } catch (e) {
        return { ok: false, error: e.message || String(e) };
    }
}

// ── Delete expense ───────────────────────────────────────────────────────────
export async function deleteExpense(orm, expenseId, employeeId) {
    // Safety: verify expense belongs to the employee and is in deletable state
    const allowed = await orm.searchCount('hr.expense', [
        ['id', '=', expenseId],
        ['employee_id', '=', employeeId],
        ['state', 'in', [..._DELETABLE_STATES]],
    ]);
    if (!allowed) {
        return { ok: false, error: 'You are not allowed to delete this expense or it is no longer in draft state.' };
    }

    try {
        await orm.unlink('hr.expense', [expenseId]);
        return { ok: true };
    } catch (e) {
        return { ok: false, error: e.message || String(e) };
    }
}

