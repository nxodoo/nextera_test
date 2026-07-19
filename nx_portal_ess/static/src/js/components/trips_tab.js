/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { essApi, stateAccent, fmtMoney } from "../ess_service";

export class TripsTab extends Component {
    static template = "nx_portal_ess.TripsTab";
    static props = {};

    setup() {
        this.state = useState({
            loading: true,
            error: null,
            data: {},
            showForm: false,
            submitting: false,
            formError: null,
            form: { destination: "", purpose: "", date_from: "", date_to: "", estimated_cost: "" },
        });
        this.stateAccent = stateAccent;
        this.fmtMoney = fmtMoney;
        onWillStart(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            this.state.data = await essApi.trips();
        } catch (e) {
            this.state.error = e.message || "Failed to load trips.";
        }
        this.state.loading = false;
    }

    toggleForm() {
        this.state.showForm = !this.state.showForm;
        this.state.formError = null;
    }

    async submit() {
        const f = this.state.form;
        if (!f.destination || !f.date_from || !f.date_to) {
            this.state.formError = "Please fill in all required fields.";
            return;
        }
        this.state.submitting = true;
        this.state.formError = null;
        const res = await essApi.createTrip({ ...f, estimated_cost: parseFloat(f.estimated_cost || 0) });
        this.state.submitting = false;
        if (res.ok) {
            this.state.showForm = false;
            this.state.form = { destination: "", purpose: "", date_from: "", date_to: "", estimated_cost: "" };
            await this._load();
        } else {
            this.state.formError = res.error || "Could not submit the request.";
        }
    }
}
