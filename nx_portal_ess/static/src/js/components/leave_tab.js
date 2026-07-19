/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { essApi, stateAccent } from "../ess_service";

export class LeaveTab extends Component {
    static template = "nx_portal_ess.LeaveTab";
    static props = {};

    setup() {
        this.state = useState({
            loading: true,
            error: null,
            data: {},
            showForm: false,
            submitting: false,
            formError: null,
            form: { leave_type_id: "", date_from: "", date_to: "", name: "" },
        });
        this.stateAccent = stateAccent;
        onWillStart(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            this.state.data = await essApi.leaves();
        } catch (e) {
            this.state.error = e.message || "Failed to load leaves.";
        }
        this.state.loading = false;
    }

    toggleForm() {
        this.state.showForm = !this.state.showForm;
        this.state.formError = null;
    }

    async submit() {
        const f = this.state.form;
        if (!f.leave_type_id || !f.date_from || !f.date_to) {
            this.state.formError = "Please fill in all required fields.";
            return;
        }
        this.state.submitting = true;
        this.state.formError = null;
        const res = await essApi.createLeave({ ...f, leave_type_id: parseInt(f.leave_type_id) });
        this.state.submitting = false;
        if (res.ok) {
            this.state.showForm = false;
            this.state.form = { leave_type_id: "", date_from: "", date_to: "", name: "" };
            await this._load();
        } else {
            this.state.formError = res.error || "Could not submit the request.";
        }
    }
}
