/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { essApi, stateAccent, fmtMoney } from "../ess_service";

export class PayrollTab extends Component {
    static template = "nx_portal_ess.PayrollTab";
    static props = {};

    setup() {
        this.state = useState({
            loading: true,
            error: null,
            data: {},
            detail: null,
            detailLoading: false,
        });
        this.stateAccent = stateAccent;
        this.fmtMoney = fmtMoney;
        onWillStart(async () => {
            try {
                this.state.data = await essApi.payslips();
            } catch (e) {
                this.state.error = e.message || "Failed to load payslips.";
            }
            this.state.loading = false;
        });
    }

    async openDetail(slipId) {
        this.state.detailLoading = true;
        this.state.detail = { open: true };
        const res = await essApi.payslipDetail(slipId);
        this.state.detailLoading = false;
        this.state.detail = res.ok ? { open: true, ...res } : { open: true, error: res.error };
    }

    closeDetail() {
        this.state.detail = null;
    }
}
