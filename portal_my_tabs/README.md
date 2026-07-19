# NXPortal My Tabs

> A modern, shadcn/ui-inspired sidebar navigation for the Odoo 18 customer portal — fully configurable from the backend, with live search, collapse/expand, mobile offcanvas support, and a clean minimal design.

---

## 📋 Short Description

`portal_my_tabs` replaces the default Odoo portal "My Account" card grid with a **persistent sidebar navigation** that groups portal links into configurable sections. Sidebar groups and items are managed directly from the Odoo backend, making the portal layout fully data-driven without any code changes.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Configurable Sidebar Groups** | Create, reorder, and deactivate navigation groups from the backend |
| **Configurable Sidebar Items** | Each item has a label, URL, SVG icon, sequence, and active flag |
| **SVG Icon Support** | Paste any raw SVG element per item; rendered safely via `Markup` |
| **Active Link Highlighting** | Prefix-based or exact-match URL highlighting per item |
| **Live Search** | Client-side instant search across all sidebar links (`⌘K` / `Ctrl+K` shortcut) |
| **Collapse / Expand** | Desktop sidebar collapses to icon-only mode; state persists via `localStorage` |
| **Mobile Offcanvas** | Full offcanvas drawer for mobile viewports |
| **QWeb Cache Invalidation** | Registry template cache is cleared automatically on any CRUD operation |
| **Portal Dashboard Widgets** | Summary cards and analytics widgets on the portal home page |
| **Task Analytics** | Per-task-status counters with chart support |
| **Filters & Pagination** | Client-side filtering and paginated task lists |

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, Odoo 18.0 ORM (`models.Model`) |
| Templating | QWeb (XML) — server-rendered portal pages |
| Frontend JS | Odoo Public Widget (`@web/legacy/js/public/public_widget`) |
| Styling | SCSS (`portal_tabs.scss`) |
| Icons | Raw SVG strings stored as `Text` fields |
| Safe HTML | `markupsafe.Markup` for icon injection |
| Asset Pipeline | Odoo `web.assets_frontend` bundle |

---

## 🗂 Module Structure

```
portal_my_tabs/
├── __init__.py
├── __manifest__.py
│
├── controllers/
│   ├── __init__.py
│   └── portal.py                  # Portal route overrides / extensions
│
├── models/
│   ├── __init__.py
│   ├── portal_sidebar_group.py    # portal.sidebar.group — navigation group model
│   └── portal_sidebar_item.py     # portal.sidebar.item — individual link model
│
├── views/
│   ├── portal_tabs.xml            # Entry-point template (wraps desktop + mobile)
│   ├── portal_sidebar_desktop.xml # Desktop sidebar panel
│   ├── portal_sidebar_mobile.xml  # Mobile offcanvas panel
│   ├── portal_sidebar_components.xml # Atomic sub-templates (reusable partials)
│   └── portal_sidebar_views.xml   # Backend list/form views for groups & items
│
├── security/
│   └── ir.model.access.csv        # Access control rules
│
├── data/
│   └── portal_sidebar_data.xml    # Default sidebar groups and items (demo/seed data)
│
└── static/
    ├── img/
    │   ├── logo.png
    │   └── img.png
    └── src/
        ├── js/
        │   └── sidebar_trigger.js # Public Widget: collapse, search, mobile toggle
        └── scss/
            └── portal_tabs.scss   # All sidebar and layout styles
```

---

## 🚀 Installation

### Requirements

- Odoo **18.0**
- Module dependency: `portal` (standard Odoo)

### Steps

1. **Copy the module** into your Odoo custom addons directory:

   ```bash
   cp -r portal_my_tabs /path/to/odoo/custom_addons/
   ```

2. **Add the addons path** to your `odoo.conf`:

   ```ini
   addons_path = /path/to/odoo/addons,/path/to/odoo/custom_addons
   ```

3. **Update the app list** in Odoo:

   - Navigate to **Settings → Activate Developer Mode**
   - Go to **Apps → Update Apps List**

4. **Install the module**:

   - Search for `NXPortal My Tabs` in the Apps list
   - Click **Install**

5. **Apply database migrations** (safe — runs only new migrations):

   ```bash
   python odoo-bin -c odoo.conf -u portal_my_tabs
   ```

---

## 📖 Usage Guide

### Managing Sidebar Groups

1. Go to **Settings → Portal Sidebar → Groups** (or use the developer menu).
2. Create a new group with a **Name** and **Sequence**.
3. Add **Items** to the group, each with:
   - **Label** — display text
   - **URL** — target portal path (e.g. `/my/tasks`)
   - **SVG Icon** — paste a raw `<svg>…</svg>` string
   - **URL Match Prefix** — controls active-link highlighting
   - **Exact Match** — enable for root paths like `/my`

### Sidebar Behaviour (Frontend)

| Action | Behaviour |
|---|---|
| Click toggle button | Collapses sidebar to icon-only mode (state saved in `localStorage`) |
| Type in search box | Instantly filters visible links by label |
| `Ctrl+K` / `⌘K` | Focuses the search input |
| Resize to mobile | Sidebar switches to offcanvas drawer mode |

### Portal Dashboard Widgets

The portal home page renders summary cards for the authenticated user's tasks:

| Card | Description |
|---|---|
| **Total Tasks** | All tasks assigned to the user |
| **In Progress** | Tasks in an active stage |
| **Done** | Tasks marked as closed/done |
| **Cancelled** | Tasks with a cancelled state |
| **Delayed Tasks** | Tasks past their deadline and not done |
| **Tasks Today** | Tasks with today's deadline |
| **Upcoming Tasks** | Tasks due in the future |
| **Tasks Without Deadline** | Tasks with no deadline set |

---



## 🧑‍💻 Development Notes

### Adding a New Sidebar Item Programmatically

```python
# In a migration or data fixture
env['portal.sidebar.group'].create({
    'name': 'My Services',
    'sequence': 20,
    'item_ids': [(0, 0, {
        'name': 'My Invoices',
        'url': '/my/invoices',
        'sequence': 10,
        'icon': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                '</svg>',
    })],
})
```

### Icon Rendering (Safe HTML)

Icons are stored as raw SVG text and rendered using `markupsafe.Markup` to prevent double-escaping in QWeb:

```python
from markupsafe import Markup

def _get_icon_markup(self):
    self.ensure_one()
    return Markup(self.icon) if self.icon else Markup('')
```

In QWeb templates, call the method directly:

```xml
<t t-out="item._get_icon_markup()"/>
```

### QWeb Cache Invalidation

Every `create`, `write`, or `unlink` on `portal.sidebar.group` clears the template registry cache so the portal pages reflect changes immediately:

```python
def _clear_sidebar_cache(self):
    self.env.registry.clear_cache('default', 'templates')
```

### Registering a New Frontend Widget

```javascript
/** @odoo-module **/
import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.MyWidget = publicWidget.Widget.extend({
    selector: '.my-portal-section',
    events: {
        'click .my-button': '_onClick',
    },
    _onClick(ev) {
        // handle click
    },
});
```

### SCSS / Styling

All styles live in `static/src/scss/portal_tabs.scss`. The file is loaded via the `web.assets_frontend` bundle — no manual `<link>` tags required.

---

## ⚡ Performance Notes

- **Server-side rendering**: The sidebar is rendered by QWeb on the server, keeping the initial page load fast and SEO-friendly.
- **LocalStorage persistence**: Sidebar collapse state is stored client-side, avoiding extra server round-trips.
- **Client-side search**: Link filtering runs entirely in the browser — no AJAX calls on each keystroke.
- **Cache invalidation**: Template cache is cleared only on backend CRUD events, not on every page load.
- **Asset bundling**: JS and SCSS are compiled into the Odoo frontend bundle — no separate HTTP requests per file.

---

## 📄 License

This module is licensed under the **GNU Lesser General Public License v3.0 (LGPL-3)**.

See the [LICENSE](https://www.gnu.org/licenses/lgpl-3.0.html) file or the official GNU website for details.

---

> **Author:** Hisham Megahed  
> **Version:** 1.0.0  
> **Odoo Version:** 18.0  
> **Category:** Website / Portal
