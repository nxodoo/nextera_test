/** @odoo-module **/
import { Component } from "@odoo/owl";
import { ExpenseRow } from "./expense_row";

export class ExpenseTable extends Component {
    static template = "nx_analytics_widgets.ExpenseTable";
    static components = { ExpenseRow };
    static props = {
        expenses: Array,
        loading:  Boolean,
        onDelete: Function,
        onView:   Function,
        onEdit:   Function,
    };
}

