/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

const FILTERS = [
    { key: '',          label: 'All' },
    { key: 'draft',     label: 'To Report' },
    { key: 'reported',  label: 'To Submit' },
    { key: 'submitted', label: 'Submitted' },
    { key: 'approved',  label: 'Approved' },
    { key: 'done',      label: 'Done' },
    { key: 'refused',   label: 'Refused' },
];

const SORT_OPTIONS = [
    { key: 'date',   label: 'Date' },
    { key: 'amount', label: 'Amount' },
    { key: 'state',  label: 'Status' },
];

export class ExpenseFilters extends Component {
    static template = "nx_analytics_widgets.ExpenseFilters";
    static props = {
        stateFilter: String,
        sortKey:     String,
        sortOrder:   String,
        search:      String,
        loading:     Boolean,
        onFilter:    Function,
        onSortKey:   Function,
        onSortOrder: Function,
        onApplySearch: Function,
    };

    setup() {
        this.local = useState({ search: this.props.search });
    }

    get filters() { return FILTERS; }
    get sortOptions() { return SORT_OPTIONS; }

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

