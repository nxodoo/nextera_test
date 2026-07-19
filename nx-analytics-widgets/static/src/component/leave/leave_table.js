/** @odoo-module **/
import { Component } from "@odoo/owl";
import { LeaveRow } from "./leave_row";

export class LeaveTable extends Component {
    static template = "nx_analytics_widgets.LeaveTable";
    static components = { LeaveRow };
    static props = {
        leaves:   Array,
        loading:  Boolean,
        onCancel: Function,
    };
}

