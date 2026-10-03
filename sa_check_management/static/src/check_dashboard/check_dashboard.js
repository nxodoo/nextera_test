/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";
import { Component, onWillStart, useState } from "@odoo/owl";

const GAUGE_CIRCUMFERENCE = 439.82; // 2 * PI * r(70), matches the SVG radius of the template

/**
 * Treasury dashboard for checks. Data comes from check.check.get_dashboard_data():
 * every KPI is {amount, count, domain}; clicking a card opens the matching checks.
 */
export class CheckDashboard extends Component {
    static template = "sa_check_management.CheckDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({ data: null, loading: true });
        this.rows = [
            [
                { key: "incoming_outstanding", label: _t("Incoming Outstanding"), icon: "fa-arrow-down", color: "blue" },
                { key: "under_collection", label: _t("Under Collection"), icon: "fa-university", color: "cyan" },
                { key: "matured_not_deposited", label: _t("Matured, Not Deposited"), icon: "fa-hourglass-end", color: "teal" },
                { key: "incoming_due_today", label: _t("In · Due Today"), icon: "fa-calendar-check-o", color: "yellow" },
                { key: "incoming_due_week", horizon: "mid", label: _t("In · Next %s Days"), icon: "fa-calendar", color: "purple" },
                { key: "incoming_due_month", horizon: "long", label: _t("In · Next %s Days"), icon: "fa-calendar-o", color: "magenta" },
            ],
            [
                { key: "outgoing_outstanding", label: _t("Outgoing Outstanding"), icon: "fa-arrow-up", color: "blue" },
                { key: "awaiting_approval", label: _t("Awaiting Approval"), icon: "fa-gavel", color: "cyan" },
                { key: "outgoing_due_today", label: _t("Out · Due Today"), icon: "fa-calendar-check-o", color: "teal" },
                { key: "outgoing_due_week", horizon: "mid", label: _t("Out · Next %s Days"), icon: "fa-calendar", color: "yellow" },
                { key: "outgoing_due_month", horizon: "long", label: _t("Out · Next %s Days"), icon: "fa-calendar-o", color: "purple" },
                { key: "bounced", label: _t("Bounced"), icon: "fa-exclamation-triangle", color: "magenta" },
            ],
            [
                { key: "guarantees_held", label: _t("Guarantees Held"), icon: "fa-shield", color: "teal" },
                { key: "unallocated", label: _t("Unallocated"), icon: "fa-random", color: "yellow", noCount: true },
            ],
        ];
        this.panels = [
            {
                key: "legal_cases", title: _t("Legal Cases"), icon: "fa-balance-scale", color: "magenta",
                subtitle: _t("Bounced checks with a lawyer or court, oldest first"),
                daysLabel: _t("days"), empty: _t("No open legal cases."), report: true,
            },
            {
                key: "discounted", title: _t("Discounted at Bank"), icon: "fa-percent", color: "purple",
                subtitle: _t("Contingent until maturity, nearest due first"),
                daysLabel: _t("days to due"), empty: _t("No discounted checks."),
            },
        ];
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("check.check", "get_dashboard_data", []);
        this.state.loading = false;
    }

    // ------------------------------------------------------------------
    // Formatting
    // ------------------------------------------------------------------
    money(value) {
        return formatMonetary(value || 0, { currencyId: this.state.data.currency.id });
    }

    kpi(key) {
        return this.state.data[key] || { amount: 0, count: 0 };
    }

    cardLabel(card) {
        return card.horizon ? card.label.replace("%s", this.state.data.horizons[card.horizon]) : card.label;
    }

    get gaugeOffset() {
        const percent = Math.max(0, Math.min(100, this.state.data.collection_rate.percent || 0));
        return GAUGE_CIRCUMFERENCE * (1 - percent / 100);
    }

    get maxFlow() {
        const values = this.state.data.cash_flow.flatMap((row) => [row.incoming, row.outgoing]);
        return Math.max(1, ...values);
    }

    barWidth(value) {
        return Math.round(((value || 0) / this.maxFlow) * 100);
    }

    monthLabel(row) {
        if (row.month === "overdue") {
            return _t("Overdue");
        }
        return luxon.DateTime.fromISO(row.month).toFormat("LLL yyyy");
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------
    openKpi(card) {
        const kpi = this.kpi(card.key);
        if (!kpi.domain) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: this.cardLabel(card),
            res_model: "check.check",
            views: [[false, "list"], [false, "form"]],
            domain: kpi.domain,
            context: { create: false },
        });
    }

    openPanel(key, title) {
        this.openKpi({ key, label: title });
    }

    openCheck(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "check.check",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openLegalReport() {
        this.actionService.doAction("sa_check_management.action_check_legal_cases");
    }

    openCashFlow() {
        this.actionService.doAction("sa_check_management.action_check_cash_flow");
    }

    openMaturity() {
        this.actionService.doAction("sa_check_management.action_check_aging");
    }
}

registry.category("actions").add("sa_check_dashboard", CheckDashboard);
