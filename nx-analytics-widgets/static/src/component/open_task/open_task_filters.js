/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

const FILTERS = [
    { key: '', label: 'All' },
    { key: 'overdue', label: 'Overdue' },
    { key: 'due_soon', label: 'Due Soon' },
    { key: 'no_deadline', label: 'No Deadline' },
];

export class OpenTaskFilters extends Component {
    static template = "nx_analytics_widgets.OpenTaskFilters";
    static props = {
        filterKey: String,
        sortKey: String,
        sortOrder: String,
        search: String,
        loading: Boolean,
        onFilter: Function,
        onSortKey: Function,
        onSortOrder: Function,
        onApplySearch: Function,
    };

    setup() {
        this.local = useState({ search: this.props.search });
    }

    get filters() {
        return FILTERS;
    }

    onFilterClick(key) {
        this.props.onFilter(key);
    }

    onSearchInput(ev) {
        this.local.search = ev.target.value;
    }

    onSearchKeydown(ev) {
        if (ev.key === 'Enter') {
            this.props.onApplySearch(this.local.search);
        }
    }

    onApplySearch() {
        this.props.onApplySearch(this.local.search);
    }

    onClearSearch() {
        this.local.search = '';
        this.props.onApplySearch('');
    }

    onToggleSortOrder() {
        this.props.onSortOrder();
    }

    onSortKeyChange(ev) {
        this.props.onSortKey(ev.target.value);
    }
}
