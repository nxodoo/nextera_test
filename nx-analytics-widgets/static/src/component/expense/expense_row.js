/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

const STATE_CLASS = {
    draft:     'draft',
    reported:  'reported',
    submitted: 'submitted',
    approved:  'approved',
    done:      'done',
    refused:   'refused',
};

export class ExpenseRow extends Component {
    static template = "nx_analytics_widgets.ExpenseRow";
    static props = {
        expense:  Object,
        index:    Number,
        onDelete: Function,
        onView:   Function,
        onEdit:   Function,
    };

    setup() {
        this.state = useState({ showModal: false });
    }

    get stateClass() {
        return STATE_CLASS[this.props.expense.state] || 'draft';
    }

    /** Returns BEM modifier for payment mode icon */
    get paymentIcon() {
        return this.props.expense.payment_mode === 'company_account'
            ? 'fa-building-o'
            : 'fa-user';
    }

    onViewClick() {
        this.props.onView(this.props.expense.id);
    }

    onEditClick() {
        this.props.onEdit(this.props.expense.id);
    }

    openConfirmModal() {
        this.state.showModal = true;
    }

    closeConfirmModal() {
        this.state.showModal = false;
    }

    confirmDelete() {
        this.state.showModal = false;
        this.props.onDelete(this.props.expense.id);
    }
}

