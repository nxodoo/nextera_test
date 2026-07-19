/** @odoo-module **/
import { Component } from "@odoo/owl";

const FILTERS = [
    { key: '',         label: 'All' },
    { key: 'pending',  label: 'Pending' },
    { key: 'approved', label: 'Approved' },
    { key: 'partial',  label: 'Partial' },
    { key: 'draft',    label: 'Draft' },
    { key: 'refused',  label: 'Refused' },
];

export class LeaveFilters extends Component {
    static template = "nx_analytics_widgets.LeaveFilters";
    static props = {
        stateFilter: String,
        sortOrder:   String,
        search:      String,
        loading:     Boolean,
        onFilter:    Function,
        onSort:      Function,
        onSearch:    Function,
    };

    get filters() { return FILTERS; }

    onFilterClick(key) {
        this.props.onFilter(key);
    }

    onSortClick() {
        this.props.onSort();
    }

    onSearchInput(ev) {
        this.props.onSearch(ev.target.value);
    }
}

