/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { essApi } from "../ess_service";

export class AttendanceTab extends Component {
    static template = "nx_portal_ess.AttendanceTab";
    static props = {};

    setup() {
        this.state = useState({ loading: true, error: null, data: {} });
        onWillStart(async () => {
            try {
                this.state.data = await essApi.attendance();
            } catch (e) {
                this.state.error = e.message || "Failed to load attendance.";
            }
            this.state.loading = false;
        });
    }

    get summary() {
        return this.state.data.summary || {};
    }
}
