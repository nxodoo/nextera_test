/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import {
    arcDepth,
    areaGradient,
    barGradient,
    barValueLabels,
    baseOptions,
    catPalette,
    categoryAxis,
    entryAnimation,
    markShadow,
    prefersReducedMotion,
    readTokens,
    shade,
    shortLabel,
    tooltipStyle,
    valueAxis,
    waterfallConnectors,
    waterfallLabels,
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
            // Per-table date-range filters, keyed by table name.
            dateRange: {
                documents: { from: "", to: "" },
                insurance: { from: "", to: "" },
            },
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
        this.payWaterfallChart = useRef("payWaterfallChart");
        this.payTaxDeptChart = useRef("payTaxDeptChart");
        this.payGrossDeptChart = useRef("payGrossDeptChart");
        this.docDistChart = useRef("docDistChart");
        this.docMissingDeptChart = useRef("docMissingDeptChart");
        this.insUninsuredChart = useRef("insUninsuredChart");
        // Added visualisations — one extra angle per tab.
        this.deptPolarChart = useRef("deptPolarChart");
        this.netChangeChart = useRef("netChangeChart");
        this.payMixChart = useRef("payMixChart");
        this.payCompDeptChart = useRef("payCompDeptChart");
        this.payRateChart = useRef("payRateChart");
        this.docRadarChart = useRef("docRadarChart");
        this.docStatusDeptChart = useRef("docStatusDeptChart");
        this.insCoverDeptChart = useRef("insCoverDeptChart");
        this.insScatterChart = useRef("insScatterChart");

        // Count-up targets, keyed by tile id. Rendered by OWL (never by
        // touching the DOM behind its back) and tweened on a rAF loop.
        this.counters = useState({});
        this._rafs = {};

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
                // Payroll loads asynchronously after the tab switch; without it
                // here its charts stay blank until some other dependency moves.
                this.state.payroll,
                // Re-create charts when a card flips back from table view.
                JSON.stringify(this.state.tableView),
            ],
        );
        onWillUnmount(() => {
            this.destroyCharts();
            this.stopCounters();
        });
    }

    // ── Count-up numbers ──────────────────────────────────────────────────
    /**
     * Tween a headline figure from 0 to its value. Purely decorative, so it
     * snaps straight to the target when the OS asks for reduced motion.
     */
    countTo(key, target) {
        const end = Number(target) || 0;
        if (prefersReducedMotion() || !end) {
            this.counters[key] = end;
            return end;
        }
        if (this.counters[key] === end || this._rafs[key]?.target === end) {
            return this.counters[key] ?? end;
        }
        cancelAnimationFrame(this._rafs[key]?.id);
        const from = 0;
        const duration = 900;
        let started = null;
        const step = (ts) => {
            if (started === null) {
                started = ts;
            }
            const p = Math.min(1, (ts - started) / duration);
            // easeOutQuart — fast start, gentle settle.
            const eased = 1 - Math.pow(1 - p, 4);
            this.counters[key] = Math.round(from + (end - from) * eased);
            if (p < 1) {
                this._rafs[key] = { id: requestAnimationFrame(step), target: end };
            } else {
                delete this._rafs[key];
            }
        };
        this._rafs[key] = { id: requestAnimationFrame(step), target: end };
        return this.counters[key] ?? 0;
    }
    stopCounters() {
        for (const k of Object.keys(this._rafs)) {
            cancelAnimationFrame(this._rafs[k].id);
            delete this._rafs[k];
        }
    }
    /** Value to render for a counter tile: the tween while it runs. */
    counted(key, value) {
        this.countTo(key, value);
        return this.counters[key] ?? 0;
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

    // ── Date-range filter (shared by the tables that carry a date) ────────
    /** Local YYYY-MM-DD, so presets line up with what the user sees. */
    _isoDay(d) {
        const p = (n) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    }
    dateRange(key) {
        return this.state.dateRange[key] || { from: "", to: "" };
    }
    onDateRangeChange(key, bound, ev) {
        this.state.dateRange[key][bound] = ev.target.value || "";
    }
    setRangeThisMonth(key) {
        const now = new Date();
        const first = new Date(now.getFullYear(), now.getMonth(), 1);
        const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
        this.state.dateRange[key] = { from: this._isoDay(first), to: this._isoDay(last) };
    }
    setRangeThisYear(key) {
        const y = new Date().getFullYear();
        this.state.dateRange[key] = { from: `${y}-01-01`, to: `${y}-12-31` };
    }
    clearRange(key) {
        this.state.dateRange[key] = { from: "", to: "" };
    }
    isRangeActive(key) {
        const r = this.dateRange(key);
        return !!(r.from || r.to);
    }

    /**
     * Keep a row when its date falls inside the range. Rows with no date are
     * dropped only once a range is actually set, so an unfiltered table still
     * shows everyone.
     */
    _inRange(value, range) {
        if (!range || (!range.from && !range.to)) {
            return true;
        }
        if (!value) {
            return false;
        }
        // ISO yyyy-mm-dd strings compare correctly as plain strings.
        if (range.from && value < range.from) {
            return false;
        }
        if (range.to && value > range.to) {
            return false;
        }
        return true;
    }

    // Filtered rows for the documents / insurance tables (client-side search).
    _filterRows(rows, query, statusKey, statusFilter, { dateField, range } = {}) {
        const q = (query || "").trim().toLowerCase();
        return (rows || []).filter((r) => {
            if (statusFilter && statusFilter !== "all" && r[statusKey] !== statusFilter) {
                return false;
            }
            if (dateField && !this._inRange(r[dateField], range)) {
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
            this.state.documents?.rows, this.state.docSearch, "status", this.state.docFilter,
            { dateField: "next_expiry", range: this.dateRange("documents") });
    }
    get insRows() {
        return this._filterRows(
            this.state.insurance?.rows, this.state.insSearch, "status", this.state.insFilter,
            { dateField: "contract_start_iso", range: this.dateRange("insurance") });
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
        // `accent` drives the card's tint, rail, icon chip and hover glow;
        // `accent2` is the second stop of its gradient wash. The lead card is
        // rendered as a full-bleed hero so the eye has somewhere to land first.
        return [
            { key: "total", label: "Total Employees", value: k.total_employees,
              accent: "#1A5C3A", accent2: "#3FA46A", icon: "fa-users", hero: true,
              sub: { kind: "delta", value: k.net_change ?? 0 }, clickable: true },
            { key: "active", label: "Active Employees", value: k.active_employees,
              accent: "#12855a", accent2: "#43C88A", icon: "fa-user-circle-o", clickable: true },
            { key: "new_hires", label: "New Hires", value: k.new_hires,
              accent: "#2a78d6", accent2: "#63A6F5", icon: "fa-user-plus",
              sub: { kind: "note", text: "this month" }, clickable: true },
            { key: "resignations", label: "Resignations", value: k.resignations,
              accent: "#8B5CF6", accent2: "#B794FA", icon: "fa-user-times",
              sub: { kind: "note", text: "this month" }, clickable: true },
            { key: "uninsured", label: "Uninsured", value: k.uninsured,
              accent: "#eb6834", accent2: "#F79B6E", icon: "fa-shield", clickable: true },
            { key: "missing_documents", label: "Missing Documents", value: k.missing_documents,
              accent: "#d03b3b", accent2: "#EE7676", icon: "fa-file-text-o", clickable: true },
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
    _donutConfig(ref, entries, { depth = 13, cutout = "66%" } = {}) {
        const t = this._tokens(ref);
        const live = (entries || []).filter((e) => (e.value || 0) > 0);
        return {
            type: "doughnut",
            data: {
                labels: live.map((e) => e.label),
                datasets: [{
                    data: live.map((e) => e.value),
                    // The lit top face — a touch brighter than the extruded
                    // wall the nxArcDepth plugin stamps underneath.
                    backgroundColor: live.map((e) => shade(e.color, 0.06, 1)),
                    // 2px surface-coloured gap between segments (spacer rule).
                    borderColor: t.surface,
                    borderWidth: 2,
                    hoverBorderColor: t.surface,
                    hoverOffset: 10,
                    borderRadius: 4,
                }],
            },
            options: {
                ...baseOptions(t),
                cutout,
                // Room for the extruded wall, so the ring is not clipped.
                layout: { padding: { bottom: depth + 4 } },
                animation: prefersReducedMotion()
                    ? { duration: 0 }
                    : { animateRotate: true, animateScale: true, duration: 1100, easing: "easeOutQuart" },
                plugins: {
                    legend: { display: false },
                    nxArcDepth: { depth, gloss: true },
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
            plugins: [arcDepth],
        };
    }

    /**
     * Polar area: one wedge per category, radius = magnitude. Reads the shape
     * of a distribution at a glance where a bar list reads its ranking, and
     * carries the categorical ramp so each department keeps its own identity.
     */
    _polarConfig(ref, items, { depth = 10 } = {}) {
        const t = this._tokens(ref);
        const ramp = catPalette(t);
        const live = (items || []).filter((r) => (r.value || 0) > 0);
        return {
            type: "polarArea",
            data: {
                labels: live.map((r) => shortLabel(r.label, 18)),
                datasets: [{
                    data: live.map((r) => r.value),
                    backgroundColor: live.map((_, i) => withAlpha(ramp[i % ramp.length], 0.88)),
                    hoverBackgroundColor: live.map((_, i) => ramp[i % ramp.length]),
                    borderColor: t.surface,
                    borderWidth: 2,
                    hoverOffset: 8,
                }],
            },
            options: {
                ...baseOptions(t),
                layout: { padding: { bottom: depth + 2 } },
                animation: prefersReducedMotion()
                    ? { duration: 0 }
                    : { animateRotate: true, animateScale: true, duration: 1200, easing: "easeOutQuart" },
                scales: {
                    r: {
                        beginAtZero: true,
                        grid: { color: t.grid, circular: true },
                        angleLines: { color: t.grid },
                        ticks: {
                            display: true, backdropColor: "transparent",
                            color: t.textMuted, font: { size: 10 }, maxTicksLimit: 4,
                        },
                        pointLabels: { display: false },
                    },
                },
                plugins: {
                    legend: {
                        display: true, position: "right",
                        labels: {
                            color: t.text, boxWidth: 10, boxHeight: 10,
                            usePointStyle: true, pointStyle: "circle",
                            font: { size: 11.5 }, padding: 10,
                        },
                    },
                    nxArcDepth: { depth, gloss: false },
                    tooltip: tooltipStyle(t, {
                        callbacks: {
                            title: (c) => live[c[0].dataIndex]?.label ?? "",
                            label: (c) => ` ${this.fmt(c.raw)}`,
                        },
                    }),
                },
            },
            plugins: [arcDepth],
        };
    }

    /**
     * Radar: several categories scored on the same 0–100 scale. The filled
     * polygon makes an uneven profile obvious in a way six separate bars do not.
     */
    _radarConfig(ref, items, { color, suffix = "%", max = 100 } = {}) {
        const t = this._tokens(ref);
        const hue = color || t.cat1;
        return {
            type: "radar",
            data: {
                labels: items.map((r) => shortLabel(r.label, 14)),
                datasets: [{
                    data: items.map((r) => r.value),
                    borderColor: hue,
                    backgroundColor: withAlpha(hue, 0.24),
                    pointBackgroundColor: hue,
                    pointBorderColor: t.surface,
                    pointBorderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 7,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.15,
                }],
            },
            options: {
                ...baseOptions(t),
                animation: prefersReducedMotion()
                    ? { duration: 0 }
                    : { duration: 1100, easing: "easeOutQuart" },
                scales: {
                    r: {
                        beginAtZero: true,
                        suggestedMax: max,
                        grid: { color: t.grid },
                        angleLines: { color: t.grid },
                        ticks: {
                            display: true, backdropColor: "transparent",
                            color: t.textMuted, font: { size: 10 }, maxTicksLimit: 4,
                        },
                        pointLabels: { color: t.text, font: { size: 11 } },
                    },
                },
                plugins: {
                    legend: { display: false },
                    nxMarkShadow: { blur: 12, offsetY: 3, color: withAlpha(hue, 0.35) },
                    tooltip: tooltipStyle(t, {
                        callbacks: {
                            title: (c) => items[c[0].dataIndex]?.label ?? "",
                            label: (c) => ` ${this.fmt(c.raw)}${suffix}`,
                        },
                    }),
                },
            },
            plugins: [markShadow],
        };
    }

    /**
     * Stacked composition — the parts of each category and their total in one
     * mark. Horizontal by default so long department names stay readable.
     */
    _stackedBarConfig(ref, labels, series, { horizontal = true, suffix = "" } = {}) {
        const t = this._tokens(ref);
        return {
            type: "bar",
            data: {
                labels: labels.map((l) => shortLabel(l)),
                datasets: series.map((s) => ({
                    label: s.label,
                    data: s.values,
                    backgroundColor: (c) =>
                        barGradient(c.chart.ctx, c.chart.chartArea, s.color, horizontal),
                    hoverBackgroundColor: shade(s.color, 0.18, 1),
                    borderRadius: 4,
                    borderSkipped: false,
                    maxBarThickness: horizontal ? 26 : 56,
                })),
            },
            options: {
                ...baseOptions(t),
                indexAxis: horizontal ? "y" : "x",
                animation: entryAnimation({ stagger: 55 }),
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: horizontal
                        ? { ...valueAxis(t), stacked: true }
                        : { ...categoryAxis(t, { ticks: { color: t.text, font: { size: 11.5 } } }), stacked: true },
                    y: horizontal
                        ? categoryAxis(t, { ticks: { color: t.text, font: { size: 12 } }, stacked: true })
                        : { ...valueAxis(t), stacked: true },
                },
                plugins: {
                    legend: {
                        display: true, position: "bottom",
                        labels: {
                            color: t.text, boxWidth: 10, boxHeight: 10,
                            usePointStyle: true, pointStyle: "circle",
                            font: { size: 11.5 }, padding: 14,
                        },
                    },
                    nxMarkShadow: { blur: 8, offsetY: 3 },
                    tooltip: tooltipStyle(t, {
                        displayColors: true,
                        callbacks: {
                            title: (c) => labels[c[0].dataIndex] ?? "",
                            label: (c) => ` ${c.dataset.label}: ${this.fmt(c.raw)}${suffix}`,
                        },
                    }),
                },
            },
            plugins: [markShadow],
        };
    }

    /**
     * Diverging bars around a zero baseline — gains above, losses below, so the
     * sign of each month is carried by direction first and colour second.
     */
    _divergingBarConfig(ref, items, { suffix = "" } = {}) {
        const t = this._tokens(ref);
        const hue = (v) => (v >= 0 ? t.good : t.critical);
        return {
            type: "bar",
            data: {
                labels: items.map((r) => r.label),
                datasets: [{
                    data: items.map((r) => r.value),
                    backgroundColor: (c) => {
                        const v = items[c.dataIndex]?.value ?? 0;
                        return barGradient(c.chart.ctx, c.chart.chartArea, hue(v), false);
                    },
                    hoverBackgroundColor: items.map((r) => shade(hue(r.value), 0.15, 1)),
                    borderRadius: 5,
                    borderSkipped: false,
                    maxBarThickness: 34,
                }],
            },
            options: {
                ...baseOptions(t),
                animation: entryAnimation({ stagger: 45 }),
                layout: { padding: { top: 22, bottom: 14 } },
                scales: {
                    y: {
                        ...valueAxis(t, { ticks: { display: false } }),
                        beginAtZero: true,
                        grid: { color: t.grid, drawTicks: false },
                    },
                    x: categoryAxis(t, { ticks: { color: t.textMuted, font: { size: 11 } } }),
                },
                plugins: {
                    legend: { display: false },
                    nxMarkShadow: { blur: 10, offsetY: 4 },
                    tooltip: tooltipStyle(t, {
                        callbacks: {
                            label: (c) => ` ${c.raw > 0 ? "+" : ""}${this.fmt(c.raw)}${suffix}`,
                        },
                    }),
                    nxBarValueLabels: {
                        horizontal: false, color: t.text,
                        format: (v) => `${v > 0 ? "+" : ""}${this.fmt(v)}`,
                    },
                },
            },
            plugins: [barValueLabels, markShadow],
        };
    }

    /**
     * Scatter — two amounts per employee plotted against each other, with a
     * 45° reference line. Points far below the line are the ones whose
     * insurance base lags their actual wage.
     */
    _scatterConfig(ref, groups, { xLabel, yLabel } = {}) {
        const t = this._tokens(ref);
        return {
            type: "scatter",
            data: {
                datasets: groups.map((g) => ({
                    label: g.label,
                    data: g.points,
                    backgroundColor: withAlpha(g.color, 0.72),
                    hoverBackgroundColor: g.color,
                    borderColor: t.surface,
                    borderWidth: 1,
                    pointRadius: 5,
                    pointHoverRadius: 9,
                })),
            },
            options: {
                ...baseOptions(t),
                animation: prefersReducedMotion()
                    ? { duration: 0 }
                    : { duration: 900, easing: "easeOutQuart" },
                interaction: { mode: "nearest", intersect: true },
                scales: {
                    x: valueAxis(t, {
                        title: { display: !!xLabel, text: xLabel, color: t.textMuted,
                                 font: { size: 11 } },
                    }),
                    y: valueAxis(t, {
                        title: { display: !!yLabel, text: yLabel, color: t.textMuted,
                                 font: { size: 11 } },
                    }),
                },
                plugins: {
                    legend: {
                        display: true, position: "bottom",
                        labels: {
                            color: t.text, boxWidth: 9, boxHeight: 9,
                            usePointStyle: true, pointStyle: "circle",
                            font: { size: 11.5 }, padding: 14,
                        },
                    },
                    nxMarkShadow: { blur: 8, offsetY: 2 },
                    tooltip: tooltipStyle(t, {
                        callbacks: {
                            title: (c) => c[0].raw.name || "",
                            label: (c) =>
                                ` ${xLabel}: ${this.fmt(c.raw.x)}  ·  ${yLabel}: ${this.fmt(c.raw.y)}`,
                        },
                    }),
                },
            },
            plugins: [markShadow],
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
                    // One series → one colour; the gradient is a lit surface,
                    // not a second encoding. Length still carries magnitude.
                    backgroundColor: (c) =>
                        barGradient(c.chart.ctx, c.chart.chartArea, hue, true),
                    hoverBackgroundColor: shade(hue, 0.18, 1),
                    borderRadius: 5,
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
                    nxMarkShadow: { blur: 9, offsetX: 3, offsetY: 3 },
                },
            },
            plugins: [barValueLabels, markShadow],
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
                    backgroundColor: (c) =>
                        barGradient(c.chart.ctx, c.chart.chartArea, hue, false),
                    hoverBackgroundColor: shade(hue, 0.18, 1),
                    borderRadius: 6,
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
                    nxMarkShadow: { blur: 11, offsetY: 5 },
                },
            },
            plugins: [barValueLabels, markShadow],
        };
    }

    /**
     * Waterfall: floating bars ([from, to]) with connectors, showing gross
     * being reduced step by step to net.
     */
    _waterfallConfig(ref, wf) {
        const t = this._tokens(ref);
        const steps = wf.steps;
        // Anchors (gross / net) vs. reductions — one colour per role, so the
        // three deductions never compete with each other for attention.
        const colorFor = (s) => {
            if (s.kind === "down") {
                return t.cat2;
            }
            return s.key === "net" ? t.series : t.cat1;
        };
        return {
            type: "bar",
            data: {
                labels: steps.map((s) => s.label),
                datasets: [{
                    data: steps.map((s) => [s.from, s.to]),
                    backgroundColor: (c) =>
                        barGradient(c.chart.ctx, c.chart.chartArea, colorFor(steps[c.dataIndex]), false),
                    hoverBackgroundColor: steps.map((s) => shade(colorFor(s), 0.18, 1)),
                    borderRadius: 6,
                    borderSkipped: false,
                    maxBarThickness: 76,
                }],
            },
            options: {
                ...baseOptions(t),
                animation: entryAnimation({ stagger: 70 }),
                layout: { padding: { top: 26 } },
                scales: {
                    y: {
                        ...valueAxis(t, { ticks: { display: false } }),
                        grid: { display: false },
                        beginAtZero: true,
                    },
                    x: categoryAxis(t, { ticks: { color: t.text, font: { size: 12 } } }),
                },
                plugins: {
                    legend: { display: false },
                    tooltip: tooltipStyle(t, {
                        callbacks: {
                            title: (c) => steps[c[0].dataIndex].label,
                            label: (c) => {
                                const s = steps[c.dataIndex];
                                const sign = s.kind === "down" ? "−" : "";
                                return ` ${sign}${this.fmt(Math.round(s.value))}  ·  ${s.pct}% of gross`;
                            },
                        },
                    }),
                    nxWaterfallConnectors: { steps, color: t.grid },
                    nxWaterfallLabels: {
                        steps,
                        color: t.text,
                        downColor: t.cat2,
                        format: (v) => this.fmt(Math.round(v)),
                    },
                    nxMarkShadow: { blur: 12, offsetY: 5 },
                },
            },
            plugins: [waterfallConnectors, waterfallLabels, markShadow],
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
                    nxMarkShadow: { blur: 14, offsetY: 6, color: withAlpha(hue, 0.35) },
                    tooltip: tooltipStyle(t, {
                        callbacks: { label: (c) => ` ${this.fmt(c.raw)}${tooltipSuffix}` },
                    }),
                },
            },
            plugins: [markShadow],
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

        const wf = this.payWaterfall;
        if (wf) {
            this._make(this.payWaterfallChart, "payWaterfall",
                this._waterfallConfig(this.payWaterfallChart, wf));
        }

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

        // Where the gross ends up, as a part-to-whole ring.
        const mix = this.payMix;
        if (mix.length) {
            const hue = { net: t.good, tax: t.critical, insurance: t.cat1, deductions: t.cat2 };
            this._make(this.payMixChart, "payMix",
                this._donutConfig(this.payMixChart,
                    mix.map((m) => ({ ...m, color: hue[m.key] || t.series })),
                    { depth: 15, cutout: "58%" }));
        }

        // Net vs. each withholding, department by department.
        const comp = this.payCompByDept;
        if (comp.length) {
            this._make(this.payCompDeptChart, "payCompDept",
                this._stackedBarConfig(this.payCompDeptChart, comp.map((r) => r.label), [
                    { label: "Net", color: t.good, values: comp.map((r) => Math.round(r.net)) },
                    { label: "Tax", color: t.critical, values: comp.map((r) => Math.round(r.tax_due)) },
                    { label: "Insurance", color: t.cat1, values: comp.map((r) => Math.round(r.insurance)) },
                    { label: "Deductions", color: t.cat2, values: comp.map((r) => Math.round(r.deductions)) },
                ]));
        }

        // Effective rate — the comparable number a raw tax total cannot give.
        const rates = this.payRateByDept;
        if (rates.length && !this.isTableView("payRate")) {
            this._make(this.payRateChart, "payRate",
                this._hBarConfig(this.payRateChart, rates, { color: t.cat4 }));
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

        // Workforce distribution — the shape of the org, not its ranking.
        const polar = this.deptPolar;
        if (polar.length && !this.isTableView("deptPolar")) {
            this._make(this.deptPolarChart, "deptPolar",
                this._polarConfig(this.deptPolarChart, polar));
        }

        // Month-over-month net change — growth and shrink around zero.
        const net = this.netChangeSeries;
        if (net.length) {
            this._make(this.netChangeChart, "netChange",
                this._divergingBarConfig(this.netChangeChart, net));
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

        // Completeness profile across departments, on one shared 0–100 scale.
        const radar = this.docComplianceByDept;
        if (radar.length >= 3) {
            this._make(this.docRadarChart, "docRadar",
                this._radarConfig(this.docRadarChart, radar, { color: t.cat1 }));
        }

        // What each department's file actually consists of.
        const status = this.docStatusByDept;
        if (status.length) {
            this._make(this.docStatusDeptChart, "docStatusDept",
                this._stackedBarConfig(this.docStatusDeptChart, status.map((r) => r.label), [
                    { label: "Complete", color: t.good, values: status.map((r) => r.complete) },
                    { label: "Missing", color: t.warning, values: status.map((r) => r.missing) },
                    { label: "Expired", color: t.critical, values: status.map((r) => r.expired) },
                ]));
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

        // Covered vs. uncovered inside each department, in one stacked mark.
        const cover = this.insCoverageByDept;
        if (cover.length) {
            this._make(this.insCoverDeptChart, "insCoverDept",
                this._stackedBarConfig(this.insCoverDeptChart, cover.map((r) => r.label), [
                    { label: "Insured", color: t.good, values: cover.map((r) => r.insured) },
                    { label: "Not Insured", color: t.critical, values: cover.map((r) => r.uninsured) },
                ]));
        }

        // Wage against declared reference — the under-declaration view.
        const scatter = this.insWageScatter;
        if (scatter.length) {
            this._make(this.insScatterChart, "insScatter",
                this._scatterConfig(this.insScatterChart,
                    scatter.map((g) => ({ ...g, color: t[g.color] })),
                    { xLabel: "Basic Wage", yLabel: "Reference Amount" }));
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

    /** Group rows by key, summing several numeric fields at once. */
    _groupMulti(rows, keyField, valueFields, { limit = 7 } = {}) {
        const acc = new Map();
        for (const r of rows || []) {
            const key = r[keyField] || "Undefined";
            const cur = acc.get(key) || Object.fromEntries(valueFields.map((f) => [f, 0]));
            for (const f of valueFields) {
                cur[f] += Number(r[f]) || 0;
            }
            acc.set(key, cur);
        }
        return [...acc.entries()]
            .map(([label, v]) => ({ label, ...v }))
            .sort((a, b) => (b[valueFields[0]] || 0) - (a[valueFields[0]] || 0))
            .slice(0, limit);
    }

    // ── Dashboard: added angles ───────────────────────────────────────────
    /** Department headcount as a distribution shape (top 7). */
    get deptPolar() {
        return (this.state.data?.headcount_by_department || []).slice(0, 7);
    }
    /**
     * Month-over-month change in headcount, derived from the trend series —
     * the growth/shrink signal the cumulative line hides.
     */
    get netChangeSeries() {
        const trend = this.state.data?.headcount_trend;
        if (!trend?.values?.length) {
            return [];
        }
        const out = [];
        for (let i = 1; i < trend.values.length; i++) {
            out.push({ label: trend.labels[i], value: trend.values[i] - trend.values[i - 1] });
        }
        return out;
    }
    get netChangeSummary() {
        const s = this.netChangeSeries;
        const up = s.filter((r) => r.value > 0).reduce((a, r) => a + r.value, 0);
        const down = s.filter((r) => r.value < 0).reduce((a, r) => a - r.value, 0);
        return { up, down, net: up - down };
    }

    // ── Payroll Tax ───────────────────────────────────────────────────────
    /**
     * Gross stepped down to net, one deduction at a time — a waterfall reads
     * the subtraction sequence, which a part-to-whole bar cannot show.
     * Zero-valued deductions are skipped so the chart never shows empty steps.
     */
    get payWaterfall() {
        const t = this.state.payroll?.totals;
        if (!t || !t.gross) {
            return null;
        }
        const steps = [];
        let running = t.gross;
        steps.push({
            key: "gross", label: "Gross Wage", kind: "total",
            from: 0, to: t.gross, value: t.gross, pct: 100,
        });
        for (const [field, label] of [
            ["tax_due", "Tax Due"],
            ["insurance", "Insurance"],
            ["deductions", "Deductions"],
        ]) {
            const amount = t[field] || 0;
            if (amount <= 0) {
                continue;
            }
            steps.push({
                key: field, label, kind: "down",
                from: running - amount, to: running,
                value: amount, pct: this._pctOf(amount, t.gross),
            });
            running -= amount;
        }
        steps.push({
            key: "net", label: "Net Salary", kind: "total",
            from: 0, to: running, value: running,
            pct: this._pctOf(running, t.gross),
        });
        return { gross: t.gross, net: running, steps };
    }
    /** Part-to-whole complement of the waterfall: where the gross ends up. */
    get payMix() {
        const t = this.state.payroll?.totals;
        if (!t || !t.gross) {
            return [];
        }
        return [
            { key: "net", label: "Net Payout", value: Math.round(t.net) },
            { key: "tax", label: "Tax Due", value: Math.round(t.tax_due) },
            { key: "insurance", label: "Insurance", value: Math.round(t.insurance) },
            { key: "deductions", label: "Other Deductions", value: Math.round(t.deductions) },
        ].filter((r) => r.value > 0);
    }
    /** Net vs. each withholding, stacked per department. */
    get payCompByDept() {
        return this._groupMulti(this.state.payroll?.rows, "department",
            ["gross", "net", "tax_due", "insurance", "deductions"]);
    }
    /** Effective tax rate per department — tax as a share of that dept's gross. */
    get payRateByDept() {
        return this._groupMulti(this.state.payroll?.rows, "department",
            ["gross", "tax_due"], { limit: 8 })
            .filter((r) => r.gross > 0)
            .map((r) => ({ label: r.label, value: this._pctOf(r.tax_due, r.gross) }))
            .sort((a, b) => b.value - a.value);
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
              icon: "fa-users", accent: "#1A5C3A", accent2: "#3FA46A" },
            { key: "gross", label: "Total Wages", value: this.fmt(t.gross), unit: cur,
              icon: "fa-money", accent: "#2a78d6", accent2: "#63A6F5" },
            { key: "exempt", label: "Exemptions", value: this.fmt(t.exemptions), unit: cur,
              icon: "fa-scissors", accent: "#1baf7a", accent2: "#57D6A8",
              meter: this._pctOf(t.exemptions, t.gross), foot: "of gross wages" },
            { key: "base", label: "Taxable Base", value: this.fmt(t.taxable_base), unit: cur,
              icon: "fa-balance-scale", accent: "#eda100", accent2: "#F5C64E",
              meter: this._pctOf(t.taxable_base, t.gross), foot: "of gross wages" },
            { key: "tax", label: "Total Tax Due", value: this.fmt(t.tax_due), unit: cur,
              icon: "fa-university", accent: "#d03b3b", accent2: "#EE7676",
              meter: this._pctOf(t.tax_due, t.gross), foot: "effective rate" },
            { key: "net", label: "Net Payout", value: this.fmt(t.net), unit: cur,
              icon: "fa-check-circle", accent: "#12855a", accent2: "#43C88A",
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
    /**
     * Average file completeness per department, on the shared 0–100 scale a
     * radar needs — an uneven polygon names the departments to chase.
     */
    get docComplianceByDept() {
        const acc = new Map();
        for (const r of this.state.documents?.rows || []) {
            const k = r.department || "Undefined";
            const cur = acc.get(k) || { sum: 0, n: 0 };
            cur.sum += Number(r.pct) || 0;
            cur.n += 1;
            acc.set(k, cur);
        }
        return [...acc.entries()]
            .map(([label, v]) => ({ label, value: Math.round(v.sum / v.n) }))
            .sort((a, b) => b.value - a.value)
            .slice(0, 8);
    }
    /** Complete / missing / expired documents stacked per department. */
    get docStatusByDept() {
        return this._groupMulti(this.state.documents?.rows, "department",
            ["complete", "missing", "expired"]);
    }
    get docStats() {
        const k = this.state.documents?.kpis;
        if (!k) {
            return [];
        }
        const total = k.total_employees || 0;
        return [
            { key: "total", label: "Total Employees", value: this.fmt(total),
              icon: "fa-users", accent: "#1A5C3A", accent2: "#3FA46A" },
            { key: "complete", label: "Complete Files", value: this.fmt(k.complete_files),
              icon: "fa-check-circle", accent: "#12855a", accent2: "#43C88A",
              meter: this._pctOf(k.complete_files, total), foot: "of employees" },
            { key: "incomplete", label: "Incomplete Files", value: this.fmt(k.incomplete_files),
              icon: "fa-exclamation-circle", accent: "#eda100", accent2: "#F5C64E",
              meter: this._pctOf(k.incomplete_files, total), foot: "of employees" },
            { key: "missing", label: "Missing Documents", value: this.fmt(k.missing_documents),
              icon: "fa-file-o", accent: "#eda100", accent2: "#F5C64E" },
            { key: "expired", label: "Expired Documents", value: this.fmt(k.expired_documents),
              icon: "fa-times-circle", accent: "#d03b3b", accent2: "#EE7676" },
            { key: "soon", label: "Expiring Soon", value: this.fmt(k.expiring_soon),
              icon: "fa-clock-o", accent: "#eb6834", accent2: "#F79B6E" },
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
    /** Insured vs. uninsured headcount, stacked per department. */
    get insCoverageByDept() {
        const rows = (this.state.insurance?.rows || []).map((r) => ({
            department: r.department,
            insured: r.status === "insured" ? 1 : 0,
            uninsured: r.status === "insured" ? 0 : 1,
        }));
        return this._groupMulti(rows, "department", ["insured", "uninsured"], { limit: 8 });
    }
    /**
     * Basic wage against the declared insurance reference, one point per
     * employee. Points sitting low carry a reference well under their wage.
     */
    get insWageScatter() {
        const rows = (this.state.insurance?.rows || []).filter((r) => r.basic_wage > 0);
        const point = (r) => ({ x: r.basic_wage, y: r.reference_amount, name: r.name });
        return [
            { key: "insured", label: "Insured", color: "good",
              points: rows.filter((r) => r.status === "insured").map(point) },
            { key: "not", label: "Not Insured", color: "critical",
              points: rows.filter((r) => r.status !== "insured").map(point) },
        ].filter((g) => g.points.length);
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
              icon: "fa-users", accent: "#1A5C3A", accent2: "#3FA46A" },
            { key: "insured", label: "Insured", value: this.fmt(k.insured),
              icon: "fa-shield", accent: "#12855a", accent2: "#43C88A",
              meter: this._pctOf(k.insured, total), foot: "of employees" },
            { key: "not", label: "Not Insured", value: this.fmt(k.not_insured),
              icon: "fa-exclamation-triangle", accent: "#d03b3b", accent2: "#EE7676",
              meter: this._pctOf(k.not_insured, total), foot: "of employees" },
            { key: "coverage", label: "Coverage", value: `${k.coverage}`, unit: "%",
              icon: "fa-pie-chart", accent: "#2a78d6", accent2: "#63A6F5", meter: Number(k.coverage) || 0 },
            { key: "ref", label: "Total Reference", value: this.fmt(k.total_reference),
              unit: this.state.insurance.currency, icon: "fa-money", accent: "#1baf7a", accent2: "#57D6A8" },
            { key: "nocontract", label: "No Contract", value: this.fmt(k.no_contract),
              icon: "fa-file-text-o", accent: "#eda100", accent2: "#F5C64E" },
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
