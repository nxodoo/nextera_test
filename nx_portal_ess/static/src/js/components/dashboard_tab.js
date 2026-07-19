/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { essApi, stateAccent } from "../ess_service";

export class DashboardTab extends Component {
    static template = "nx_portal_ess.DashboardTab";
    static props = { setTab: { type: Function, optional: true } };

    setup() {
        this.state = useState({ loading: true, error: null, data: {} });
        this.stateAccent = stateAccent;
        onWillStart(async () => {
            try {
                this.state.data = await essApi.dashboard();
            } catch (e) {
                this.state.error = e.message || "Failed to load dashboard.";
            }
            this.state.loading = false;
        });
    }

    get kpis() {
        return this.state.data.kpis || {};
    }

    open(tab) {
        if (this.props.setTab) {
            this.props.setTab(tab);
        }
    }
}
