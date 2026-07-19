/** @odoo-module **/

import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { listView } from "@web/views/list/list_view";

const viewRegistry = registry.category("views");

if (!viewRegistry.contains("hr_payslip_form")) {
    viewRegistry.add("hr_payslip_form", {
        ...formView,
    });
}

if (!viewRegistry.contains("hr_payroll_payslip_tree")) {
    viewRegistry.add("hr_payroll_payslip_tree", {
        ...listView,
    });
}
