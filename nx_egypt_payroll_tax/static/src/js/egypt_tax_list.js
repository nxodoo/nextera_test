/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";

export class EgyptTaxListController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    onTestCalculation() {
        this.actionService.doAction(
            "nx_egypt_payroll_tax.action_nx_egypt_payroll_tax_test"
        );
    }
}

registry.category("views").add("egypt_tax_list", {
    ...listView,
    Controller: EgyptTaxListController,
    buttonTemplate: "nx_egypt_payroll_tax.ListButtons",
});
