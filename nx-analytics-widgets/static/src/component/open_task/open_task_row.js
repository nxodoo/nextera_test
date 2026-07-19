/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

// Map stage name keywords → CSS modifier
const STAGE_COLOR_MAP = [
    { keys: ['new',   'backlog', 'inbox', 'todo', 'to do'],          cls: 'new'      },
    { keys: ['progress', 'doing', 'ongoing', 'active', 'open'],      cls: 'progress' },
    { keys: ['review', 'testing', 'qa', 'check', 'approval'],        cls: 'review'   },
    { keys: ['done', 'complete', 'finished', 'closed', 'delivered'],  cls: 'done'     },
    { keys: ['block', 'hold', 'wait', 'pending', 'cancel'],          cls: 'blocked'  },
];

export class OpenTaskRow extends Component {
    static template = "nx_analytics_widgets.OpenTaskRow";
    static props = {
        task: Object,
        index: Number,
        onArchive: Function,
    };

    setup() {
        this.state = useState({ showModal: false });
    }

    /** Returns a CSS modifier class like "nx-stage--progress" based on stage name */
    get stageCls() {
        const name = (this.props.task.stage || '').toLowerCase();
        for (const { keys, cls } of STAGE_COLOR_MAP) {
            if (keys.some(k => name.includes(k))) return `nx-stage--${cls}`;
        }
        return 'nx-stage--default';
    }

    /**
     * Returns { cls, icon, label } for the deadline cell.
     *  - overdue   → red   / fa-exclamation-circle   (past due)
     *  - due-soon  → amber / fa-clock-o              (within 3 days)
     *  - ok        → green / fa-calendar-check-o     (more than 3 days away)
     *  - none      → gray  / fa-calendar-times-o     (no deadline set)
     */
    get deadlineInfo() {
        const raw = this.props.task.deadline;
        if (!raw) return { cls: 'nx-date--none', icon: 'fa-calendar-times-o', label: '—' };

        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const due = new Date(raw);
        due.setHours(0, 0, 0, 0);
        const diffDays = Math.ceil((due - today) / 86400000);

        if (diffDays < 0)  return { cls: 'nx-date--overdue',  icon: 'fa-exclamation-circle', label: raw };
        if (diffDays <= 3) return { cls: 'nx-date--due-soon', icon: 'fa-clock-o',            label: raw };
        return               { cls: 'nx-date--ok',       icon: 'fa-calendar-check-o',   label: raw };
    }

    openConfirmModal() {
        this.state.showModal = true;
    }

    closeConfirmModal() {
        this.state.showModal = false;
    }

    confirmArchive() {
        this.state.showModal = false;
        this.props.onArchive(this.props.task.id);
    }
}
