/** @odoo-module **/

import { Component, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

export class TaskChart extends Component {
    static template = "nx_analytics_widgets.TaskChart";
    static props = {
        labels: { type: Array, optional: true },
        data:   { type: Array, optional: true },
        title:  { type: String, optional: true },
    };

    setup() {
        this.chartRef = useRef("chart");
        this._chart = null;

        onMounted(() => this.renderChart());
        onWillUnmount(() => {
            if (this._chart) {
                this._chart.destroy();
                this._chart = null;
            }
        });
    }

    async renderChart() {
        await loadJS(
            "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"
        );

        const labels = this.props.labels || [];
        const data   = this.props.data || [];
        if (!labels.length) return;

        // Format ISO date labels → "Mar 02"
        const fmtLabels = labels.map(d => {
            const dt = new Date(d + "T00:00:00");
            return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        });

        this._chart = new Chart(this.chartRef.el, {
            type: "line",
            data: {
                labels: fmtLabels,
                datasets: [
                    {
                        label: "Hours Logged",
                        data: data,
                        borderColor: "#4f46e5",
                        backgroundColor: "rgba(79, 70, 229, 0.08)",
                        borderWidth: 2.5,
                        pointRadius: 3,
                        pointBackgroundColor: "#4f46e5",
                        pointHoverRadius: 6,
                        pointHoverBackgroundColor: "#7c3aed",
                        tension: 0.4,
                        fill: true,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: "index" },
                plugins: {
                    legend: { display: false },
                    title: {
                        display: true,
                        text: this.props.title || "Hours Logged (Last 30 Days)",
                        position: "bottom",
                        font: { size: 13, weight: "700" },
                        color: "#475569",
                        padding: { top: 14 },
                    },
                    tooltip: {
                        backgroundColor: "#1e293b",
                        titleFont: { size: 12, weight: "600" },
                        bodyFont: { size: 12 },
                        padding: 10,
                        cornerRadius: 8,
                        callbacks: {
                            label: (ctx) => ` ${ctx.parsed.y}h`,
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            font: { size: 10 },
                            color: "#94a3b8",
                            maxRotation: 45,
                            maxTicksLimit: 10,
                        },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.04)" },
                        ticks: {
                            font: { size: 10 },
                            color: "#94a3b8",
                            callback: (v) => v + "h",
                        },
                    },
                },
            },
        });
    }
}

