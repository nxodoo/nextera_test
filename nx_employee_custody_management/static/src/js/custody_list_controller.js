/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/**
 * Custody Requests list: the "New" button (and the empty-state "Create new
 * document" placeholder) open the create wizard instead of a blank form.
 */
export class CustodyRequestListController extends ListController {
    async createRecord() {
        return this.actionService.doAction(
            "nx_employee_custody_management.action_custody_create_wizard",
            {
                onClose: () => this.model.root.load(),
            }
        );
    }
}

registry.category("views").add("custody_request_list", {
    ...listView,
    Controller: CustodyRequestListController,
});
