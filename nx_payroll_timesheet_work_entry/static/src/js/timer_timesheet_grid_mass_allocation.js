/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { onWillStart } from "@odoo/owl";
import { GridController } from "@web_grid/views/grid_controller";

patch(GridController.prototype, {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.canManageInternalProjectEntries = false;
        onWillStart(async () => {
            this.canManageInternalProjectEntries =
                await user.hasGroup(
                    "nx_payroll_timesheet_work_entry.group_manage_internal_project_entries"
                );
        });
    },

    /**
     * Show the mass allocation button only on analytic timesheet grids for
     * users allowed to manage restricted internal project entries.
     *
     * @returns {boolean}
     */
    get showMassInternalAllocationButton() {
        return Boolean(
            this.canManageInternalProjectEntries &&
            this.props.resModel === "account.analytic.line"
        );
    },

    /**
     * Open the shared mass allocation wizard from the Timesheets toolbar.
     *
     * The wizard keeps the project field empty so HR/Admin can choose any
     * restricted internal project, including the normal Internal project.
     *
     * @returns {Promise<void>}
     */
    async openMassInternalAllocationWizard() {
        await this.actionService.doAction({
            name: _t("Internal Project Mass Allocation"),
            type: "ir.actions.act_window",
            res_model: "nx.internal.project.mass.allocation.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {},
        });
    },
});
