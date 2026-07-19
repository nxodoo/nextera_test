/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.PortalSidebarTrigger = publicWidget.Widget.extend({
    selector: '.portal-sidebar-layout',
    events: {
        'click .portal-sidebar__trigger': '_onTriggerClick',
        'input .portal-sidebar__search-input': '_onSearchInput',
        'click .portal-sidebar__search-clear': '_onSearchClear',
        'click .portal-sidebar__user-trigger': '_onUserTriggerClick',
    },

    start() {
        this._super(...arguments);
        // Restore collapsed state from localStorage
        const collapsed = localStorage.getItem('portal_sidebar_collapsed') === 'true';
        if (collapsed) {
            this.el.classList.add('sidebar-collapsed');
        }
        // Bind ⌘K / Ctrl+K shortcut to focus search
        this._onKeyDown = this._onKeyDown.bind(this);
        document.addEventListener('keydown', this._onKeyDown);
        // Bind outside click to close popover
        this._onOutsideClick = this._onOutsideClick.bind(this);
        document.addEventListener('click', this._onOutsideClick);
    },

    destroy() {
        document.removeEventListener('keydown', this._onKeyDown);
        document.removeEventListener('click', this._onOutsideClick);
        this._super(...arguments);
    },

    _onKeyDown(ev) {
        if ((ev.metaKey || ev.ctrlKey) && ev.key === 'k') {
            ev.preventDefault();
            const input = this.el.querySelector('.portal-sidebar__search-input');
            if (input) {
                input.focus();
                input.select();
            }
        }
    },

    _onTriggerClick() {
        this.el.classList.toggle('sidebar-collapsed');
        const isCollapsed = this.el.classList.contains('sidebar-collapsed');
        localStorage.setItem('portal_sidebar_collapsed', isCollapsed);
    },

    _onSearchInput(ev) {
        const input = ev.currentTarget;
        const query = input.value.toLowerCase().trim();
        const searchWrapper = input.closest('.portal-sidebar__search');

        // Toggle has-value class for clear button visibility
        if (query.length > 0) {
            searchWrapper.classList.add('has-value');
        } else {
            searchWrapper.classList.remove('has-value');
        }

        // Filter links
        const links = this.el.querySelectorAll('.portal-sidebar .portal-sidebar__nav .portal-sidebar__link');
        links.forEach(function (link) {
            const text = link.textContent.toLowerCase();
            link.style.display = (query === '' || text.includes(query)) ? '' : 'none';
        });
    },

    _onSearchClear() {
        const input = this.el.querySelector('.portal-sidebar__search-input');
        const searchWrapper = input.closest('.portal-sidebar__search');
        input.value = '';
        searchWrapper.classList.remove('has-value');
        input.focus();

        // Reset all links visibility
        const links = this.el.querySelectorAll('.portal-sidebar .portal-sidebar__nav .portal-sidebar__link');
        links.forEach(function (link) {
            link.style.display = '';
        });
    },

    _onUserTriggerClick(ev) {
        ev.stopPropagation();
        const wrapper = ev.currentTarget.closest('.portal-sidebar__user-wrapper');
        // Close all other open popovers
        this.el.querySelectorAll('.portal-sidebar__user-wrapper.open').forEach(function (w) {
            if (w !== wrapper) w.classList.remove('open');
        });
        wrapper.classList.toggle('open');
    },

    _onOutsideClick(ev) {
        // Close popover if clicking outside the user wrapper
        const wrappers = this.el.querySelectorAll('.portal-sidebar__user-wrapper.open');
        wrappers.forEach(function (wrapper) {
            if (!wrapper.contains(ev.target)) {
                wrapper.classList.remove('open');
            }
        });
    },
});

