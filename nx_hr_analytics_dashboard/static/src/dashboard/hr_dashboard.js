/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

const GREENS = ["#1A5C3A", "#2D6A4F", "#40916C", "#52B788", "#74C69D", "#95D5B2", "#B7E4C7", "#D8F3DC"];
const C_SUCCESS = "#22C55E";
const C_WARN = "#F59E0B";
const C_DANGER = "#EF4444";
const C_INFO = "#3B82F6";

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
        });

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

    get _gridColor() {
        return "rgba(0,0,0,0.06)";
    }
    get _baseOpts() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            animation: { duration: 700, easing: "easeOutQuart" },
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
        }
    }

    _renderDashboardCharts() {
        const data = this.state.data;
        if (!data) {
            return;
        }
        const gridColor = this._gridColor;
        const baseOpts = this._baseOpts;

        // Headcount by Department — vertical bar
        const dept = data.headcount_by_department || [];
        this._make(this.deptChart, "dept", {
            type: "bar",
            data: {
                labels: dept.map((d) => d.label),
                datasets: [{
                    data: dept.map((d) => d.value),
                    backgroundColor: dept.map((_, i) => GREENS[i % GREENS.length]),
                    borderRadius: 6,
                    maxBarThickness: 46,
                }],
            },
            options: {
                ...baseOpts,
                onClick: (evt, els) => {
                    if (els.length) {
                        const d = dept[els[0].index];
                        this.openEmployeesFiltered("department_id", d && d.id, d && d.label);
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, precision: 0 },
                        grid: { color: gridColor },
                        border: { display: false },
                    },
                    x: { grid: { display: false }, border: { display: false } },
                },
            },
        });

        // Social Insurance — doughnut
        const ins = data.social_insurance;
        if (ins) {
            this._make(this.insuranceChart, "insurance", {
                type: "doughnut",
                data: {
                    labels: ["Insured", "Not Insured"],
                    datasets: [{
                        data: [ins.insured, ins.not_insured],
                        backgroundColor: [C_SUCCESS, C_DANGER],
                        borderWidth: 0,
                    }],
                },
                options: { ...baseOpts, cutout: "68%" },
            });
        }

        // Document Compliance — doughnut
        const comp = data.document_compliance;
        if (comp) {
            this._make(this.complianceChart, "compliance", {
                type: "doughnut",
                data: {
                    labels: ["Complete", "Incomplete", "Expired"],
                    datasets: [{
                        data: [comp.complete, comp.incomplete, comp.expired],
                        backgroundColor: [C_SUCCESS, C_WARN, C_DANGER],
                        borderWidth: 0,
                    }],
                },
                options: { ...baseOpts, cutout: "68%" },
            });
        }

        // Headcount Trend — line
        const trend = data.headcount_trend || { labels: [], values: [] };
        this._make(this.trendChart, "trend", {
            type: "line",
            data: {
                labels: trend.labels,
                datasets: [{
                    data: trend.values,
                    borderColor: "#1A5C3A",
                    backgroundColor: "rgba(26,92,58,0.10)",
                    fill: true,
                    tension: 0.4,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                }],
            },
            options: {
                ...baseOpts,
                scales: {
                    y: {
                        ticks: { precision: 0 },
                        grid: { color: gridColor },
                        border: { display: false },
                    },
                    x: { grid: { display: false }, border: { display: false } },
                },
            },
        });

        // Turnover — line
        const turn = data.turnover_trend || { labels: [], values: [] };
        this._make(this.turnoverChart, "turnover", {
            type: "line",
            data: {
                labels: turn.labels,
                datasets: [{
                    data: turn.values,
                    borderColor: C_WARN,
                    backgroundColor: "rgba(245,158,11,0.10)",
                    fill: true,
                    tension: 0.4,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                }],
            },
            options: {
                ...baseOpts,
                scales: {
                    y: { beginAtZero: true, grid: { color: gridColor }, border: { display: false } },
                    x: { grid: { display: false }, border: { display: false } },
                },
            },
        });
    }

    _renderDocumentCharts() {
        const d = this.state.documents;
        if (!d) {
            return;
        }
        const comp = d.compliance || {};
        this._make(this.docComplianceChart, "docCompliance", {
            type: "doughnut",
            data: {
                labels: ["Complete", "Incomplete", "Expired"],
                datasets: [{
                    data: [comp.complete, comp.incomplete, comp.expired],
                    backgroundColor: [C_SUCCESS, C_WARN, C_DANGER],
                    borderWidth: 0,
                }],
            },
            options: { ...this._baseOpts, cutout: "68%" },
        });

        const byType = d.missing_by_type || [];
        this._make(this.missingTypeChart, "missingType", {
            type: "bar",
            data: {
                labels: byType.map((r) => r.label),
                datasets: [{
                    data: byType.map((r) => r.value),
                    backgroundColor: C_WARN,
                    borderRadius: 6,
                    maxBarThickness: 22,
                }],
            },
            options: {
                ...this._baseOpts,
                indexAxis: "y",
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, precision: 0 },
                        grid: { color: this._gridColor },
                        border: { display: false },
                    },
                    y: { grid: { display: false }, border: { display: false } },
                },
            },
        });
    }

    _renderInsuranceCharts() {
        const d = this.state.insurance;
        if (!d) {
            return;
        }
        const s = d.status || {};
        this._make(this.insStatusChart, "insStatus", {
            type: "doughnut",
            data: {
                labels: ["Insured", "Not Insured"],
                datasets: [{
                    data: [s.insured, s.not_insured],
                    backgroundColor: [C_SUCCESS, C_DANGER],
                    borderWidth: 0,
                }],
            },
            options: { ...this._baseOpts, cutout: "68%" },
        });

        const byDept = d.by_department || [];
        this._make(this.insTrendChart, "insByDept", {
            type: "bar",
            data: {
                labels: byDept.map((r) => r.label),
                datasets: [{
                    data: byDept.map((r) => r.value),
                    backgroundColor: byDept.map((_, i) => GREENS[i % GREENS.length]),
                    borderRadius: 6,
                    maxBarThickness: 22,
                }],
            },
            options: {
                ...this._baseOpts,
                indexAxis: "y",
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, precision: 0 },
                        grid: { color: this._gridColor },
                        border: { display: false },
                    },
                    y: { grid: { display: false }, border: { display: false } },
                },
            },
        });
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
