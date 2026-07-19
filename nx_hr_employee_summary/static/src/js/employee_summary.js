/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

/**
 * Renders one block of the Employee Summary dashboard from the
 * `nx_summary_data_json` computed field. The `part` prop selects which
 * block to render: exec | career | compensation | attendance.
 */
export class EmployeeSummary extends Component {
    static template = "nx_hr_employee_summary.EmployeeSummary";

    static props = {
        part: { type: String, optional: true },
        record: { type: Object, optional: true },
        "*": true,
    };

    get data() {
        const raw = this.props.record?.data?.nx_summary_data_json;
        if (!raw) {
            return {};
        }
        try {
            return JSON.parse(raw);
        } catch (e) {
            return {};
        }
    }

    get part() {
        return this.props.part || "exec";
    }

    // ---- exec helpers -------------------------------------------------
    get recommendationClass() {
        const key = this.data.exec?.recommendation_key || "review";
        return {
            renew: "nx_rec_renew",
            review: "nx_rec_review",
            terminate: "nx_rec_terminate",
        }[key] || "nx_rec_review";
    }

    pctClass(pct) {
        return pct > 0 ? "nx_pct_pos" : pct < 0 ? "nx_pct_neg" : "nx_pct_zero";
    }

    pctLabel(pct) {
        if (!pct) {
            return "";
        }
        return (pct > 0 ? "+" : "") + Math.round(pct) + "%";
    }
}

registry.category("view_widgets").add("nx_summary", {
    component: EmployeeSummary,
    extractProps: ({ attrs }) => ({ part: attrs.part }),
});
