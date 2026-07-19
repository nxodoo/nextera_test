/** @odoo-module **/

import {Component, useState, onWillStart} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {user} from "@web/core/user";

import {OpenTaskFilters} from "./open_task_filters";
import {OpenTaskTable} from "./open_task_table";
import {OpenTaskPagination} from "./open_task_pagination";
import {fetchOpenTasks, archiveTask} from "./open_task_service";


export class OpenTaskTableApp extends Component {
    static template = "nx_analytics_widgets.OpenTaskTableApp";
    static components = {OpenTaskFilters, OpenTaskTable, OpenTaskPagination};
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            page: 1,
            pageSize: 10,
            filterKey: '',
            search: '',
            sortKey: 'deadline',
            sortOrder: 'asc',
            tasks: [],
            total: 0,
            pages: 1,
            loading: true,
            error: null,
        });

        onWillStart(async () => {
            await this._load();
        });
    }

    async _load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await fetchOpenTasks(this.orm, {
                userId: user.userId,
                page: this.state.page,
                pageSize: this.state.pageSize,
                filterKey: this.state.filterKey,
                search: this.state.search,
                sortKey: this.state.sortKey,
                sortOrder: this.state.sortOrder,
            });
            Object.assign(this.state, {
                tasks: result.tasks,
                total: result.total,
                page: result.page,
                pages: result.pages,
            });
        } catch (e) {
            this.state.error = e.message || 'Failed to load tasks.';
        } finally {
            this.state.loading = false;
        }
    }

    async onFilter(key) {
        this.state.filterKey = key;
        this.state.page = 1;
        await this._load();
    }

    async onPageChange(n) {
        this.state.page = n;
        await this._load();
    }

    async onApplySearch(val) {
        this.state.search = val;
        this.state.page = 1;
        await this._load();
    }

    async onSortKey(key) {
        this.state.sortKey = key;
        this.state.page = 1;
        await this._load();
    }

    async onSortOrder() {
        this.state.sortOrder = this.state.sortOrder === 'desc' ? 'asc' : 'desc';
        this.state.page = 1;
        await this._load();
    }

    async onArchive(taskId) {
        const res = await archiveTask(this.orm, taskId, user.userId);
        if (res && res.ok) {
            await this._load();
            this.notification.add("Archived successfully", {
                type: "success",
            });
        } else {
            this.notification.add((res && res.error) || 'Could not archive the task.', {
                type: "danger",
            });
        }
    }
}

registry.category("public_components").add("nx.OpenTaskTableApp", OpenTaskTableApp);
