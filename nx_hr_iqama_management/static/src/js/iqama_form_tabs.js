/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";
import { FormController } from "@web/views/form/form_controller";
import { useEffect } from "@odoo/owl";

const PROCESSING_STAGE_TAB_NAME = {
    iqama_details: "iqama_details_tab",
    fees: "fees_tab",
    security_review: "security_review_tab",
    completed: "request_timeline_tab",
};
const ISSUE_DATE_MIN_SENTINEL = "__issue_date__";

patch(DateTimeField.prototype, {
    parseLimitDate(value) {
        if (
            value === ISSUE_DATE_MIN_SENTINEL &&
            this.props.name === "expiry_date" &&
            (this.props.record.resModel === "hr.iqama" ||
                this.props.record.model?.config?.resModel === "hr.iqama")
        ) {
            return this.props.record.data.issue_date || undefined;
        }
        return super.parseLimitDate(...arguments);
    },
});

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

        this._lastIqamaStageSignature = null;
        useEffect(
            () => {
                this._activateIqamaStageTab();
            },
            () => [
                this.props.resModel,
                this.model.root.resId,
                this.model.root.data.state,
                this.model.root.data.processing_stage,
                this.rootRef.el,
            ]
        );
    },

    _activateIqamaStageTab() {
        if (this.props.resModel !== "hr.iqama" || !this.rootRef.el) {
            return;
        }

        const { state, processing_stage: processingStage } = this.model.root.data;
        if (state !== "under_processing") {
            this._lastIqamaStageSignature = null;
            return;
        }

        const stageSignature = `${this.model.root.resId}:${state}:${processingStage}`;
        if (!processingStage || this._lastIqamaStageSignature === stageSignature) {
            return;
        }

        this._lastIqamaStageSignature = stageSignature;
        const tabName = PROCESSING_STAGE_TAB_NAME[processingStage];
        if (!tabName) {
            return;
        }

        browser.setTimeout(() => {
            const tabLink = this.rootRef.el?.querySelector(`.nav-link[name="${tabName}"]`);
            tabLink?.click();
        });
    },
});
