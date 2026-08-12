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
    const c = toRgb(hex);
    return c ? `rgba(${c.r},${c.g},${c.b},${alpha})` : hex;
}

/** Parse "#rgb" / "#rrggbb" / "rgb()" / "rgba()" into {r,g,b,a}. */
export function toRgb(color) {
    const s = String(color || "").trim();
    if (s.startsWith("#")) {
        let h = s.slice(1);
        if (h.length === 3) {
            h = h.split("").map((ch) => ch + ch).join("");
        }
        if (h.length !== 6) {
            return null;
        }
        return {
            r: parseInt(h.slice(0, 2), 16),
            g: parseInt(h.slice(2, 4), 16),
            b: parseInt(h.slice(4, 6), 16),
            a: 1,
        };
    }
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) {
        return null;
    }
    const p = m[1].split(",").map((v) => parseFloat(v));
    return { r: p[0] | 0, g: p[1] | 0, b: p[2] | 0, a: p.length > 3 ? p[3] : 1 };
}

/**
 * Move a colour toward black (amount < 0) or white (amount > 0).
 * Used for the lit top face and the shaded side wall of the 3D marks.
 */
export function shade(color, amount, alpha) {
    const c = toRgb(color);
    if (!c) {
        return color;
    }
    const t = amount < 0 ? 0 : 255;
    const k = Math.abs(amount);
    const mix = (v) => Math.round(v + (t - v) * k);
    return `rgba(${mix(c.r)},${mix(c.g)},${mix(c.b)},${alpha ?? c.a})`;
}

/** Ordered categorical ramp — identity slots, never state. */
export function catPalette(t) {
    return [t.cat1, t.cat3, t.cat4, t.cat2, t.series, t.good, t.critical, t.warning];
}

/**
 * Glossy fill for a bar: a lighter tint at the base fading into the full hue,
 * so a flat rectangle reads as a lit, rounded solid.
 */
export function barGradient(chartCtx, area, hex, horizontal = false) {
    if (!area) {
        return withAlpha(hex, 0.9);
    }
    const g = horizontal
        ? chartCtx.createLinearGradient(area.left, 0, area.right, 0)
        : chartCtx.createLinearGradient(0, area.bottom, 0, area.top);
    g.addColorStop(0, shade(hex, -0.12, 0.95));
    g.addColorStop(0.55, withAlpha(hex, 0.95));
    g.addColorStop(1, shade(hex, 0.34, 0.98));
    return g;
}

/**
 * Extrudes doughnut / pie / polar-area slices: the same arc path is stamped
 * repeatedly a pixel lower each time, in a progressively darker shade, so the
 * ring gains a solid side wall. The real Chart.js arcs stay untouched on top,
 * which keeps hover hit-testing exact — a squashed/rotated canvas transform
 * would have moved the marks away from their hit boxes.
 */
export const arcDepth = {
    id: "nxArcDepth",
    beforeDatasetsDraw(chart, _args, opts) {
        if (opts?.enabled === false) {
            return;
        }
        const meta = chart.getDatasetMeta(0);
        if (!meta?.data?.length) {
            return;
        }
        const depth = Math.max(1, Math.round(opts?.depth ?? 14));
        const colors = chart.data.datasets[0]?.backgroundColor || [];
        const { ctx } = chart;
        ctx.save();
        for (let layer = depth; layer >= 1; layer--) {
            // Deepest layer darkest — the wall falls away from the light.
            const k = layer / depth;
            meta.data.forEach((arc, i) => {
                const base = Array.isArray(colors) ? colors[i] : colors;
                const off = arc.options?.offset || 0;
                const mid = (arc.startAngle + arc.endAngle) / 2;
                ctx.save();
                ctx.translate(Math.cos(mid) * off, Math.sin(mid) * off + layer);
                ctx.fillStyle = shade(base, -(0.18 + 0.34 * k), 1);
                ctx.beginPath();
                ctx.arc(arc.x, arc.y, arc.outerRadius, arc.startAngle, arc.endAngle);
                if (arc.innerRadius > 0) {
                    ctx.arc(arc.x, arc.y, arc.innerRadius, arc.endAngle, arc.startAngle, true);
                } else {
                    ctx.lineTo(arc.x, arc.y);
                }
                ctx.closePath();
                ctx.fill();
                ctx.restore();
            });
        }
        ctx.restore();
    },
    /** Specular sheen across the top face, clipped to the ring itself. */
    afterDatasetsDraw(chart, _args, opts) {
        if (opts?.enabled === false || opts?.gloss === false) {
            return;
        }
        const meta = chart.getDatasetMeta(0);
        const first = meta?.data?.[0];
        if (!first) {
            return;
        }
        const { ctx } = chart;
        const { x, y, outerRadius, innerRadius } = first;
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, outerRadius, 0, Math.PI * 2);
        if (innerRadius > 0) {
            ctx.arc(x, y, innerRadius, Math.PI * 2, 0, true);
        }
        ctx.clip();
        const g = ctx.createLinearGradient(x, y - outerRadius, x, y + outerRadius);
        g.addColorStop(0, "rgba(255,255,255,.30)");
        g.addColorStop(0.42, "rgba(255,255,255,.05)");
        g.addColorStop(1, "rgba(0,0,0,.10)");
        ctx.fillStyle = g;
        ctx.fillRect(x - outerRadius, y - outerRadius, outerRadius * 2, outerRadius * 2);
        ctx.restore();
    },
};

/**
 * Casts a soft drop shadow under the marks of a dataset, so bars and lines sit
 * above the card rather than being painted onto it. Scoped to the dataset draw
 * so it never bleeds onto the grid or the axis text.
 */
export const markShadow = {
    id: "nxMarkShadow",
    beforeDatasetDraw(chart, _args, opts) {
        if (opts?.enabled === false) {
            return;
        }
        const { ctx } = chart;
        ctx.save();
        ctx.shadowColor = opts?.color || "rgba(16,24,40,.22)";
        ctx.shadowBlur = opts?.blur ?? 10;
        ctx.shadowOffsetX = opts?.offsetX ?? 0;
        ctx.shadowOffsetY = opts?.offsetY ?? 4;
    },
    afterDatasetDraw(chart, _args, opts) {
        if (opts?.enabled === false) {
            return;
        }
        chart.ctx.restore();
    },
};

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
