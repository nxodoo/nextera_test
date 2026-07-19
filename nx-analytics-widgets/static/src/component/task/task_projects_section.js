/** @odoo-module **/

import {Component, useState, onWillStart} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
import {user} from "@web/core/user";

import {TaskProjectChart} from "./task_project_chart";
import {fetchDataTasksCount} from "./task_service";


/**
 * Right-column section: loads and renders projects doughnut + details panel.
 *
 * By default, it loads for the current logged-in user; you can override via props.userId.
 */
export class TaskProjectsSection extends Component {
    static template = "nx_analytics_widgets.TaskProjectsSection";
    static components = {TaskProjectChart};
    static props = {
        userId: {type: Number, optional: true},
        projects: {type: Array, optional: true},
    };

    setup() {
        this.orm = useService("orm");


        this.state = useState({
            loading: true,
            error: null,
            projects: [],
        });

        onWillStart(async () => {
            await this._load();
        });
    }

    get effectiveUserId() {
        return this.props.userId ?? user.userId;
    }

    async _load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            if (this.props.projects && this.props.projects.length > 0) {
                this.state.projects = this.props.projects;
            } else {
                this.state.projects = await this.fetchData();
            }
        } catch (e) {
            this.state.error = e.message || "Failed to load projects overview.";
        } finally {
            this.state.loading = false;
        }
    }

    async fetchData() {

        const {project: tasksCount = []} = await fetchDataTasksCount(this.orm, this.effectiveUserId);

        return tasksCount;

    }

}
