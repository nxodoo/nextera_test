/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import {
    areaGradient,
    barValueLabels,
    baseOptions,
    categoryAxis,
    entryAnimation,
    prefersReducedMotion,
    readTokens,
    shortLabel,
    tooltipStyle,
    valueAxis,
    withAlpha,
} from "./chart_theme";

export class HrAnalyticsDashboard extends Component {
    static template = "nx_hr_analytics_dashboard.HrAnalyticsDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this._charts = {};

        this.state = useState({
            loading: true,
            activeTab: "dashboard",
            filters: { company_id: false, department_id: false, month: false },
            data: null,
            payroll: null,
            payrollLoading: false,
            payrollSearch: "",
            documents: null,
            documentsLoading: false,
            docSearch: "",
            docFilter: "all",
            insurance: null,
            insuranceLoading: false,
            insSearch: "",
            insFilter: "all",
            // Per-chart "show the numbers instead" toggles (table-view twin).
            tableView: {},
        });

        // Root ref — the design tokens are declared on it, so it is the
        // reliable place to resolve them from even when a canvas is hidden.
        this.rootEl = useRef("root");

        // Canvas refs
        this.deptChart = useRef("deptChart");
        this.insuranceChart = useRef("insuranceChart");
        this.trendChart = useRef("trendChart");
        this.complianceChart = useRef("complianceChart");
        this.turnoverChart = useRef("turnoverChart");
        this.docComplianceChart = useRef("docComplianceChart");
        this.missingTypeChart = useRef("missingTypeChart");
        this.insStatusChart = useRef("insStatusChart");
        this.insTrendChart = useRef("insTrendChart");
        // New per-tab charts
        this.payTaxDeptChart = useRef("payTaxDeptChart");
        this.payGrossDeptChart = useRef("payGrossDeptChart");
        this.docDistChart = useRef("docDistChart");
        this.docMissingDeptChart = useRef("docMissingDeptChart");
        this.insUninsuredChart = useRef("insUninsuredChart");

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });
        // Render charts AFTER the DOM is patched (canvas refs exist) whenever
        // the active tab or any tab's dataset changes.
        useEffect(
            () => {
                this.renderCharts();
            },
            () => [
                this.state.activeTab,
                this.state.data,
                this.state.documents,
                this.state.insurance,
                // Re-create charts when a card flips back from table view.
                JSON.stringify(this.state.tableView),
            ],
        );
        onWillUnmount(() => this.destroyCharts());
    }

    // ── Data ────────────────────────────────────────────────────────────
    async loadData() {
        this.state.loading = true;
        const data = await this.orm.call(
            "nx.hr.dashboard.service", "get_dashboard_data", [this.state.filters]);
        this.state.data = data;
        this.state.loading = false;
    }

    async loadPayroll() {
        this.state.payrollLoading = true;
        this.state.payroll = await this.orm.call(
            "nx.hr.dashboard.service", "get_payroll_tax_data", [this.state.filters]);
        // Reflect the resolved month (defaults to previous month) in the picker.
        if (!this.state.filters.month && this.state.payroll?.month_value) {
            this.state.filters.month = this.state.payroll.month_value;
        }
        this.state.payrollLoading = false;
    }

    async loadDocuments() {
        this.state.documentsLoading = true;
        this.state.documents = await this.orm.call(
            "nx.hr.dashboard.service", "get_documents_data", [this.state.filters]);
        this.state.documentsLoading = false;
    }

    async loadInsurance() {
        this.state.insuranceLoading = true;
        this.state.insurance = await this.orm.call(
            "nx.hr.dashboard.service", "get_insurance_data", [this.state.filters]);
        this.state.insuranceLoading = false;
    }

    async applyFilters() {
        await this.loadData();
        if (this.state.activeTab === "payroll") {
            await this.loadPayroll();
        } else if (this.state.activeTab === "documents") {
            await this.loadDocuments();
        } else if (this.state.activeTab === "insurance") {
            await this.loadInsurance();
        }
        // Charts re-render via useEffect when the datasets above change.
    }

    onFilterChange(field, ev) {
        const val = ev.target.value;
        this.state.filters[field] = val ? parseInt(val, 10) : false;
        this.applyFilters();
    }

    onMonthChange(ev) {
        this.state.filters.month = ev.target.value || false;
        if (this.state.activeTab === "payroll") {
            this.loadPayroll();
        }
    }

    clearFilters() {
        this.state.filters = { company_id: false, department_id: false, month: false };
        this.state.payrollSearch = "";
        this.applyFilters();
    }

    setTab(tab) {
        this.state.activeTab = tab;
        // Dashboard charts re-render via useEffect (activeTab is a dependency).
        if (tab === "payroll" && !this.state.payroll) {
            this.loadPayroll();
        } else if (tab === "documents" && !this.state.documents) {
            this.loadDocuments();
        } else if (tab === "insurance" && !this.state.insurance) {
            this.loadInsurance();
        }
    }

    get payrollRows() {
        const rows = this.state.payroll?.rows || [];
        const q = (this.state.payrollSearch || "").trim().toLowerCase();
        if (!q) {
            return rows;
        }
        return rows.filter((r) =>
            (r.name || "").toLowerCase().includes(q) ||
            (r.code || "").toLowerCase().includes(q) ||
            (r.national_id || "").toLowerCase().includes(q));
    }

    statusLabel(s) {
        return {
            approved: "Approved", reviewed: "Reviewed", waiting: "Waiting",
            draft: "Draft", warning: "Review", error: "Error", cancelled: "Cancelled",
        }[s] || s;
    }

    exportDashboard() {
        window.print();
    }

    openEmployee(empId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            res_id: empId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openEmployeesFiltered(field, id, name) {
        if (!id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || "Employees",
            res_model: "hr.employee",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: [["active", "=", true], [field, "=", id]],
        });
    }

    // Filtered rows for the documents / insurance tables (client-side search).
    _filterRows(rows, query, statusKey, statusFilter) {
        const q = (query || "").trim().toLowerCase();
        return (rows || []).filter((r) => {
            if (statusFilter && statusFilter !== "all" && r[statusKey] !== statusFilter) {
                return false;
            }
            if (!q) {
                return true;
            }
            return (r.name || "").toLowerCase().includes(q) ||
                (r.code || "").toLowerCase().includes(q) ||
                (r.national_id || "").toLowerCase().includes(q);
        });
    }
    get docRows() {
        return this._filterRows(
            this.state.documents?.rows, this.state.docSearch, "status", this.state.docFilter);
    }
    get insRows() {
        return this._filterRows(
            this.state.insurance?.rows, this.state.insSearch, "status", this.state.insFilter);
    }

    // ── Formatting helpers ────────────────────────────────────────────────
    fmt(n) {
        return (n ?? 0).toLocaleString("en-US");
    }
    get kpis() {
        return this.state.data?.kpis || {};
    }
    get kpiCards() {
        const k = this.kpis;
        return [
            { key: "total", label: "Total Employees", value: k.total_employees,
              accent: "#1A5C3A", icon: "fa-users",
              sub: { kind: "delta", value: k.net_change ?? 0 }, clickable: true },
            { key: "active", label: "Active Employees", value: k.active_employees,
              accent: "#22C55E", icon: "fa-user-plus", clickable: true },
            { key: "new_hires", label: "New Hires", value: k.new_hires,
              accent: "#3B82F6", icon: "fa-user-plus",
              sub: { kind: "note", text: "this month" }, clickable: true },
            { key: "resignations", label: "Resignations", value: k.resignations,
              accent: "#F59E0B", icon: "fa-user-times",
              sub: { kind: "note", text: "this month" }, clickable: true },
            { key: "uninsured", label: "Uninsured", value: k.uninsured,
              accent: "#EF4444", icon: "fa-shield", clickable: true },
            { key: "missing_documents", label: "Missing Documents", value: k.missing_documents,
              accent: "#EF4444", icon: "fa-file-text-o", clickable: true },
        ];
    }

    _monthStart() {
        // Compute first-of-month without Date.now restrictions in this context.
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
    }

    openKpi(key) {
        const employees = (name, domain, ctx) => this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "hr.employee",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: domain || [],
            context: ctx || {},
        });
        switch (key) {
            case "total":
                return employees("Employees", []);
            case "active":
                return employees("Active Employees", [["active", "=", true]]);
            case "new_hires":
                return employees("New Hires (this month)",
                    [["create_date", ">=", this._monthStart()]]);
            case "resignations":
                return employees("Resignations (this month)",
                    [["departure_date", ">=", this._monthStart()]], { active_test: false });
            case "uninsured":
                return this.setTab("insurance");
            case "missing_documents":
                return this.action.doAction(
                    "nx_hr_analytics_dashboard.action_hr_employee_document");
            default:
                return undefined;
        }
    }

    // ── Charts ────────────────────────────────────────────────────────────
    destroyCharts() {
        for (const key of Object.keys(this._charts)) {
            this._charts[key]?.destroy();
            delete this._charts[key];
        }
    }

    _make(ref, key, config) {
        if (!ref.el || !window.Chart) {
            return;
        }
        this._charts[key]?.destroy();
        this._charts[key] = new window.Chart(ref.el, config);
    }

    /** Resolved colour tokens, read from CSS so light/dark live in one place. */
    _tokens(ref) {
        return readTokens(ref?.el || this.rootEl?.el || document.documentElement);
    }

    // ── Table-view twin ───────────────────────────────────────────────────
    toggleTableView(key) {
        this.state.tableView[key] = !this.state.tableView[key];
    }
    isTableView(key) {
        return !!this.state.tableView[key];
    }

    /** Rows for a chart's table twin, as [{label, value, pct}]. */
    tableRows(items) {
        const rows = items || [];
        const total = rows.reduce((s, r) => s + (r.value || 0), 0);
        return rows.map((r) => ({
            label: r.label,
            value: r.value || 0,
            pct: total ? Math.round(((r.value || 0) / total) * 100) : 0,
        }));
    }

    /**
     * Horizontal bars need vertical room per row, otherwise the labels get
     * squeezed. Grow the container with the number of bars instead of forcing
     * a fixed height that crops the axis band.
     */
    barBoxHeight(count, { row = 38, min = 132, pad = 28 } = {}) {
        return Math.max(min, (count || 0) * row + pad);
    }

    // ── Donut hero numbers (the value the donut is really about) ───────────
    _pct(part, total) {
        return total ? Math.round((part / total) * 100) : 0;
    }
    get insuranceHero() {
        const s = this.state.data?.social_insurance;
        if (!s) {
            return null;
        }
        const total = (s.insured || 0) + (s.not_insured || 0);
        return { value: this._pct(s.insured, total), caption: "insured" };
    }
    get complianceHero() {
        const c = this.state.data?.document_compliance;
        if (!c) {
            return null;
        }
        const total = (c.complete || 0) + (c.incomplete || 0) + (c.expired || 0);
        return { value: this._pct(c.complete, total), caption: "complete" };
    }
    get docComplianceHero() {
        const c = this.state.documents?.compliance;
        if (!c) {
            return null;
        }
        const total = (c.complete || 0) + (c.incomplete || 0) + (c.expired || 0);
        return { value: this._pct(c.complete, total), caption: "complete" };
    }
    get insStatusHero() {
        const s = this.state.insurance?.status;
        if (!s) {
            return null;
        }
        const total = (s.insured || 0) + (s.not_insured || 0);
        return { value: this._pct(s.insured, total), caption: "insured" };
    }

    /**
     * Shared doughnut config. Zero-value segments are dropped so the ring
     * never reads as a single solid colour, and a 2px surface gap separates
     * the remaining segments instead of a drawn border.
     */
    _donutConfig(ref, entries) {
        const t = this._tokens(ref);
        const live = (entries || []).filter((e) => (e.value || 0) > 0);
        return {
            type: "doughnut",
            data: {
                labels: live.map((e) => e.label),
                datasets: [{
                    data: live.map((e) => e.value),
                    backgroundColor: live.map((e) => e.color),
                    // 2px surface-coloured gap between segments (spacer rule).
                    borderColor: t.surface,
                    borderWidth: 2,
                    hoverBorderColor: t.surface,
                    hoverOffset: 6,
                    borderRadius: 4,
                }],
            },
            options: {
                ...baseOptions(t),
                cutout: "72%",
                animation: prefersReducedMotion()
                    ? { duration: 0 }
                    : { animateRotate: true, animateScale: true, duration: 850, easing: "easeOutQuart" },
                plugins: {
                    legend: { display: false },
                    tooltip: tooltipStyle(t, {
                        callbacks: {
                            label: (c) => {
                                const total = c.dataset.data.reduce((s, v) => s + v, 0);
                                const pct = total ? Math.round((c.raw / total) * 100) : 0;
                                return ` ${c.label}: ${this.fmt(c.raw)} (${pct}%)`;
                            },
                        },
                    }),
                },
            },
        };
    }

    /** Shared horizontal-bar config for a single-hue series. */
    _hBarConfig(ref, items, { color, onClick, stagger = 45 } = {}) {
        const t = this._tokens(ref);
        const hue = color || t.series;
        return {
            type: "bar",
            data: {
                labels: items.map((r) => shortLabel(r.label)),
                datasets: [{
                    data: items.map((r) => r.value),
                    // One series → one colour. Length already encodes magnitude.
                    backgroundColor: withAlpha(hue, 0.88),
                    hoverBackgroundColor: hue,
                    borderRadius: 4,
                    borderSkipped: false,
                    maxBarThickness: 22,
                }],
            },
            options: {
                ...baseOptions(t),
                indexAxis: "y",
                animation: entryAnimation({ stagger }),
                layout: { padding: { right: 44 } },
                onClick,
                onHover: (evt, els) => {
                    const target = evt?.native?.target;
                    if (onClick && target) {
                        target.style.cursor = els.length ? "pointer" : "default";
                    }
                },
                scales: {
                    x: {
                        ...valueAxis(t, { ticks: { display: false } }),
                        grid: { display: false },
                    },
                    y: categoryAxis(t, {
                        ticks: { color: t.text, font: { size: 12 }, padding: 6 },
                    }),
                },
                plugins: {
                    legend: { display: false },
                    tooltip: tooltipStyle(t, {
                        callbacks: {
                            // Tooltip shows the FULL name; the axis shows the leaf.
                            title: (c) => items[c[0].dataIndex]?.label ?? "",
                            label: (c) => ` ${this.fmt(c.raw)}`,
                        },
                    }),
                    nxBarValueLabels: { horizontal: true, color: t.text, format: (v) => this.fmt(v) },
                },
            },
            plugins: [barValueLabels],
        };
    }

    /**
     * Vertical bars — used for ordered bands (e.g. completeness 0→100%),
     * where left-to-right progression is part of the meaning. Short labels
     * only, so nothing needs rotating.
     */
    _vBarConfig(ref, items, { color, stagger = 55 } = {}) {
        const t = this._tokens(ref);
        const hue = color || t.series;
        return {
            type: "bar",
            data: {
                labels: items.map((r) => r.label),
                datasets: [{
                    data: items.map((r) => r.value),
                    backgroundColor: withAlpha(hue, 0.88),
                    hoverBackgroundColor: hue,
                    borderRadius: 4,
                    borderSkipped: false,
                    maxBarThickness: 54,
                }],
            },
            options: {
                ...baseOptions(t),
                animation: entryAnimation({ stagger }),
                layout: { padding: { top: 22 } },
                scales: {
                    y: { ...valueAxis(t, { ticks: { display: false } }), grid: { display: false } },
                    x: categoryAxis(t, { ticks: { color: t.text, font: { size: 12 } } }),
                },
                plugins: {
                    legend: { display: false },
                    tooltip: tooltipStyle(t, {
                        callbacks: { label: (c) => ` ${this.fmt(c.raw)} employees` },
                    }),
                    nxBarValueLabels: { horizontal: false, color: t.text, format: (v) => this.fmt(v) },
                },
            },
            plugins: [barValueLabels],
        };
    }

    /** Shared area-line config with a gradient fill. */
    _areaConfig(ref, trend, { color, yOpts = {}, onPointClick, tooltipSuffix = "" } = {}) {
        const t = this._tokens(ref);
        const hue = color || t.series;
        return {
            type: "line",
            data: {
                labels: trend.labels,
                datasets: [{
                    data: trend.values,
                    borderColor: hue,
                    backgroundColor: (c) => areaGradient(c.chart.ctx, c.chart.chartArea, hue),
                    fill: true,
                    // Monotone keeps the curve inside the data range — a plain
                    // tension spline can dip below zero on a rate that cannot
                    // be negative, inventing values that aren't in the data.
                    cubicInterpolationMode: "monotone",
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointBackgroundColor: hue,
                    pointBorderColor: t.surface,
                    pointBorderWidth: 2,
                    // Generous hit target — no pinpoint hovering.
                    pointHitRadius: 24,
                }],
            },
            options: {
                ...baseOptions(t),
                // Crosshair-style hover: nearest x, no need to hit the point.
                interaction: { mode: "index", intersect: false },
                onClick: onPointClick
                    ? (evt, els, chart) => {
                        // Use the index under the cursor, so the whole column
                        // is clickable rather than just the 5px marker.
                        const pts = chart.getElementsAtEventForMode(
                            evt, "index", { intersect: false }, true);
                        if (pts.length) {
                            onPointClick(pts[0].index);
                        }
                    }
                    : undefined,
                onHover: onPointClick
                    ? (evt) => {
                        const target = evt?.native?.target;
                        if (target) {
                            target.style.cursor = "pointer";
                        }
                    }
                    : undefined,
                scales: {
                    y: valueAxis(t, yOpts),
                    x: categoryAxis(t),
                },
                plugins: {
                    legend: { display: false },
                    tooltip: tooltipStyle(t, {
                        callbacks: { label: (c) => ` ${this.fmt(c.raw)}${tooltipSuffix}` },
                    }),
                },
            },
        };
    }

    renderCharts() {
        if (!window.Chart) {
            return;
        }
        const tab = this.state.activeTab;
        if (tab === "dashboard") {
            this._renderDashboardCharts();
        } else if (tab === "documents") {
            this._renderDocumentCharts();
        } else if (tab === "insurance") {
            this._renderInsuranceCharts();
        } else if (tab === "payroll") {
            this._renderPayrollCharts();
        }
    }

    _renderPayrollCharts() {
        if (!this.state.payroll) {
            return;
        }
        const t = this._tokens(this.payTaxDeptChart);
        const byTax = this.payTaxByDept;
        if (byTax.length && !this.isTableView("payTaxDept")) {
            this._make(this.payTaxDeptChart, "payTaxDept",
                this._hBarConfig(this.payTaxDeptChart, byTax, { color: t.critical }));
        }
        const byGross = this.payGrossByDept;
        if (byGross.length && !this.isTableView("payGrossDept")) {
            this._make(this.payGrossDeptChart, "payGrossDept",
                this._hBarConfig(this.payGrossDeptChart, byGross, { color: t.series }));
        }
    }

    _renderDashboardCharts() {
        const data = this.state.data;
        if (!data) {
            return;
        }
        const t = this._tokens(this.deptChart);

        // Headcount by Department — horizontal bars. Vertical bars forced the
        // long department paths into colliding 45° labels; one row per
        // department gives each name a horizontal line of its own.
        const dept = data.headcount_by_department || [];
        if (!this.isTableView("dept")) {
            this._make(this.deptChart, "dept", this._hBarConfig(this.deptChart, dept, {
                onClick: (evt, els) => {
                    if (els.length) {
                        const d = dept[els[0].index];
                        this.openEmployeesFiltered("department_id", d && d.id, d && d.label);
                    }
                },
            }));
        }

        // Social Insurance — doughnut
        const ins = data.social_insurance;
        if (ins && !this.isTableView("insurance")) {
            this._make(this.insuranceChart, "insurance",
                this._donutConfig(this.insuranceChart, [
                    { label: "Insured", value: ins.insured, color: t.good },
                    { label: "Not Insured", value: ins.not_insured, color: t.critical },
                ]));
        }

        // Document Compliance — doughnut
        const comp = data.document_compliance;
        if (comp && !this.isTableView("compliance")) {
            this._make(this.complianceChart, "compliance",
                this._donutConfig(this.complianceChart, [
                    { label: "Complete", value: comp.complete, color: t.good },
                    { label: "Incomplete", value: comp.incomplete, color: t.warning },
                    { label: "Expired", value: comp.expired, color: t.critical },
                ]));
        }

        // Headcount Trend — gradient area line
        const trend = data.headcount_trend || { labels: [], values: [] };
        if (!this.isTableView("trend")) {
            this._make(this.trendChart, "trend",
                this._areaConfig(this.trendChart, trend, { color: t.series }));
        }

        // Turnover — gradient area line
        const turn = data.turnover_trend || { labels: [], values: [] };
        if (!this.isTableView("turnover")) {
            this._make(this.turnoverChart, "turnover",
                this._areaConfig(this.turnoverChart, turn, {
                    color: t.warning,
                    yOpts: { ticks: { callback: (v) => `${v}%` } },
                    tooltipSuffix: "%  ·  click to see who left",
                    onPointClick: (i) => this.openTurnoverMonth(i),
                }));
        }
    }

    _renderDocumentCharts() {
        const d = this.state.documents;
        if (!d) {
            return;
        }
        const t = this._tokens(this.docComplianceChart);
        const comp = d.compliance || {};
        if (!this.isTableView("docCompliance")) {
            this._make(this.docComplianceChart, "docCompliance",
                this._donutConfig(this.docComplianceChart, [
                    { label: "Complete", value: comp.complete, color: t.good },
                    { label: "Incomplete", value: comp.incomplete, color: t.warning },
                    { label: "Expired", value: comp.expired, color: t.critical },
                ]));
        }

        const byType = d.missing_by_type || [];
        if (!this.isTableView("missingType")) {
            this._make(this.missingTypeChart, "missingType",
                this._hBarConfig(this.missingTypeChart, byType, { color: t.warning }));
        }

        // How the workforce is spread across completeness bands — turns one
        // aggregate percentage into a shape you can actually act on.
        this._make(this.docDistChart, "docDist",
            this._vBarConfig(this.docDistChart, this.docDistribution, { color: t.series }));

        const byDept = this.docMissingByDept;
        if (byDept.length && !this.isTableView("docMissingDept")) {
            this._make(this.docMissingDeptChart, "docMissingDept",
                this._hBarConfig(this.docMissingDeptChart, byDept, { color: t.critical }));
        }
    }

    _renderInsuranceCharts() {
        const d = this.state.insurance;
        if (!d) {
            return;
        }
        const t = this._tokens(this.insStatusChart);
        const s = d.status || {};
        if (!this.isTableView("insStatus")) {
            this._make(this.insStatusChart, "insStatus",
                this._donutConfig(this.insStatusChart, [
                    { label: "Insured", value: s.insured, color: t.good },
                    { label: "Not Insured", value: s.not_insured, color: t.critical },
                ]));
        }

        const byDept = d.by_department || [];
        if (!this.isTableView("insByDept")) {
            this._make(this.insTrendChart, "insByDept",
                this._hBarConfig(this.insTrendChart, byDept, { color: t.series }));
        }

        // The actionable cut: who is still uncovered, and where.
        const uninsured = this.insUninsuredByDept;
        if (uninsured.length && !this.isTableView("insUninsured")) {
            this._make(this.insUninsuredChart, "insUninsured",
                this._hBarConfig(this.insUninsuredChart, uninsured, { color: t.critical }));
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    //  Derived views — everything below is computed from the rows the service
    //  already returns, so no extra RPC and no backend change is needed.
    // ══════════════════════════════════════════════════════════════════════

    /** Group any row list by a key, summing a numeric field. Sorted desc. */
    _groupSum(rows, keyField, valueField, { limit = 8 } = {}) {
        const acc = new Map();
        for (const r of rows || []) {
            const key = r[keyField] || "Undefined";
            acc.set(key, (acc.get(key) || 0) + (Number(r[valueField]) || 0));
        }
        const out = [...acc.entries()]
            .map(([label, value]) => ({ label, value: Math.round(value) }))
            .filter((r) => r.value > 0)
            .sort((a, b) => b.value - a.value);
        if (out.length <= limit) {
            return out;
        }
        // Never silently truncate — the tail is folded into an explicit "Other".
        const head = out.slice(0, limit - 1);
        const rest = out.slice(limit - 1).reduce((s, r) => s + r.value, 0);
        return [...head, { label: `Other (${out.length - limit + 1})`, value: rest }];
    }

    _pctOf(part, total) {
        return total ? Math.round((part / total) * 1000) / 10 : 0;
    }

    // ── Payroll Tax ───────────────────────────────────────────────────────
    /**
     * Where the gross wage actually goes. Net + tax + insurance + other
     * deductions reconstitute gross, so this is a true part-to-whole.
     */
    get payComposition() {
        const t = this.state.payroll?.totals;
        if (!t || !t.gross) {
            return null;
        }
        const segs = [
            { key: "net", label: "Net Salary", value: t.net || 0, cls: "o_cat1" },
            { key: "tax", label: "Tax Due", value: t.tax_due || 0, cls: "o_cat2" },
            { key: "ins", label: "Insurance", value: t.insurance || 0, cls: "o_cat3" },
            { key: "ded", label: "Deductions", value: t.deductions || 0, cls: "o_cat4" },
        ].filter((s) => s.value > 0);
        const sum = segs.reduce((s, x) => s + x.value, 0) || 1;
        return {
            gross: t.gross,
            segments: segs.map((s) => ({ ...s, pct: this._pctOf(s.value, sum) })),
        };
    }
    get payTaxByDept() {
        return this._groupSum(this.state.payroll?.rows, "department", "tax_due");
    }
    get payGrossByDept() {
        return this._groupSum(this.state.payroll?.rows, "department", "gross");
    }
    get payStats() {
        const p = this.state.payroll;
        if (!p) {
            return [];
        }
        const t = p.totals;
        const cur = p.currency;
        return [
            { key: "emp", label: "Employees", value: this.fmt(t.employees),
              icon: "fa-users", accent: "#1A5C3A" },
            { key: "gross", label: "Total Wages", value: this.fmt(t.gross), unit: cur,
              icon: "fa-money", accent: "#2a78d6" },
            { key: "exempt", label: "Exemptions", value: this.fmt(t.exemptions), unit: cur,
              icon: "fa-scissors", accent: "#1baf7a",
              meter: this._pctOf(t.exemptions, t.gross), foot: "of gross wages" },
            { key: "base", label: "Taxable Base", value: this.fmt(t.taxable_base), unit: cur,
              icon: "fa-balance-scale", accent: "#eda100",
              meter: this._pctOf(t.taxable_base, t.gross), foot: "of gross wages" },
            { key: "tax", label: "Total Tax Due", value: this.fmt(t.tax_due), unit: cur,
              icon: "fa-university", accent: "#d03b3b",
              meter: this._pctOf(t.tax_due, t.gross), foot: "effective rate" },
            { key: "net", label: "Net Payout", value: this.fmt(t.net), unit: cur,
              icon: "fa-check-circle", accent: "#12855a",
              meter: this._pctOf(t.net, t.gross), foot: "of gross wages" },
        ];
    }

    // ── Documents ─────────────────────────────────────────────────────────
    /** How many employees sit in each completeness band. */
    get docDistribution() {
        const rows = this.state.documents?.rows || [];
        const bands = [
            { label: "0–25%", min: 0, max: 25 },
            { label: "26–50%", min: 26, max: 50 },
            { label: "51–75%", min: 51, max: 75 },
            { label: "76–99%", min: 76, max: 99 },
            { label: "100%", min: 100, max: 100 },
        ];
        return bands.map((b) => ({
            label: b.label,
            value: rows.filter((r) => (r.pct || 0) >= b.min && (r.pct || 0) <= b.max).length,
        }));
    }
    get docMissingByDept() {
        return this._groupSum(this.state.documents?.rows, "department", "missing");
    }
    get docStats() {
        const k = this.state.documents?.kpis;
        if (!k) {
            return [];
        }
        const total = k.total_employees || 0;
        return [
            { key: "total", label: "Total Employees", value: this.fmt(total),
              icon: "fa-users", accent: "#1A5C3A" },
            { key: "complete", label: "Complete Files", value: this.fmt(k.complete_files),
              icon: "fa-check-circle", accent: "#12855a",
              meter: this._pctOf(k.complete_files, total), foot: "of employees" },
            { key: "incomplete", label: "Incomplete Files", value: this.fmt(k.incomplete_files),
              icon: "fa-exclamation-circle", accent: "#eda100",
              meter: this._pctOf(k.incomplete_files, total), foot: "of employees" },
            { key: "missing", label: "Missing Documents", value: this.fmt(k.missing_documents),
              icon: "fa-file-o", accent: "#eda100" },
            { key: "expired", label: "Expired Documents", value: this.fmt(k.expired_documents),
              icon: "fa-times-circle", accent: "#d03b3b" },
            { key: "soon", label: "Expiring Soon", value: this.fmt(k.expiring_soon),
              icon: "fa-clock-o", accent: "#eb6834" },
        ];
    }

    // ── Insurance ─────────────────────────────────────────────────────────
    /**
     * Insured wage base vs. total basic wage, by department — shows how much
     * of payroll the social-insurance reference actually covers.
     */
    get insWageCoverage() {
        const rows = (this.state.insurance?.rows || []).filter((r) => r.status === "insured");
        const byDept = new Map();
        for (const r of rows) {
            const k = r.department || "Undefined";
            const cur = byDept.get(k) || { wage: 0, ref: 0 };
            cur.wage += Number(r.basic_wage) || 0;
            cur.ref += Number(r.reference_amount) || 0;
            byDept.set(k, cur);
        }
        return [...byDept.entries()]
            .map(([label, v]) => ({
                label, wage: Math.round(v.wage), ref: Math.round(v.ref),
                pct: this._pctOf(v.ref, v.wage),
            }))
            .filter((r) => r.wage > 0)
            .sort((a, b) => b.wage - a.wage)
            .slice(0, 8);
    }
    get insUninsuredByDept() {
        const rows = (this.state.insurance?.rows || [])
            .filter((r) => r.status !== "insured")
            .map((r) => ({ department: r.department, n: 1 }));
        return this._groupSum(rows, "department", "n");
    }
    get insStats() {
        const k = this.state.insurance?.kpis;
        if (!k) {
            return [];
        }
        const total = k.total_employees || 0;
        return [
            { key: "total", label: "Total Employees", value: this.fmt(total),
              icon: "fa-users", accent: "#1A5C3A" },
            { key: "insured", label: "Insured", value: this.fmt(k.insured),
              icon: "fa-shield", accent: "#12855a",
              meter: this._pctOf(k.insured, total), foot: "of employees" },
            { key: "not", label: "Not Insured", value: this.fmt(k.not_insured),
              icon: "fa-exclamation-triangle", accent: "#d03b3b",
              meter: this._pctOf(k.not_insured, total), foot: "of employees" },
            { key: "coverage", label: "Coverage", value: `${k.coverage}`, unit: "%",
              icon: "fa-pie-chart", accent: "#2a78d6", meter: Number(k.coverage) || 0 },
            { key: "ref", label: "Total Reference", value: this.fmt(k.total_reference),
              unit: this.state.insurance.currency, icon: "fa-money", accent: "#1baf7a" },
            { key: "nocontract", label: "No Contract", value: this.fmt(k.no_contract),
              icon: "fa-file-text-o", accent: "#eda100" },
        ];
    }

    // ── Drill-through helpers ─────────────────────────────────────────────
    /** Open an employee list restricted to an explicit set of ids. */
    _openEmployeeIds(name, ids, { includeArchived = false } = {}) {
        if (!ids || !ids.length) {
            return this.notification.add(`No employees behind “${name}”.`, { type: "info" });
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "hr.employee",
            domain: [["id", "in", ids]],
            context: includeArchived ? { active_test: false } : {},
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
        });
    }

    _openDocuments(name, state) {
        const domain = [["mandatory", "=", true]];
        if (state) {
            domain.push(["state", "=", state]);
        }
        const f = this.state.filters;
        if (f.department_id) {
            domain.push(["employee_id.department_id", "=", f.department_id]);
        }
        if (f.company_id) {
            domain.push(["company_id", "=", f.company_id]);
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "hr.employee.document",
            domain,
            views: [[false, "list"], [false, "form"]],
        });
    }

    /**
     * Departures inside one month of the turnover series, grouped by reason —
     * this is the "who resigned / retired / was let go" view.
     */
    openTurnoverMonth(index) {
        const trend = this.state.data?.turnover_trend;
        if (!trend?.starts?.length) {
            return undefined;
        }
        const start = trend.starts[index];
        const end = trend.ends[index];
        const label = trend.labels[index];
        if ((trend.departures?.[index] || 0) === 0) {
            return this.notification.add(`No departures recorded in ${label}.`, { type: "info" });
        }
        const domain = [["departure_date", ">=", start], ["departure_date", "<=", end]];
        const f = this.state.filters;
        if (f.department_id) {
            domain.push(["department_id", "=", f.department_id]);
        }
        if (f.company_id) {
            domain.push(["company_id", "=", f.company_id]);
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: `Departures — ${label}`,
            res_model: "hr.employee",
            domain,
            // Departed employees are archived, so they only appear with
            // active_test disabled. Grouping by reason answers the "why".
            context: {
                active_test: false,
                group_by: ["departure_reason_id"],
                list_view_ref: "nx_hr_analytics_dashboard.view_hr_employee_departure_list",
            },
            views: [[false, "list"], [false, "form"]],
        });
    }

    /** Dispatch a stat-tile click to the right drill-through. */
    openStat(scope, key) {
        const empIds = (rows, pred) => (rows || []).filter(pred).map((r) => r.id).filter(Boolean);

        if (scope === "insurance") {
            const rows = this.state.insurance?.rows || [];
            switch (key) {
                case "total":
                    return this._openEmployeeIds("Employees", empIds(rows, () => true));
                case "insured":
                case "coverage":
                case "ref":
                    return this._openEmployeeIds("Insured Employees",
                        empIds(rows, (r) => r.status === "insured"));
                case "not":
                    return this._openEmployeeIds("Not Insured",
                        empIds(rows, (r) => r.status !== "insured"));
                case "nocontract":
                    return this._openEmployeeIds("No Contract",
                        empIds(rows, (r) => !r.has_contract));
                default:
                    return undefined;
            }
        }

        if (scope === "documents") {
            const rows = this.state.documents?.rows || [];
            switch (key) {
                case "total":
                    return this._openEmployeeIds("Employees", empIds(rows, () => true));
                case "complete":
                    return this._openEmployeeIds("Complete Files",
                        empIds(rows, (r) => r.status === "complete"));
                case "incomplete":
                    return this._openEmployeeIds("Incomplete Files",
                        empIds(rows, (r) => r.status !== "complete"));
                case "missing":
                    return this._openDocuments("Missing Documents", "missing");
                case "expired":
                    return this._openDocuments("Expired Documents", "expired");
                case "soon":
                    return this._openDocuments("Expiring Soon", "expiring");
                default:
                    return undefined;
            }
        }

        if (scope === "payroll") {
            const rows = this.state.payroll?.rows || [];
            const ids = empIds(rows, () => true);
            const names = {
                emp: "Employees in this payroll run",
                gross: "Employees — Total Wages",
                exempt: "Employees — Exemptions",
                base: "Employees — Taxable Base",
                tax: "Employees — Tax Due",
                net: "Employees — Net Payout",
            };
            return this._openEmployeeIds(names[key] || "Employees", ids);
        }

        return undefined;
    }

    /** Colour class for a percentage cell's mini-bar. */
    pctClass(pct) {
        const p = Number(pct) || 0;
        if (p >= 100) {
            return "o_ok";
        }
        return p >= 50 ? "o_warn" : "o_bad";
    }

    // ── Alerts / actions ──────────────────────────────────────────────────
    openAlert(alert) {
        const map = {
            employees_uninsured: () => this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "hr.employee",
                name: "Employees",
                views: [[false, "list"], [false, "form"]],
                domain: [["active", "=", true]],
            }),
            documents_incomplete: () => this.action.doAction(
                "nx_hr_analytics_dashboard.action_hr_employee_document"),
            documents_expiring: () => this.action.doAction(
                "nx_hr_analytics_dashboard.action_hr_employee_document"),
            payroll_tax: () => this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "nx.egypt.payroll.tax",
                name: "Payroll Tax",
                views: [[false, "list"], [false, "form"]],
            }),
        };
        (map[alert.action] || (() => {}))();
    }
}

registry.category("actions").add("nx_hr_analytics_dashboard.dashboard", HrAnalyticsDashboard);
