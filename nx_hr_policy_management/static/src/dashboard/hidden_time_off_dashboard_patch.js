/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { TimeOffDashboard } from "@hr_holidays/dashboard/time_off_dashboard";

patch(TimeOffDashboard.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.hiddenHolidays = [];
        this.state.showHiddenRail = false;
    },

    async loadDashboardData(date = false) {
        await super.loadDashboardData(date);
        this.state.hiddenHolidays = await this.orm.call(
            "hr.leave.type",
            "get_hidden_allocation_data_request",
            [this.state.date],
            {
                context: this.getContext(),
            }
        );
    },

    toggleHiddenRail() {
        this.state.showHiddenRail = !this.state.showHiddenRail;
    },
});
