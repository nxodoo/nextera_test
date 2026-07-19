/** @odoo-module **/

/**
 * Interactive enhancements for nx_summary_stat_cards
 * Adds click interactions, tooltips, and smooth animations
 */

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.NxStatCardsInteractive = publicWidget.Widget.extend({
    selector: '.nx-analytics-widget--enhanced',
    events: {
        'click .nx-aw-chip': '_onChipClick',
        'mouseenter .nx-aw-chip': '_onChipHover',
        'mouseleave .nx-aw-chip': '_onChipLeave',
    },

    /**
     * @override
     */
    start: function () {
        this._super.apply(this, arguments);
        this._initAnimations();
        this._initTooltips();
        return this._super(...arguments);
    },

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * Initialize entrance animations
     * @private
     */
    _initAnimations: function () {
        const chips = this.el.querySelectorAll('.nx-aw-chip');
        chips.forEach((chip, index) => {
            chip.style.opacity = '0';
            chip.style.transform = 'translateY(20px)';

            setTimeout(() => {
                chip.style.transition = 'all 0.5s cubic-bezier(0.4, 0, 0.2, 1)';
                chip.style.opacity = '1';
                chip.style.transform = 'translateY(0)';
            }, 100 * index);
        });
    },

    /**
     * Initialize tooltips for chips
     * @private
     */
    _initTooltips: function () {
        const chips = this.el.querySelectorAll('.nx-aw-chip');
        chips.forEach((chip) => {
            const type = chip.dataset.statType;
            let tooltipText = '';

            switch(type) {
                case 'balance':
                    tooltipText = 'Total available leave days across all types';
                    break;
                case 'pending':
                    tooltipText = 'Leave requests awaiting approval';
                    break;
                case 'approved':
                    tooltipText = 'Successfully approved leave requests';
                    break;
                case 'total':
                    tooltipText = 'All leave requests (all statuses)';
                    break;
            }

            if (tooltipText) {
                chip.setAttribute('title', tooltipText);
                chip.setAttribute('data-bs-toggle', 'tooltip');
                chip.setAttribute('data-bs-placement', 'top');
            }
        });

        // Initialize Bootstrap tooltips if available
        if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
            const tooltipTriggerList = this.el.querySelectorAll('[data-bs-toggle="tooltip"]');
            [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
        }
    },

    /**
     * Add ripple effect on chip
     * @private
     */
    _addRippleEffect: function (chip, event) {
        const ripple = document.createElement('span');
        const rect = chip.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = event.clientX - rect.left - size / 2;
        const y = event.clientY - rect.top - size / 2;

        ripple.style.cssText = `
            position: absolute;
            width: ${size}px;
            height: ${size}px;
            left: ${x}px;
            top: ${y}px;
            background: rgba(255, 255, 255, 0.4);
            border-radius: 50%;
            transform: scale(0);
            animation: ripple-animation 0.6s ease-out;
            pointer-events: none;
        `;

        chip.appendChild(ripple);

        setTimeout(() => {
            ripple.remove();
        }, 600);
    },

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Handle chip click
     * @private
     */
    _onChipClick: function (ev) {
        const chip = ev.currentTarget;
        const type = chip.dataset.statType;

        this._addRippleEffect(chip, ev);

        // Optional: Filter table by stat type
        // You can emit a custom event or directly filter the leave table
        console.log(`Stat card clicked: ${type}`);

        // Add pulse effect
        chip.style.animation = 'none';
        setTimeout(() => {
            chip.style.animation = 'chip-pulse 0.4s ease';
        }, 10);
    },

    /**
     * Handle chip hover
     * @private
     */
    _onChipHover: function (ev) {
        const chip = ev.currentTarget;
        const icon = chip.querySelector('.nx-aw-chip-icon');

        if (icon) {
            icon.style.transform = 'scale(1.15) rotate(8deg)';
        }
    },

    /**
     * Handle chip leave
     * @private
     */
    _onChipLeave: function (ev) {
        const chip = ev.currentTarget;
        const icon = chip.querySelector('.nx-aw-chip-icon');

        if (icon) {
            icon.style.transform = 'scale(1) rotate(0deg)';
        }
    },
});

// Add CSS animations dynamically
const style = document.createElement('style');
style.textContent = `
    @keyframes ripple-animation {
        to {
            transform: scale(4);
            opacity: 0;
        }
    }
    
    @keyframes chip-pulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(0.98); }
    }
`;
document.head.appendChild(style);

