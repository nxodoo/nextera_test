/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const CHANGE_LABELS = {
    set: "set",
    change: "changed",
    clear: "cleared",
    add: "added",
    remove: "removed",
    create_child: "line added",
    update_child: "line updated",
    delete_child: "line removed",
};

export class AuditTimeline extends Component {
    static template = "nx_audit_log.Timeline";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.changeLabels = CHANGE_LABELS;
        this.state = useState({ data: null, showDerived: true });
        const params = this.props.action.params || {};
        this.model = params.model;
        this.resId = params.res_id;
        onWillStart(async () => {
            this.state.data = await this.orm.call("audit.log", "get_timeline", [this.model, this.resId]);
        });
    }

    visibleLines(event) {
        return this.state.showDerived ? event.lines : event.lines.filter((l) => l.origin !== "derived");
    }

    toggleDerived() {
        this.state.showDerived = !this.state.showDerived;
    }

    openEvent(event) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "audit.log",
            res_id: event.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("nx_audit_log.timeline", AuditTimeline);
