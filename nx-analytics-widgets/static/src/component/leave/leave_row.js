/** @odoo-module **/
import { Component } from "@odoo/owl";

/** Map Odoo state key → BEM modifier for the pill */
const STATE_CLASS = {
    draft:     'draft',
    confirm:   'confirm',
    validate1: 'validate1',
    validate:  'validate',
    refuse:    'refuse',
};

export class LeaveRow extends Component {
    static template = "nx_analytics_widgets.LeaveRow";
    static props = {
        leave:    Object,
        index:    Number,
        onCancel: Function,
    };

    get stateClass() {
        return STATE_CLASS[this.props.leave.state] || 'draft';
    }

    onCancelClick() {
        this.props.onCancel(this.props.leave.id);
    }
}

