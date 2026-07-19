/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.NxPortalTextType = publicWidget.Widget.extend({
    selector: "#wrapwrap.nx-warranty-portal-mode .nx-typewriter",

    start() {
        this._phrases = this._readPhrases();
        this._textNode = this.el.querySelector(".nx-typewriter-text");
        this._cursorNode = this.el.querySelector(".nx-typewriter-cursor");
        this._phraseIndex = 0;
        this._charIndex = 0;
        this._isDeleting = false;
        this._hasStarted = false;
        this._tickTimeout = null;
        this._typeSpeed = parseInt(this.el.dataset.typeSpeed || "58", 10);
        this._deleteSpeed = parseInt(this.el.dataset.deleteSpeed || "34", 10);
        this._holdDelay = parseInt(this.el.dataset.holdDelay || "1500", 10);
        this._startDelay = parseInt(this.el.dataset.startDelay || "260", 10);

        if (!this._textNode || !this._phrases.length) {
            return Promise.resolve();
        }

        if ("IntersectionObserver" in window) {
            this._observer = new IntersectionObserver((entries) => {
                const isVisible = entries.some((entry) => entry.isIntersecting);
                if (isVisible) {
                    this._beginTyping();
                    this._observer.disconnect();
                    this._observer = null;
                }
            }, { threshold: 0.35 });
            this._observer.observe(this.el);
        } else {
            this._beginTyping();
        }

        return this._super(...arguments);
    },

    destroy() {
        if (this._tickTimeout) {
            clearTimeout(this._tickTimeout);
            this._tickTimeout = null;
        }
        if (this._observer) {
            this._observer.disconnect();
            this._observer = null;
        }
        this._super(...arguments);
    },

    _readPhrases() {
        const raw = this.el.dataset.phrases || "";
        return raw
            .split("|")
            .map((phrase) => phrase.trim())
            .filter(Boolean);
    },

    _beginTyping() {
        if (this._hasStarted) {
            return;
        }
        this._hasStarted = true;
        this.el.classList.add("is-active");
        this._queueNextTick(this._startDelay);
    },

    _queueNextTick(delay) {
        this._tickTimeout = setTimeout(() => this._tick(), delay);
    },

    _tick() {
        const phrase = this._phrases[this._phraseIndex] || "";
        if (!phrase) {
            return;
        }

        if (this._isDeleting) {
            this._charIndex = Math.max(0, this._charIndex - 1);
        } else {
            this._charIndex = Math.min(phrase.length, this._charIndex + 1);
        }

        this._textNode.textContent = phrase.slice(0, this._charIndex);

        if (!this._isDeleting && this._charIndex === phrase.length) {
            this._isDeleting = true;
            this._queueNextTick(this._holdDelay);
            return;
        }

        if (this._isDeleting && this._charIndex === 0) {
            this._isDeleting = false;
            this._phraseIndex = (this._phraseIndex + 1) % this._phrases.length;
            this._queueNextTick(260);
            return;
        }

        const nextDelay = this._isDeleting ? this._deleteSpeed : this._typeSpeed;
        this._queueNextTick(nextDelay);
    },
});
