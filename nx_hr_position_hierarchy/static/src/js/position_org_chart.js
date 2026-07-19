/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

class PositionOrgChartNode extends Component {
    static template = "nx_hr_position_hierarchy.PositionOrgChartNode";
    static props = {
        node: Object,
        openJob: Function,
    };
}

PositionOrgChartNode.components = { PositionOrgChartNode };

export class PositionOrgChart extends Component {
    static template = "nx_hr_position_hierarchy.PositionOrgChart";
    static components = { PositionOrgChartNode };

    setup() {
        this.action = useService("action");
        this.state = useState({
            departments: [],
            levels: [],
            nodes: [],
            summary: {},
            departmentId: "",
            level: "",
            showVacant: true,
            loading: true,
        });
        this.rootJobId = this.props.action.params?.root_job_id || false;

        onWillStart(async () => {
            await this.loadOptions();
            await this.loadChart();
        });
    }

    async loadOptions() {
        const options = await rpc("/nx_hr_position_hierarchy/options", {});
        this.state.departments = options.departments;
        this.state.levels = options.levels;
    }

    async loadChart() {
        this.state.loading = true;
        const chart = await rpc("/nx_hr_position_hierarchy/chart", {
            department_id: this.state.departmentId || false,
            level: this.state.level || false,
            show_vacant: this.state.showVacant,
            root_job_id: this.rootJobId,
        });
        this.state.nodes = chart.nodes;
        this.state.summary = chart.summary;
        this.state.loading = false;
    }

    async onDepartmentChange(ev) {
        this.state.departmentId = ev.target.value;
        await this.loadChart();
    }

    async onLevelChange(ev) {
        this.state.level = ev.target.value;
        await this.loadChart();
    }

    async onShowVacantChange(ev) {
        this.state.showVacant = ev.target.checked;
        await this.loadChart();
    }

    openJob(jobId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.job",
            res_id: jobId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("nx_position_org_chart", PositionOrgChart);
