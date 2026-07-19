/** @odoo-module **/

import {Component, useState, onWillStart} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {user} from "@web/core/user";

import {TaskProjectsSection} from "./task_projects_section";
import {defaultPipeline, fetchTaskDashboard} from "./task_service";

export class TaskDashboardApp extends Component {
    static template = "nx_analytics_widgets.TaskChartDashboardApp";
    static components = {TaskProjectsSection};
    static props = ["*"];

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            loading: true,
            error: null,
            projects: [],
            pipeline: defaultPipeline,
            deadlines: {
                delayed: 0,
                todayCount: 0,
                upcoming: 0,
                noDeadline: 0,
            },
        });

        onWillStart(async () => {
            await this._load();
        });
    }

    async _load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await fetchTaskDashboard(this.orm, user.userId);
            // Keep only counters here; projects moved to TaskProjectsSection component.
            this.state = {
                ...this.state,
                ...result,
                loading: false,
            }
        } catch (e) {
            this.state.error = e.message || "Failed to load task dashboard.";
            this.state.loading = false;
        }
    }
}

registry.category("public_components").add("nx.TaskDashboardApp", TaskDashboardApp);
