/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import {
    fetchExpenseFormData,
    fetchExpenseDetail,
    createExpense,
    updateExpense,
} from "./expense_service";

/**
 * ExpenseFormPopup – modal dialog for New / Edit / View expense.
 *
 * Props:
 *   mode            : 'create' | 'edit' | 'view'
 *   expenseId       : Number | null   (required for edit/view)
 *   employeeId      : Number
 *   onClose         : Function
 *   onSaved         : Function
 *   onSwitchToEdit  : Function (optional)
 */
export class ExpenseFormPopup extends Component {
    static template = "nx_analytics_widgets.ExpenseFormPopup";
    static props = {
        mode:           String,
        expenseId:      { type: Number, optional: true },
        employeeId:     Number,
        onClose:        Function,
        onSaved:        Function,
        onSwitchToEdit: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            saving: false,
            // form fields
            name: '',
            date: new Date().toISOString().split('T')[0],
            product_id: false,
            amount: 0,
            currency_id: false,
            payment_mode: 'own_account',
            tax_ids: [],
            account_id: false,
            vendor_id: false,
            // lookup data
            categories: [],
            currencies: [],
            taxes: [],
            accounts: [],
            vendors: [],
            // view-only extras
            state: '',
            state_label: '',
            product_name: '',
            currency_name: '',
            account_name: '',
            vendor_name: '',
            tax_names: [],
            // validation
            errors: {},
            // tax dropdown
            taxDropdownOpen: false,
            taxSearch: '',
        });

        onWillStart(() => this._init());
    }

    async _init() {
        this.state.loading = true;
        try {
            const formData = await fetchExpenseFormData(this.orm);
            this.state.categories = formData.categories;
            this.state.currencies = formData.currencies;
            this.state.taxes = formData.taxes;
            this.state.accounts = formData.accounts;
            this.state.vendors = formData.vendors;

            // Set default currency
            if (!this.state.currency_id && formData.currencies.length) {
                this.state.currency_id = formData.currencies[0].id;
            }

            // If editing or viewing, load existing record
            if ((this.props.mode === 'edit' || this.props.mode === 'view') && this.props.expenseId) {
                const detail = await fetchExpenseDetail(this.orm, this.props.expenseId, this.props.employeeId);
                if (detail) {
                    // Resolve tax names for view mode
                    const taxMap = {};
                    for (const t of formData.taxes) taxMap[t.id] = t.name;
                    const taxNames = (detail.tax_ids || []).map(id => taxMap[id] || `Tax #${id}`);

                    Object.assign(this.state, {
                        name:          detail.name,
                        date:          detail.date,
                        product_id:    detail.product_id,
                        amount:        detail.amount,
                        currency_id:   detail.currency_id,
                        payment_mode:  detail.payment_mode,
                        tax_ids:       detail.tax_ids || [],
                        account_id:    detail.account_id,
                        vendor_id:     detail.vendor_id,
                        state:         detail.state,
                        state_label:   detail.state_label,
                        product_name:  detail.product_name,
                        currency_name: detail.currency_name,
                        account_name:  detail.account_name,
                        vendor_name:   detail.vendor_name,
                        tax_names:     taxNames,
                    });
                }
            }
        } catch (e) {
            this.notification.add(e.message || 'Failed to load form data.', { type: 'danger' });
        } finally {
            this.state.loading = false;
        }
    }

    get isReadonly() {
        return this.props.mode === 'view';
    }

    get showVendor() {
        return this.state.payment_mode === 'company_account';
    }

    get title() {
        switch (this.props.mode) {
            case 'create': return 'New Expense';
            case 'edit':   return 'Edit Expense';
            case 'view':   return 'Expense Details';
            default:       return 'Expense';
        }
    }

    get titleIcon() {
        switch (this.props.mode) {
            case 'create': return 'fa-plus-circle';
            case 'edit':   return 'fa-pencil';
            case 'view':   return 'fa-eye';
            default:       return 'fa-money';
        }
    }

    get paymentModeLabel() {
        return this.state.payment_mode === 'company_account' ? 'Company' : 'Employee (to reimburse)';
    }

    // ── Field handlers ───────────────────────────────────────────────────
    onFieldChange(field, ev) {
        const val = ev.target.value;
        if (['product_id', 'currency_id', 'account_id', 'vendor_id'].includes(field)) {
            this.state[field] = val ? parseInt(val, 10) : false;
        } else if (field === 'amount') {
            this.state[field] = parseFloat(val) || 0;
        } else if (field === 'payment_mode') {
            this.state[field] = val;
            // Clear vendor when switching to own_account
            if (val !== 'company_account') {
                this.state.vendor_id = false;
            }
        } else {
            this.state[field] = val;
        }
        // Clear error
        if (this.state.errors[field]) {
            delete this.state.errors[field];
            this.state.errors = { ...this.state.errors };
        }
    }

    // ── Select2-style multi-tag for taxes ────────────────────────────────
    get taxDropdownOpen() {
        return this.state.taxDropdownOpen || false;
    }

    get filteredTaxes() {
        const q = (this.state.taxSearch || '').toLowerCase().trim();
        if (!q) return this.state.taxes;
        return this.state.taxes.filter(t => t.name.toLowerCase().includes(q));
    }

    get selectedTaxItems() {
        const taxMap = {};
        for (const t of this.state.taxes) taxMap[t.id] = t.name;
        return this.state.tax_ids.map(id => ({ id, name: taxMap[id] || `Tax #${id}` }));
    }

    isTaxSelected(taxId) {
        return this.state.tax_ids.includes(taxId);
    }

    onTaxBoxClick() {
        this.state.taxDropdownOpen = true;
    }

    onTaxSearchInput(ev) {
        this.state.taxSearch = ev.target.value;
        if (!this.state.taxDropdownOpen) {
            this.state.taxDropdownOpen = true;
        }
    }

    onTaxSearchFocus() {
        this.state.taxDropdownOpen = true;
    }

    toggleTax(taxId) {
        const idx = this.state.tax_ids.indexOf(taxId);
        if (idx >= 0) {
            this.state.tax_ids = this.state.tax_ids.filter(id => id !== taxId);
        } else {
            this.state.tax_ids = [...this.state.tax_ids, taxId];
        }
    }

    removeTax(taxId) {
        this.state.tax_ids = this.state.tax_ids.filter(id => id !== taxId);
    }

    closeTaxDropdown() {
        this.state.taxDropdownOpen = false;
        this.state.taxSearch = '';
    }

    // ── Validation ───────────────────────────────────────────────────────
    _validate() {
        const errs = {};
        if (!this.state.name || !this.state.name.trim()) {
            errs.name = 'Description is required.';
        }
        if (!this.state.date) {
            errs.date = 'Expense Date is required.';
        }
        if (!this.state.product_id) {
            errs.product_id = 'Category is required.';
        }
        if (!this.state.amount || this.state.amount <= 0) {
            errs.amount = 'Total must be greater than 0.';
        }
        if (!this.state.currency_id) {
            errs.currency_id = 'Currency is required.';
        }
        this.state.errors = errs;
        return Object.keys(errs).length === 0;
    }

    // ── Save ─────────────────────────────────────────────────────────────
    async onSave() {
        if (!this._validate()) return;

        this.state.saving = true;
        const vals = {
            name:         this.state.name.trim(),
            date:         this.state.date,
            product_id:   this.state.product_id,
            amount:       this.state.amount,
            currency_id:  this.state.currency_id,
            payment_mode: this.state.payment_mode,
            tax_ids:      this.state.tax_ids,
            account_id:   this.state.account_id,
            vendor_id:    this.state.vendor_id,
        };

        let res;
        if (this.props.mode === 'create') {
            res = await createExpense(this.orm, this.props.employeeId, vals);
        } else {
            res = await updateExpense(this.orm, this.props.expenseId, this.props.employeeId, vals);
        }

        this.state.saving = false;

        if (res && res.ok) {
            this.notification.add(
                this.props.mode === 'create' ? 'Expense created successfully!' : 'Expense updated successfully!',
                { type: 'success' },
            );
            this.props.onSaved();
        } else {
            this.notification.add((res && res.error) || 'Failed to save expense.', { type: 'danger' });
        }
    }

    onClose() {
        this.props.onClose();
    }

    onBackdropClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.props.onClose();
        }
    }

    onSwitchToEdit() {
        if (this.props.onSwitchToEdit) {
            this.props.onSwitchToEdit(this.props.expenseId);
        }
    }
}




