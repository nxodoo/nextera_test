/** @odoo-module **/
import { Component } from "@odoo/owl";

export class ExpensePagination extends Component {
    static template = "nx_analytics_widgets.ExpensePagination";
    static props = {
        page:         Number,
        pages:        Number,
        total:        Number,
        pageSize:     Number,
        onPageChange: Function,
    };

    get hasPrev() { return this.props.page > 1; }
    get hasNext() { return this.props.page < this.props.pages; }

    get pageNumbers() {
        const { page, pages } = this.props;
        if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
        const set = new Set([1, pages, page - 1, page, page + 1]
            .filter(n => n >= 1 && n <= pages));
        const sorted = [...set].sort((a, b) => a - b);
        const result = [];
        let prev = 0;
        for (const n of sorted) {
            if (n - prev > 1) result.push(-1);
            result.push(n);
            prev = n;
        }
        return result;
    }

    go(n) {
        if (n >= 1 && n <= this.props.pages && n !== this.props.page) {
            this.props.onPageChange(n);
        }
    }
}
