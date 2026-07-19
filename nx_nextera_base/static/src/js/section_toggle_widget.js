/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onMounted, onPatched, useRef } from "@odoo/owl";

export class SectionToggle extends Component {
    static template = "nx_nextera_base.SectionToggle";

    static props = {
        defaultOpen: { type: String, optional: true },
        record:      { type: Object, optional: true },
        "*": true,
    };

    setup() {
        this.rootRef = useRef("root");

        this.state = useState({
            isOpen: this.props.defaultOpen === "true",
            title: "Section",
            icon: "fa-folder",
            color: "#3B82F6",
        });

        onMounted(() => {
            this._initFromDOM();
            this._applyVisibility(false);
        });

        onPatched(() => {
            this._applyVisibility(false);
        });
    }

    _initFromDOM() {
        const target = this._getTarget();
        if (!target) return;

        const meta = target.querySelector(".nx_section_meta");

        if (meta) {
            this.state.title = meta.dataset.title || "Section";
            this.state.icon  = meta.dataset.icon  || "fa-folder";
            this.state.color = meta.dataset.color || "#3B82F6";
        }
    }

    toggle() {
        this.state.isOpen = !this.state.isOpen;
        this._applyVisibility(true);
    }

    _getTarget() {
        if (!this.rootRef.el) return null;

        let current = this.rootRef.el;

        while (current) {
            let sibling = current.nextElementSibling;
            while (sibling) {
                if (sibling.matches?.(".closed-section")) {
                    return sibling;
                }

                const nestedSection = sibling.querySelector?.(".closed-section");
                if (nestedSection) {
                    return nestedSection;
                }

                sibling = sibling.nextElementSibling;
            }

            current = current.parentElement;
        }

        return null;
    }

    _applyVisibility(animate) {
        const target = this._getTarget();
        if (!target) return;

        if (this.state.isOpen) {
            target.style.display = "";
            target.style.overflow = "";

            if (animate) {
                target.style.animation = "none";
                void target.offsetHeight;
                target.style.animation = "nxSectionSlideDown 0.25s ease-out";
            }
        } else {
            target.style.display = "none";
        }
    }
}

const viewWidgetsRegistry = registry.category("view_widgets");

viewWidgetsRegistry.add(
    "section_toggle",
    {
        component: SectionToggle,
    },
    {
        force: true,
    }
);
