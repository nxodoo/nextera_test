/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.NxPortalMagneticButton = publicWidget.Widget.extend({
    selector: "#wrapwrap.nx-warranty-portal-mode .nx-magnetic-btn",

    start() {
        this._buttonInner = this.el.querySelector(".nx-magnetic-btn-inner") || this.el;
        this._rafId = null;
        this._bounds = null;
        this._currentX = 0;
        this._currentY = 0;
        this._targetX = 0;
        this._targetY = 0;
        this._isHovering = false;
        this._strength = parseFloat(this.el.dataset.magneticStrength || "0.32");
        this._maxShift = parseFloat(this.el.dataset.magneticShift || "18");

        this._boundEnter = this._onPointerEnter.bind(this);
        this._boundMove = this._onPointerMove.bind(this);
        this._boundLeave = this._onPointerLeave.bind(this);

        this.el.addEventListener("pointerenter", this._boundEnter);
        this.el.addEventListener("pointermove", this._boundMove);
        this.el.addEventListener("pointerleave", this._boundLeave);

        return this._super(...arguments);
    },

    destroy() {
        this.el.removeEventListener("pointerenter", this._boundEnter);
        this.el.removeEventListener("pointermove", this._boundMove);
        this.el.removeEventListener("pointerleave", this._boundLeave);
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }
        this._super(...arguments);
    },

    _onPointerEnter() {
        this._isHovering = true;
        this._bounds = this.el.getBoundingClientRect();
        this.el.classList.add("is-magnetic-hover");
        this._startAnimation();
    },

    _onPointerMove(event) {
        if (!this._bounds) {
            this._bounds = this.el.getBoundingClientRect();
        }
        const centerX = this._bounds.left + this._bounds.width / 2;
        const centerY = this._bounds.top + this._bounds.height / 2;
        const offsetX = (event.clientX - centerX) * this._strength;
        const offsetY = (event.clientY - centerY) * this._strength;
        this._targetX = Math.max(-this._maxShift, Math.min(this._maxShift, offsetX));
        this._targetY = Math.max(-this._maxShift, Math.min(this._maxShift, offsetY));
        this._startAnimation();
    },

    _onPointerLeave() {
        this._isHovering = false;
        this._targetX = 0;
        this._targetY = 0;
        this.el.classList.remove("is-magnetic-hover");
        this._startAnimation();
    },

    _startAnimation() {
        if (!this._rafId) {
            this._rafId = requestAnimationFrame(() => this._animate());
        }
    },

    _animate() {
        this._currentX += (this._targetX - this._currentX) * 0.16;
        this._currentY += (this._targetY - this._currentY) * 0.16;

        const closeEnough = Math.abs(this._targetX - this._currentX) < 0.1 && Math.abs(this._targetY - this._currentY) < 0.1;
        this._buttonInner.style.transform = `translate3d(${this._currentX}px, ${this._currentY}px, 0)`;

        if (!closeEnough || this._isHovering) {
            this._rafId = requestAnimationFrame(() => this._animate());
        } else {
            this._buttonInner.style.transform = "";
            this._currentX = 0;
            this._currentY = 0;
            this._rafId = null;
        }
    },
});
