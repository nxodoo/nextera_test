/** @odoo-module **/
import {Component, useState, onWillStart} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {user} from "@web/core/user";
import {LeaveFilters} from "./leave_filters";
import {LeaveTable} from "./leave_table";
import {LeavePagination} from "./leave_pagination";
import {fetchLeaves, cancelLeave, fetchEmployeeId} from "./leave_service";

// ── debounce helper ──────────────────────────────────────────────────────────
function debounce(fn, ms = 350) {
    let t;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), ms);
    };
}

export class LeaveTableApp extends Component {
    static template = "nx_analytics_widgets.LeaveTableApp";
    static components = {LeaveFilters, LeaveTable, LeavePagination};
    static props = ["*"];

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            page: 1,
            pageSize: 10,
            stateFilter: '',
            sortOrder: 'desc',
            search: '',
            leaves: [],
            total: 0,
            pages: 1,
            loading: true,
            error: null,
        });

        this._employeeId = null;

        this._debouncedSearch = debounce(async (val) => {
            this.state.search = val;
            this.state.page = 1;
            await this._load();
        }, 350);

        onWillStart(async () => {
            this._employeeId = await fetchEmployeeId(this.orm, user.userId);
            await this._load();
        });
    }

    async _load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await fetchLeaves(this.orm, {
                employeeId: this._employeeId,
                userId: user.userId,
                page: this.state.page,
                pageSize: this.state.pageSize,
                stateFilter: this.state.stateFilter,
                sortOrder: this.state.sortOrder,
                search: this.state.search,
            });
            Object.assign(this.state, {
                leaves: result.leaves,
                total: result.total,
                page: result.page,
                pages: result.pages,
            });
        } catch (e) {
            this.state.error = e.message || 'Failed to load leave data.';
        } finally {
            this.state.loading = false;
        }
    }

    async onFilter(key) {
        this.state.stateFilter = key;
        this.state.page = 1;
        await this._load();
    }

    async onSort() {
        this.state.sortOrder = this.state.sortOrder === 'desc' ? 'asc' : 'desc';
        this.state.page = 1;
        await this._load();
    }

    onSearch(value) {
        this._debouncedSearch(value);
    }

    async onPageChange(n) {
        this.state.page = n;
        await this._load();
    }

    async onCancel(leaveId) {
        if (!confirm('Cancel this leave request?')) return;
        const res = await cancelLeave(this.orm, leaveId);
        if (res && res.ok) {
            await this._load();
        } else {
            alert((res && res.error) || 'Could not cancel the leave.');
        }
    }
}

// ── Register in public_components so Odoo mounts it via <owl-component> ─────
registry.category("public_components").add("nx.LeaveTableApp", LeaveTableApp);
