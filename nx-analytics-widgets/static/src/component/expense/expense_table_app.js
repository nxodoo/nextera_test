/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

import { ExpenseFilters } from "./expense_filters";
import { ExpenseTable } from "./expense_table";
import { ExpensePagination } from "./expense_pagination";
import { ExpenseFormPopup } from "./expense_form_popup";
import { fetchExpenses, deleteExpense, fetchEmployeeId } from "./expense_service";

export class ExpenseTableApp extends Component {
    static template = "nx_analytics_widgets.ExpenseTableApp";
    static components = { ExpenseFilters, ExpenseTable, ExpensePagination, ExpenseFormPopup };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            page: 1,
            pageSize: 10,
            stateFilter: '',
            search: '',
            sortKey: 'date',
            sortOrder: 'desc',
            expenses: [],
            total: 0,
            pages: 1,
            loading: true,
            error: null,
            // popup state
            popupMode: null,       // null | 'create' | 'edit' | 'view'
            popupExpenseId: null,   // expense id for edit/view
        });

        this._employeeId = null;

        onWillStart(async () => {
            this._employeeId = await fetchEmployeeId(this.orm, user.userId);
            await this._load();
        });
    }

    get employeeId() {
        return this._employeeId;
    }

    get showPopup() {
        return !!this.state.popupMode;
    }

    async _load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await fetchExpenses(this.orm, {
                employeeId: this._employeeId,
                userId: user.userId,
                page: this.state.page,
                pageSize: this.state.pageSize,
                stateFilter: this.state.stateFilter,
                search: this.state.search,
                sortKey: this.state.sortKey,
                sortOrder: this.state.sortOrder,
            });
            Object.assign(this.state, {
                expenses: result.expenses,
                total: result.total,
                page: result.page,
                pages: result.pages,
            });
        } catch (e) {
            this.state.error = e.message || 'Failed to load expenses.';
        } finally {
            this.state.loading = false;
        }
    }

    async onFilter(key) {
        this.state.stateFilter = key;
        this.state.page = 1;
        await this._load();
    }

    async onPageChange(n) {
        this.state.page = n;
        await this._load();
    }

    async onApplySearch(val) {
        this.state.search = val;
        this.state.page = 1;
        await this._load();
    }

    async onSortKey(key) {
        this.state.sortKey = key;
        this.state.page = 1;
        await this._load();
    }

    async onSortOrder() {
        this.state.sortOrder = this.state.sortOrder === 'desc' ? 'asc' : 'desc';
        this.state.page = 1;
        await this._load();
    }

    async onDelete(expenseId) {
        const res = await deleteExpense(this.orm, expenseId, this._employeeId);
        if (res && res.ok) {
            await this._load();
            this.notification.add("Expense deleted successfully", {
                type: "success",
            });
        } else {
            this.notification.add((res && res.error) || 'Could not delete the expense.', {
                type: "danger",
            });
        }
    }

    // ── Popup actions ────────────────────────────────────────────────────
    onNewExpense() {
        this.state.popupMode = 'create';
        this.state.popupExpenseId = null;
    }

    onViewExpense(expenseId) {
        this.state.popupMode = 'view';
        this.state.popupExpenseId = expenseId;
    }

    onEditExpense(expenseId) {
        this.state.popupMode = 'edit';
        this.state.popupExpenseId = expenseId;
    }

    onClosePopup() {
        this.state.popupMode = null;
        this.state.popupExpenseId = null;
    }

    async onPopupSaved() {
        this.state.popupMode = null;
        this.state.popupExpenseId = null;
        await this._load();
    }

    onSwitchToEdit(expenseId) {
        this.state.popupMode = 'edit';
        this.state.popupExpenseId = expenseId;
    }
}

registry.category("public_components").add("nx.ExpenseTableApp", ExpenseTableApp);

