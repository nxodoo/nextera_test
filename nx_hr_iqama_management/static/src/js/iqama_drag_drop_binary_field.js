/** @odoo-module **/

import { registry } from "@web/core/registry";
import { checkFileSize } from "@web/core/utils/files";
import { getDataURLFromFile } from "@web/core/utils/urls";
import {
    ListBinaryField,
    listBinaryField,
} from "@web/views/fields/binary/binary_field";

import { useState } from "@odoo/owl";

export class IqamaDragDropBinaryField extends ListBinaryField {
    static template = "nx_hr_iqama_management.DragDropBinaryField";

    setup() {
        super.setup();
        this.dragState = useState({
            counter: 0,
            isDragging: false,
        });
    }

    get hasFile() {
        return Boolean(this.props.record.data[this.props.name]);
    }

    get dropzoneClassName() {
        return this.dragState.isDragging
            ? "o_iqama_drag_drop_binary_field o_iqama_drag_drop_binary_field--dragging"
            : "o_iqama_drag_drop_binary_field";
    }

    onDragEnter(ev) {
        if (this.props.readonly) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.dragState.counter += 1;
        this.dragState.isDragging = true;
    }

    onDragOver(ev) {
        if (this.props.readonly) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        ev.dataTransfer.dropEffect = "copy";
    }

    onDragLeave(ev) {
        if (this.props.readonly) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.dragState.counter = Math.max(0, this.dragState.counter - 1);
        if (!this.dragState.counter) {
            this.dragState.isDragging = false;
        }
    }

    async onDrop(ev) {
        if (this.props.readonly) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.dragState.counter = 0;
        this.dragState.isDragging = false;

        const [file] = Array.from(ev.dataTransfer?.files || []);
        if (!file || !checkFileSize(file.size, this.notification)) {
            return;
        }

        const dataUrl = await getDataURLFromFile(file);
        await this.update({
            name: file.name,
            data: dataUrl.split(",")[1],
        });
    }
}

export const iqamaDragDropBinaryField = {
    ...listBinaryField,
    component: IqamaDragDropBinaryField,
};

registry.category("fields").add("iqama_drag_drop_binary", iqamaDragDropBinaryField);
registry.category("fields").add("list.iqama_drag_drop_binary", iqamaDragDropBinaryField);
