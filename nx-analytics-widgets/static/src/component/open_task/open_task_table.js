/** @odoo-module **/
import { Component } from "@odoo/owl";
import { OpenTaskRow } from "./open_task_row.js";

export class OpenTaskTable extends Component {
    static template = "nx_analytics_widgets.OpenTaskTable";
    static components = { OpenTaskRow };
    static props = {
        tasks: Array,
        loading: Boolean,
        onArchive: Function,
    };
}
