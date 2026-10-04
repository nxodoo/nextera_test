/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const PERIODS = [
    { days: 1, label: "24 hours" },
    { days: 7, label: "7 days" },
    { days: 30, label: "30 days" },
];

export class AuditDashboard extends Component {
    static template = "nx_audit_log.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;
        this.state = useState({ days: 1, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("audit.log", "get_dashboard_data", [], {
            days: this.state.days,
        });
    }

    async setPeriod(days) {
        this.state.days = days;
        await this.load();
    }

    get maxSource() {
        return Math.max(1, ...this.state.data.sources.map((s) => s.count));
    }

    barStyle(source) {
        return `width: ${Math.round((source.count * 100) / this.maxSource)}%`;
    }

    periodDomain() {
        return [["event_datetime", ">=", this.state.data.since]];
    }

    openLogs(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "audit.log",
            views: [[false, "list"], [false, "form"]],
            domain: [...this.periodDomain(), ...domain],
        });
    }

    openOperation(op) {
        this.openLogs(op.label, [["operation", "=", op.code]]);
    }

    openSource(source) {
        this.openLogs(source.label, [["source", "=", source.code]]);
    }

    openModel(row) {
        this.openLogs(row.model, [["model_name", "=", row.model]]);
    }

    openUser(row) {
        this.openLogs(row.name, [["user_id", "=", row.id]]);
    }

    openFailures() {
        this.openLogs("Failures", [["result", "=", "failure"]]);
    }

    openAlerts() {
        this.action.doAction("nx_audit_log.audit_alert_action");
    }

    openIntegrity() {
        this.action.doAction("nx_audit_log.audit_integrity_check_action");
    }

    openUnsealed() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Unsealed events",
            res_model: "audit.log",
            views: [[false, "list"], [false, "form"]],
            domain: [["seal_state", "=", "unsealed"]],
        });
    }

    formatBytes(bytes) {
        const units = ["B", "KB", "MB", "GB", "TB"];
        let value = bytes;
        let unit = 0;
        while (value >= 1024 && unit < units.length - 1) {
            value /= 1024;
            unit++;
        }
        return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
    }
}

registry.category("actions").add("nx_audit_log.dashboard", AuditDashboard);
