/** @odoo-module **/

import { Component, useState, onWillDestroy } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { DashboardTab } from "./components/dashboard_tab";
import { LeaveTab } from "./components/leave_tab";
import { AttendanceTab } from "./components/attendance_tab";
import { PayrollTab } from "./components/payroll_tab";
import { LettersTab } from "./components/letters_tab";
import { TripsTab } from "./components/trips_tab";

const TABS = [
    { id: "dashboard", label: "Dashboard", icon: "fa-th-large", group: "" },
    { id: "leave", label: "Leave Management", icon: "fa-calendar", group: "Employee" },
    { id: "attendance", label: "Attendance", icon: "fa-clock-o", group: "Employee" },
    { id: "payroll", label: "Payroll", icon: "fa-credit-card", group: "Employee" },
    { id: "letters", label: "Letter Requests", icon: "fa-envelope-o", group: "HR Services" },
    { id: "trips", label: "Business Trips", icon: "fa-plane", group: "HR Services" },
];

export class EssPortalApp extends Component {
    static template = "nx_portal_ess.EssPortalApp";
    static props = ["*"];
    static components = {
        DashboardTab, LeaveTab, AttendanceTab, PayrollTab, LettersTab, TripsTab,
    };

    setup() {
        this.tabs = TABS;
        const initial = (window.location.hash || "").replace("#", "");
        const valid = TABS.some((t) => t.id === initial);
        this.state = useState({
            active: valid ? initial : "dashboard",
            sidebarOpen: false,
        });

        this._onHash = () => {
            const h = (window.location.hash || "").replace("#", "");
            if (TABS.some((t) => t.id === h) && h !== this.state.active) {
                this.state.active = h;
            }
        };
        window.addEventListener("hashchange", this._onHash);
        onWillDestroy(() => window.removeEventListener("hashchange", this._onHash));
    }

    get groups() {
        const seen = [];
        for (const t of this.tabs) {
            if (t.group && !seen.includes(t.group)) {
                seen.push(t.group);
            }
        }
        return seen;
    }

    tabsForGroup(group) {
        return this.tabs.filter((t) => t.group === group);
    }

    get topTabs() {
        return this.tabs.filter((t) => !t.group);
    }

    get activeTab() {
        return this.tabs.find((t) => t.id === this.state.active) || this.tabs[0];
    }

    setTab(id) {
        this.state.active = id;
        this.state.sidebarOpen = false;
        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, "", "#" + id);
        } else {
            window.location.hash = id;
        }
    }

    toggleSidebar() {
        this.state.sidebarOpen = !this.state.sidebarOpen;
    }
}

registry.category("public_components").add("nx.EssPortalApp", EssPortalApp);
