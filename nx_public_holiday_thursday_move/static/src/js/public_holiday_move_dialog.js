/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";

const TRACKED_FIELDS = ["resource_id", "calendar_id", "date_from", "date_to"];

function shouldCheckPublicHolidayMove(record, changes) {
    if (record.resModel !== "resource.calendar.leaves") {
        return false;
    }
    if (record.isNew) {
        return true;
    }
    return TRACKED_FIELDS.some((fieldName) => fieldName in changes);
}

async function maybeConfirmPublicHolidayMove(controller, record, changes) {
    if (!shouldCheckPublicHolidayMove(record, changes)) {
        return true;
    }

    const moveData = await record.model.orm.call(
        "resource.calendar.leaves",
        "get_public_holiday_thursday_move_data",
        [],
        {
            values: changes,
            record_id: record.resId || false,
        }
    );

    if (!moveData.should_prompt) {
        return true;
    }

    return new Promise((resolve) => {
        controller.dialogService.add(ConfirmationDialog, {
            title: _t("Move Public Holiday"),
            body: moveData.message || _t("Do you want to move this public holiday to Thursday?"),
            confirmLabel: _t("Yes"),
            cancelLabel: _t("No"),
            confirm: () => {
                changes.date_from = moveData.target_date_from;
                changes.date_to = moveData.target_date_to;
                resolve(true);
            },
            cancel: () => resolve(true),
            dismiss: () => resolve(true),
        });
    });
}

patch(ListController.prototype, {
    async onWillSaveRecord(record, changes) {
        const canProceed = await maybeConfirmPublicHolidayMove(this, record, changes);
        if (canProceed === false) {
            return false;
        }
        return super.onWillSaveRecord(...arguments);
    },

    async onWillSaveMulti(editedRecord, changes, validSelectedRecords) {
        const canProceed = await maybeConfirmPublicHolidayMove(this, editedRecord, changes);
        if (canProceed === false) {
            return false;
        }
        return super.onWillSaveMulti(...arguments);
    },
});

patch(FormController.prototype, {
    async onWillSaveRecord(record, changes) {
        const canProceed = await maybeConfirmPublicHolidayMove(this, record, changes);
        if (canProceed === false) {
            return false;
        }
        return super.onWillSaveRecord(...arguments);
    },
});
