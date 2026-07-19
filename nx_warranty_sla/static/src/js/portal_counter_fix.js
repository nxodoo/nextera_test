/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

const PortalHomeCounters = publicWidget.registry.PortalHomeCounters;

if (PortalHomeCounters) {
    PortalHomeCounters.include({
        async _updateCounters(...args) {
            try {
                return await this._super(...args);
            } catch (error) {
                const isTextContentNull = error instanceof TypeError && String(error.message || "").includes("textContent");
                if (!isTextContentNull) {
                    throw error;
                }
                const spinner = this.el && this.el.querySelector(".o_portal_doc_spinner");
                if (spinner) {
                    spinner.remove();
                }
                return Promise.resolve();
            }
        },
    });
}
