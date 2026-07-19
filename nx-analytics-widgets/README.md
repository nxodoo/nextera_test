# NXPortal Analytics Widgets

> A powerful Odoo 18 portal enhancement that replaces the default "My Account" layout with a unified, analytics-first experience — featuring OWL-powered dashboards, real-time task/leave/expense data, interactive charts, and a fully configurable sidebar — all rendered client-side via the Odoo ORM service.

---

## 📋 Short Description

`nx-analytics-widgets` is an Odoo 18 portal module that integrates with the **NXPortal ecosystem** (`nx_portal_tasks`, `nx_portal_expense`, `nx_efe_portal_hr_leave`, `portal_my_tabs`) to deliver a cohesive, analytics-driven portal experience.

Each portal section — Tasks, Leaves, and Expenses — is powered by a dedicated **OWL component** that fetches live data from the Odoo ORM service. The result is a fast, reactive, mobile-friendly portal with summary cards, charts, filters, pagination, and smooth animations.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Task Dashboard** | Summary pipeline cards, per-project breakdown, deadline analytics |
| **Task Chart (Line)** | Chart.js line chart for hours logged over time, loaded on demand |
| **Project Section** | Per-project OWL card with completion percentage, task counts, and accent colours |
| **Open Tasks Table** | OWL table with filters (overdue / due soon / no deadline), search, sort, pagination |
| **Leave Table** | OWL leave table with state filters (draft / pending / approved / refused), pagination |
| **Leave Balance Cards** | Per-leave-type allocation, taken, and remaining days/hours with progress bar |
| **Expense Table** | OWL expense table with state filters, amount sort, delete action, pagination |
| **Interactive Stat Cards** | Staggered entrance animations + hover tooltips via Public Widget |
| **Client-Side ORM Calls** | All data fetched with `useService("orm")` — no server-rendered data arrays |
| **Filters & Search** | Live search + quick-filter chips on every table widget |
| **Pagination** | Configurable page size, previous/next controls on every table widget |
| **Controller Overrides** | Thin Python controllers override parent routes, delegating data to OWL |

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, Odoo 18.0 (`odoo.http`, `odoo.fields`) |
| OWL Components | Odoo OWL 3 (`@odoo/owl`) — `Component`, `useState`, `onWillStart`, `useRef`, `onMounted` |
| ORM Service | `useService("orm")` — `searchRead`, `readGroup`, `unlink` |
| Charts | [Chart.js 4.4](https://www.chartjs.org/) — loaded on demand via `loadJS` |
| Public Widget | `@web/legacy/js/public/public_widget` — stat card animations |
| Templating | QWeb (XML) — OWL templates + server-side portal overrides |
| Styling | SCSS per component + global `leave.scss` |
| Asset Pipeline | Odoo `web.assets_frontend` bundle (glob pattern per component folder) |

---

## 🗂 Module Structure

```
nx-analytics-widgets/
├── __init__.py
├── __manifest__.py
│
├── controllers/
│   ├── __init__.py
│   ├── portal_open_task_inherit.py    # Overrides task list route → OWL template
│   ├── portal_hr_leaves_inherit.py    # Overrides leave route → leave balances + OWL
│   ├── portal_expense_inherit.py      # Overrides expense route → OWL template
│   └── helpers/
│       ├── __init__.py
│       └── leave_stats.py             # build_leave_maps(), get_leave_state_counts()
│
├── models/                            # (reserved for future ORM models)
│
├── views/
│   ├── portal_breadcrumbs.xml         # Shared breadcrumb template overrides
│   ├── portal_open_task.xml           # OWL mount point for task dashboard + table
│   ├── portal_leave_templates.xml     # OWL mount point for leave table + balances
│   └── portal_expense_templates.xml   # OWL mount point for expense table
│
└── static/
    ├── img/
    │   ├── analytics_sphere.svg
    │   └── card-website-analytics-1.png
    └── src/
        ├── js/
        │   └── nx_stat_cards_interactive.js   # Public Widget: animations + tooltips
        ├── scss/
        │   └── leave.scss                     # Global leave page styles
        └── component/
            ├── task/
            │   ├── task_service.js             # fetchTaskDashboard(), getDeadlinesTasks()
            │   ├── task_dashboard.js           # OWL root: TaskDashboardApp
            │   ├── task_dashboard.xml          # OWL template: pipeline cards + deadlines
            │   ├── task_dashboard.scss
            │   ├── task_projects_section.js    # OWL: per-project cards
            │   ├── task_projects_section.xml
            │   ├── task_chart.js               # OWL: Chart.js line chart (hours logged)
            │   ├── task_chart.xml
            │   ├── task_project_chart.js       # OWL: per-project bar/doughnut chart
            │   ├── task_project_chart.xml
            │   └── nx-pd-stats_customization_examples.scss
            ├── open_task/
            │   ├── open_task_service.js        # fetchOpenTasks(), domain builder
            │   ├── open_task_table_app.js      # OWL root: OpenTaskTableApp
            │   ├── open_task_table_app.xml
            │   ├── open_task_table.js          # OWL: table layout
            │   ├── open_task_row.js            # OWL: single row
            │   ├── open_task_filters.js        # OWL: filter chips + search
            │   ├── open_task_pagination.js     # OWL: pagination controls
            │   └── open_task_table_owl.scss
            ├── leave/
            │   ├── leave_service.js            # fetchLeaves(), fetchEmployeeId()
            │   ├── leave_table_app.js          # OWL root: LeaveTableApp
            │   ├── leave_table_app.xml
            │   ├── leave_table.js
            │   ├── leave_row.js
            │   ├── leave_filters.js
            │   ├── leave_pagination.js
            │   └── leave_table_owl.scss
            └── expense/
                ├── expense_service.js          # fetchExpenses(), delete action
                ├── expense_table_app.js        # OWL root: ExpenseTableApp
                ├── expense_table_app.xml
                ├── expense_table.js
                ├── expense_row.js
                ├── expense_filters.js
                ├── expense_pagination.js
                └── expense_table_owl.scss
```

---

## 🚀 Installation

### Requirements

- Odoo **18.0**
- The following custom modules must be installed **first**:

  | Module | Purpose |
  |---|---|
  | `portal` | Odoo standard portal |
  | `portal_my_tabs` | Sidebar navigation layout |
  | `nx_portal_tasks` | Task portal routes + base templates |
  | `nx_portal_expense` | Expense portal routes + base templates |
  | `nx_efe_portal_hr_leave` | HR Leave portal routes + base templates |

### Steps

1. **Copy the module** into your custom addons directory:

   ```bash
   cp -r nx-analytics-widgets /path/to/odoo/custom_addons/
   ```

2. **Verify `odoo.conf`** includes your addons path:

   ```ini
   addons_path = /path/to/odoo/addons,/path/to/odoo/custom_addons
   ```

3. **Update the app list** in Odoo:
   - Enable **Developer Mode** → **Apps → Update Apps List**

4. **Install the module**:
   - Search for `NXPortal Analytics Widgets` → click **Install**

5. **Upgrade safely** (no data loss):

   ```bash
   python odoo-bin -c odoo.conf -u nx-analytics-widgets
   ```

---

## 📖 Usage Guide

### Task Dashboard

Accessible at `/my/tasks` — rendered by the `TaskDashboardApp` OWL component.

**Pipeline Cards**

| Card | Source |
|---|---|
| **Total Tasks** | All tasks assigned to the user |
| **New** | Tasks in a "new" stage |
| **In Progress** | Tasks in a "progress" stage |
| **Done** | Tasks in a "done" stage |
| **Cancelled** | Tasks in a "cancel" stage |

**Deadline Cards**

| Card | Logic |
|---|---|
| **Delayed** | Open tasks with `date_deadline < today` |
| **Tasks Today** | Open tasks with `date_deadline == today` |
| **Upcoming** | Open tasks with `date_deadline > today` |
| **No Deadline** | Open tasks where `date_deadline` is not set |

**Project Section**

Each project renders a card showing: task count, completed tasks, cancelled tasks, in-progress tasks, total hours, and a completion percentage bar. Cards are colour-coded using an accent cycle (`primary → success → info → warning → danger → purple`).

**Line Chart**

A Chart.js line chart displays **hours logged per date** across all tasks. Chart.js is loaded on demand — it is not bundled.

---

### Open Tasks Table

An OWL table widget at `/my/tasks` listing the user's active (non-closed) tasks with:

- **Quick filters**: All / Overdue / Due Soon (next 7 days) / No Deadline
- **Live search**: by task name or project name
- **Sortable columns**: Deadline, Assigned Date, Stage
- **Pagination**: configurable page size

---

### Leave Table & Balances

Accessible at `/my/leaves`:

- **Leave balances**: per leave type — allocated days/hours, taken days/hours, remaining days/hours, percentage-used progress bar
- **Leave table**: filterable by state (Draft / Pending / Partial Approval / Approved / Refused)
- **Search**: by leave type name or description
- **Pagination** with previous/next controls

---

### Expense Table

Accessible at `/my/expenses`:

- **Filterable** by state: To Report / To Submit / Submitted / Approved / Done / Refused
- **Sortable** by date, amount, or state
- **Search** by expense name or product name
- **Delete action** for draft/reported expenses
- **Pagination** with configurable page size

---

### Stat Card Animations

Any element with the class `nx-analytics-widget--enhanced` will have its `.nx-aw-chip` children animated on load (staggered fade-in + slide-up) and will receive hover tooltips describing each stat type.

---

## 🖼 Screenshots

> Place screenshots in `static/img/` and update the paths below.

### Task Dashboard

![Task Dashboard](static/img/card-website-analytics-1.png)

### Analytics Sphere

![Analytics](static/img/analytics_sphere.svg)

---

## 🧑‍💻 Development Notes

### Adding a New OWL Table Widget

Follow the established pattern: one `*_service.js` for ORM calls, one `*_table_app.js` as the root, and atomic sub-components for rows, filters, and pagination.

```javascript
/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { registry } from "@web/core/registry";
import { fetchMyData } from "./my_service";

export class MyTableApp extends Component {
    static template = "nx_analytics_widgets.MyTableApp";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({ loading: true, rows: [], total: 0 });

        onWillStart(async () => {
            const result = await fetchMyData(this.orm, user.userId, { page: 1, pageSize: 10 });
            Object.assign(this.state, result, { loading: false });
        });
    }
}

registry.category("public_components").add("nx.MyTableApp", MyTableApp);
```

Mount the component in a QWeb template:

```xml
<t t-name="nx_analytics_widgets.my_page_override" inherit_id="..." id="...">
    <owl-component name="nx.MyTableApp" />
</t>
```

### Extending the Leave Balance Helper

`controllers/helpers/leave_stats.py` exposes two pure functions:

```python
from .helpers.leave_stats import build_leave_maps, get_leave_state_counts

# Returns (allocation_map, taken_map) keyed by leave_type_id
alloc_map, taken_map = build_leave_maps(request.env, employee_id)

# Returns (pending_count, approved_count)
pending, approved = get_leave_state_counts(Leave, employee_id)
```

### Chart.js — On-Demand Loading

Chart.js is **not** bundled in the Odoo asset pipeline. It is loaded lazily inside the OWL component:

```javascript
import { loadJS } from "@web/core/assets";

async renderChart() {
    await loadJS(
        "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"
    );
    // Chart instance is available via this.chartRef.el
}
```

### Asset Registration (Glob Pattern)

All component JS/XML/SCSS files are registered with a single glob per type in `__manifest__.py`:

```python
'assets': {
    'web.assets_frontend': [
        'nx-analytics-widgets/static/src/component/*/*.js',
        'nx-analytics-widgets/static/src/component/*/*.xml',
        'nx-analytics-widgets/static/src/component/*/*.scss',
        'nx-analytics-widgets/static/src/js/nx_stat_cards_interactive.js',
        'nx-analytics-widgets/static/src/scss/leave.scss',
    ]
},
```

New component folders are picked up automatically — no manifest changes needed.

---

## ⚡ Performance Notes

- **Client-side ORM**: All table data is fetched by OWL components after page load, keeping initial server response fast and free of large data arrays.
- **`readGroup` for aggregation**: Task pipeline counters use a single `readGroup` call grouped by stage and project — one DB query replaces N individual counts.
- **Lazy Chart.js**: The chart library (~200 KB) is only downloaded when a chart component actually mounts.
- **OWL reactive state**: `useState` ensures only the affected DOM subtree re-renders on filter/page/search changes — no full-page reloads.
- **Controller delegation**: Python controllers are thin — they render a shell template and pass no data arrays; all data logic lives in the OWL service layer.

---

## 📦 Dependencies

| Module | Type | Purpose |
|---|---|---|
| `portal` | Odoo standard | Base portal routes and layout |
| `portal_my_tabs` | Custom | Sidebar navigation wrapper |
| `nx_portal_tasks` | Custom | Task portal controller base class |
| `nx_portal_expense` | Custom | Expense portal controller base class |
| `nx_efe_portal_hr_leave` | Custom | HR Leave portal controller base class |
| `Chart.js 4.4` | CDN | Line/bar charts in task dashboard |

---

## 📄 License

This module is licensed under the **GNU Lesser General Public License v3.0 (LGPL-3)**.

See the [LICENSE](https://www.gnu.org/licenses/lgpl-3.0.html) file or the official GNU website for details.

---

> **Author:** Hisham Megahed  
> **Company:** Nextera MEA  
> **Version:** 1.0.0  
> **Odoo Version:** 18.0  
> **Category:** Website / Portal

