/** @odoo-module **/

/**
 * Shared data-viz theme for the HR Analytics dashboard.
 *
 * Colour tokens live in hr_dashboard.scss as CSS custom properties (so light /
 * dark are declared in one place) and are read back here at render time. The
 * status triplet was validated with the data-viz palette validator:
 *
 *   light  #12855a / #eda100 / #d03b3b  → all checks pass,
 *                                         worst adjacent CVD ΔE 17.3 (protan)
 *   dark   #1faa72 / #e3a41a / #e66767  → CVD ΔE 9.1, contrast ≥ 3:1
 *
 * The previous #22C55E / #F59E0B / #EF4444 triplet FAILED CVD separation at
 * ΔE 5.7 (protan): red-green colourblind readers could not tell "Complete"
 * from "Incomplete" in the compliance donut.
 */

/** Read the resolved design tokens off any element inside the dashboard. */
export function readTokens(el) {
    const cs = getComputedStyle(el);
    const v = (name, fallback) => (cs.getPropertyValue(name) || "").trim() || fallback;
    return {
        surface: v("--nx-chart-surface", "#ffffff"),
        grid: v("--nx-chart-grid", "rgba(16,24,40,.07)"),
        text: v("--nx-chart-text", "#1F2937"),
        textMuted: v("--nx-chart-text-muted", "#6B7A8D"),
        tooltipBg: v("--nx-chart-tooltip-bg", "#1F2937"),
        tooltipText: v("--nx-chart-tooltip-text", "#ffffff"),
        // One hue for a single series — bar length already carries magnitude.
        series: v("--nx-chart-series", "#1A5C3A"),
        good: v("--nx-chart-good", "#12855a"),
        warning: v("--nx-chart-warning", "#eda100"),
        critical: v("--nx-chart-critical", "#d03b3b"),
        // Categorical slots (identity, not state) — validated on the adjacent
        // pairlist: worst CVD ΔE 9.1 light / 8.4 dark.
        cat1: v("--nx-cat-1", "#2a78d6"),
        cat2: v("--nx-cat-2", "#eb6834"),
        cat3: v("--nx-cat-3", "#1baf7a"),
        cat4: v("--nx-cat-4", "#eda100"),
    };
}

/** Honour the OS "reduce motion" setting — animation is opt-out, not forced. */
export function prefersReducedMotion() {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false;
}

/**
 * Staggered grow-in animation. Each mark starts slightly after the previous
 * one, which reads as the chart "building" rather than popping.
 */
export function entryAnimation({ stagger = 45, duration = 750 } = {}) {
    if (prefersReducedMotion()) {
        return { duration: 0 };
    }
    return {
        duration,
        easing: "easeOutQuart",
        delay(ctx) {
            // Only stagger the initial draw, never hover/resize re-draws.
            if (ctx.type === "data" && ctx.mode === "default" && !ctx.dropped) {
                return ctx.dataIndex * stagger;
            }
            return 0;
        },
    };
}

/** Tooltip styling shared by every chart (rounded, padded, on-surface). */
export function tooltipStyle(t, extra = {}) {
    return {
        backgroundColor: t.tooltipBg,
        titleColor: t.tooltipText,
        bodyColor: t.tooltipText,
        borderColor: "rgba(255,255,255,.12)",
        borderWidth: 1,
        cornerRadius: 10,
        padding: { top: 9, right: 12, bottom: 9, left: 12 },
        titleFont: { size: 12, weight: "600" },
        bodyFont: { size: 12.5, weight: "500" },
        displayColors: false,
        ...extra,
    };
}

/** Base options every chart starts from. */
export function baseOptions(t) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: entryAnimation(),
        // Bigger-than-the-mark hit targets.
        interaction: { mode: "nearest", intersect: true },
        plugins: {
            legend: { display: false },
            tooltip: tooltipStyle(t),
        },
    };
}

/** Recessive solid hairline axis — never dashed. */
export function valueAxis(t, extra = {}) {
    return {
        beginAtZero: true,
        grid: { color: t.grid, drawTicks: false, lineWidth: 1 },
        border: { display: false },
        ticks: {
            color: t.textMuted,
            font: { size: 11 },
            padding: 6,
            precision: 0,
            // A recessive axis needs a handful of reference lines, not a dense ladder.
            maxTicksLimit: 6,
        },
        ...extra,
    };
}

export function categoryAxis(t, extra = {}) {
    return {
        grid: { display: false },
        border: { display: false },
        ticks: { color: t.textMuted, font: { size: 11.5 }, padding: 4 },
        ...extra,
    };
}

/**
 * Vertical fill gradient for area charts — the brand hue fading into the
 * surface, so the fill reads as recessive support for the line.
 */
export function areaGradient(chartCtx, area, hex) {
    if (!area) {
        return withAlpha(hex, 0.14);
    }
    const g = chartCtx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, withAlpha(hex, 0.22));
    g.addColorStop(1, withAlpha(hex, 0.01));
    return g;
}

export function withAlpha(hex, alpha) {
    const h = (hex || "").replace("#", "").trim();
    if (h.length !== 6) {
        return hex;
    }
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
}

/**
 * Draws the value at the end of each bar, so a value is never reachable only
 * by hovering. Registered per-chart via the `plugins` array.
 */
export const barValueLabels = {
    id: "nxBarValueLabels",
    afterDatasetsDraw(chart, _args, opts) {
        const { ctx } = chart;
        const horizontal = opts?.horizontal !== false;
        const color = opts?.color || "#1F2937";
        const fmt = opts?.format || ((v) => v);
        ctx.save();
        ctx.font = "600 11.5px Inter, system-ui, sans-serif";
        ctx.fillStyle = color;
        ctx.textBaseline = "middle";
        for (const meta of chart.getSortedVisibleDatasetMetas()) {
            meta.data.forEach((el, i) => {
                const raw = chart.data.datasets[meta.index].data[i];
                if (raw === null || raw === undefined || raw === 0) {
                    return;
                }
                const label = String(fmt(raw));
                if (horizontal) {
                    ctx.textAlign = "left";
                    ctx.fillText(label, el.x + 8, el.y);
                } else {
                    ctx.textAlign = "center";
                    ctx.fillText(label, el.x, el.y - 9);
                }
            });
        }
        ctx.restore();
    },
};

/**
 * Waterfall step connectors — thin solid hairlines linking the settled total
 * of one bar to the start of the next, so the chart reads as a running
 * subtraction rather than five unrelated bars. Solid, never dashed.
 */
export const waterfallConnectors = {
    id: "nxWaterfallConnectors",
    beforeDatasetsDraw(chart, _args, opts) {
        const meta = chart.getDatasetMeta(0);
        const steps = opts?.steps || [];
        const scale = chart.scales.y;
        if (!meta?.data?.length || !scale) {
            return;
        }
        const { ctx } = chart;
        ctx.save();
        ctx.strokeStyle = opts?.color || "rgba(0,0,0,.22)";
        ctx.lineWidth = 1;
        for (let i = 0; i < meta.data.length - 1; i++) {
            const step = steps[i];
            if (!step) {
                continue;
            }
            // Where the running total sits once this step has been applied.
            const settled = step.kind === "total" ? step.to : step.from;
            const y = Math.round(scale.getPixelForValue(settled)) + 0.5;
            const a = meta.data[i];
            const b = meta.data[i + 1];
            ctx.beginPath();
            ctx.moveTo(a.x + a.width / 2, y);
            ctx.lineTo(b.x - b.width / 2, y);
            ctx.stroke();
        }
        ctx.restore();
    },
};

/**
 * Labels each waterfall bar above its top edge — signed for the deductions
 * so the direction of each step is readable without the tooltip.
 */
export const waterfallLabels = {
    id: "nxWaterfallLabels",
    afterDatasetsDraw(chart, _args, opts) {
        const meta = chart.getDatasetMeta(0);
        const steps = opts?.steps || [];
        const fmt = opts?.format || ((v) => v);
        const { ctx } = chart;
        ctx.save();
        ctx.font = "700 11.5px Inter, system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        meta.data.forEach((bar, i) => {
            const step = steps[i];
            if (!step) {
                return;
            }
            ctx.fillStyle = step.kind === "down"
                ? (opts?.downColor || "#b4531f")
                : (opts?.color || "#1F2937");
            const text = step.kind === "down"
                ? `−${fmt(Math.abs(step.value))}`
                : fmt(step.value);
            ctx.fillText(text, bar.x, Math.min(bar.y, bar.base) - 7);
        });
        ctx.restore();
    },
};

/**
 * Keeps the last segment of a hierarchical name ("A / B / C" → "C") and
 * truncates what is left, so long department paths stay legible. The full
 * value still shows in the tooltip.
 */
export function shortLabel(label, max = 22) {
    const leaf = String(label ?? "").split("/").pop().trim() || String(label ?? "");
    return leaf.length > max ? `${leaf.slice(0, max - 1)}…` : leaf;
}
