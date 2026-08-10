/** @odoo-module **/

import { Component, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { getDataURLFromFile } from "@web/core/utils/urls";

/**
 * Binary field rendered as a drag-and-drop upload zone.
 * Drop a file on it (or click to browse) to upload; shows the filename with a
 * remove button once a file is set.
 */
export class NxFileDropzone extends Component {
    static template = "nx_hr_analytics_dashboard.FileDropzone";
    static props = {
        ...standardFieldProps,
        fileNameField: { type: String, optional: true },
        acceptedFileExtensions: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ dragging: false });
        this.fileInput = useRef("fileInput");
    }

    get hasValue() {
        return !!this.props.record.data[this.props.name];
    }
    get fileName() {
        const { fileNameField, record } = this.props;
        return (fileNameField && record.data[fileNameField]) || "File";
    }

    onDragOver(ev) {
        if (this.props.readonly) {
            return;
        }
        ev.preventDefault();
        this.state.dragging = true;
    }
    onDragLeave() {
        this.state.dragging = false;
    }
    async onDrop(ev) {
        if (this.props.readonly) {
            return;
        }
        ev.preventDefault();
        this.state.dragging = false;
        const file = ev.dataTransfer && ev.dataTransfer.files[0];
        if (file) {
            await this._upload(file);
        }
    }
    openPicker() {
        if (!this.props.readonly && this.fileInput.el) {
            this.fileInput.el.click();
        }
    }
    async onInputChange(ev) {
        const file = ev.target.files[0];
        if (file) {
            await this._upload(file);
        }
        ev.target.value = "";
    }
    async clearFile(ev) {
        ev.stopPropagation();
        await this._write(false, false);
    }

    async _upload(file) {
        const dataUrl = await getDataURLFromFile(file);
        const base64 = dataUrl.split(",")[1] || false;
        await this._write(base64, file.name);
    }
    async _write(value, filename) {
        const changes = { [this.props.name]: value };
        const { fileNameField, record } = this.props;
        if (fileNameField && fileNameField in record.fields) {
            changes[fileNameField] = filename || false;
        }
        await record.update(changes);
    }
}

export const nxFileDropzone = {
    component: NxFileDropzone,
    displayName: "File Dropzone",
    supportedTypes: ["binary"],
    extractProps: ({ attrs, options }) => ({
        fileNameField: (options && options.filename_field) || attrs.filename,
        acceptedFileExtensions: options && options.accepted_file_extensions,
    }),
};

registry.category("fields").add("nx_file_dropzone", nxFileDropzone);
