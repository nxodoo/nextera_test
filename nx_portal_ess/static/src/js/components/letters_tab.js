/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { essApi, stateAccent } from "../ess_service";

export class LettersTab extends Component {
    static template = "nx_portal_ess.LettersTab";
    static props = {};

    setup() {
        this.state = useState({
            loading: true,
            error: null,
            data: {},
            showForm: false,
            submitting: false,
            formError: null,
            form: { letter_type: "", addressed_to: "", reason: "" },
        });
        this.stateAccent = stateAccent;
        onWillStart(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            this.state.data = await essApi.letters();
        } catch (e) {
            this.state.error = e.message || "Failed to load letter requests.";
        }
        this.state.loading = false;
    }

    toggleForm() {
        this.state.showForm = !this.state.showForm;
        this.state.formError = null;
    }

    async submit() {
        if (!this.state.form.letter_type) {
            this.state.formError = "Please choose a letter type.";
            return;
        }
        this.state.submitting = true;
        this.state.formError = null;
        const res = await essApi.createLetter({ ...this.state.form });
        this.state.submitting = false;
        if (res.ok) {
            this.state.showForm = false;
            this.state.form = { letter_type: "", addressed_to: "", reason: "" };
            await this._load();
        } else {
            this.state.formError = res.error || "Could not submit the request.";
        }
    }
}
