/** @odoo-module **/

import {Component, useRef, useState, onMounted, onWillUnmount, onPatched} from "@odoo/owl";
import {loadJS} from "@web/core/assets";

const COLORS = [
    "#4f46e5", // indigo
    "#10b981", // emerald
    "#f59e0b", // amber
    "#ef4444", // rose
    "#06b6d4", // cyan
    "#8b5cf6", // purple
    "#ec4899", // pink
    "#14b8a6", // teal
];

const HOVER_COLORS = [
    "#4338ca",
    "#059669",
    "#d97706",
    "#dc2626",
    "#0891b2",
    "#7c3aed",
    "#db2777",
    "#0d9488",
];

/**
 * Center-text plugin: renders total task count in the doughnut hole.
 */
function makeCenterTextPlugin(totalTasks) {
    return {
        id: "nxCenterText",
        beforeDraw(chart) {
            const {ctx, chartArea: {top, bottom, left, right}} = chart;
            const cx = (left + right) / 2;
            const cy = (top + bottom) / 2;

            ctx.save();
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";

            // Big number
            ctx.font = "bold 28px Inter, system-ui, sans-serif";
            ctx.fillStyle = "#1e293b";
            ctx.fillText(totalTasks, cx, cy - 10);

            // Label
            ctx.font = "500 12px Inter, system-ui, sans-serif";
            ctx.fillStyle = "#94a3b8";
            ctx.fillText("Total Tasks", cx, cy + 14);

            ctx.restore();
        },
    };
}

export class TaskProjectChart extends Component {
    static template = "nx_analytics_widgets.TaskProjectChart";
    static props = {
        projects: {type: Array, optional: true},
    };

    setup() {
        this.chartRef = useRef("projectChart");
        this._chart = null;
        this.state = useState({selectedProject: null});

        onMounted(() => this._renderChart());
        onPatched(() => {
            // Re-render if projects data changes
            if (this._chart) {
                this._chart.destroy();
                this._chart = null;
            }
            this._renderChart();

            // Disable animation on stat cards after first render
            setTimeout(() => {
                const statCards = document.querySelectorAll('.nx-pd-stat');
                statCards.forEach(card => card.classList.add('nx-stat-loaded'));
            }, 500);
        });
        onWillUnmount(() => {
            if (this._chart) {
                this._chart.destroy();
                this._chart = null;
            }
        });
    }

    get projects() {
        return this.props.projects || [];
    }

    get totalTasks() {
        return this.projects.reduce((sum, p) => sum + p.taskCount, 0);
    }

    closePanel() {
        this.state.selectedProject = null;
    }

    async _renderChart() {
        await loadJS(
            "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"
        );

        const projects = this.projects;
        if (!projects.length || !this.chartRef.el) return;

        const labels = projects.map((p) => p.name);
        const data = projects.map((p) => p.taskCount);
        const colors = projects.map((_, i) => COLORS[i % COLORS.length]);
        const hoverColors = projects.map((_, i) => HOVER_COLORS[i % HOVER_COLORS.length]);
        const self = this;

        this._chart = new Chart(this.chartRef.el, {
            type: "doughnut",
            data: {
                labels,
                datasets: [
                    {
                        data,
                        backgroundColor: colors,
                        hoverBackgroundColor: hoverColors,
                        borderColor: "#fff",
                        borderWidth: 3,
                        hoverBorderColor: "#fff",
                        hoverBorderWidth: 4,
                        borderRadius: 6,
                        hoverOffset: 8,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "50%",
                layout: {
                    padding: {top: 8, bottom: 8, left: 8, right: 8},
                },
                onHover(event, elements) {
                    event.native.target.style.cursor = elements.length ? "pointer" : "default";
                },
                plugins: {
                    legend: {
                        display: true,
                        position: "right",
                        labels: {
                            usePointStyle: true,
                            pointStyle: "circle",
                            padding: 16,
                            font: {size: 10, weight: "400", family: "Inter, system-ui, sans-serif"},
                            color: "#475569",
                            generateLabels(chart) {
                                const ds = chart.data.datasets[0];
                                return chart.data.labels.map((label, i) => ({
                                    text: `${label}  (${ds.data[i]})`,
                                    fillStyle: ds.backgroundColor[i],
                                    strokeStyle: ds.backgroundColor[i],
                                    hidden: false,
                                    index: i,
                                    pointStyle: "circle",
                                }));
                            },
                        },
                    },
                    tooltip: {
                        backgroundColor: "#1e293b",
                        titleFont: {size: 13, weight: "700", family: "Inter, system-ui, sans-serif"},
                        bodyFont: {size: 12, weight: "500", family: "Inter, system-ui, sans-serif"},
                        padding: 14,
                        cornerRadius: 12,
                        displayColors: true,
                        boxPadding: 6,
                        callbacks: {
                            title(items) {
                                const idx = items[0].dataIndex;
                                return projects[idx].name;
                            },
                            label(ctx) {
                                const p = projects[ctx.dataIndex];
                                return ` Tasks: ${p.taskCount}`;
                            },
                            afterLabel(ctx) {
                                const p = projects[ctx.dataIndex];
                                return [
                                    ` New: ${p.newTasks}`,
                                    ` Open: ${p.openTasks}`,
                                    ` In Progress: ${p.inProgressTasks}`,
                                    ` Done: ${p.completedTasks}`,
                                    ` Canceled: ${p.canceledTasks}`,
                                    ` Hours: ${p.totalHours}h`,
                                    ` Completion: ${p.completionPercentage}%`,
                                ];
                            },
                        },
                    },
                },
                onClick(_event, elements) {
                    if (elements.length) {
                        const idx = elements[0].index;
                        self.state.selectedProject = {...projects[idx]};
                    }
                },
            },
            plugins: [makeCenterTextPlugin(self.totalTasks)],
        });
    }
}

