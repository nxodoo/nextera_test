# nx_audit_log - Architecture, decisions and limitations

Target: Odoo 18.0 (verified against the 18.0 source; 39 automated tests on a real database).

## 1. Capture pipeline

```
ORM hooks (models/base.py)            Request boundary (controllers/main.py)
  create / write / _write_multi /       call_kw, call_button, /jsonrpc, /xmlrpc,
  unlink / copy / export_data / load    logout, ir.http._handle_error
            |                                        |
            v                                        v
  services/observer.py  --->  Accumulator (one per DB cursor)  <--- access / action entries
     BEFORE state read in SQL            |  journal (savepoint-aware)
     (first observation only)            v
                         patched Cursor.commit()  -> services/finalizer.py
                                 fold -> AFTER state (SQL) -> diff -> rule -> serialize
                                 -> audit.log / audit.log.line (same transaction)
                                 -> alerts outbox (same transaction)
```

### Key decisions

| Topic | Decision | Why |
|---|---|---|
| Finalize point | Patched `Cursor.commit()` / `TestCursor.commit()`, **not** `cr.precommit` | Odoo 18 runs precommit hooks on every flushing savepoint (`cr.flush()`), which would split one logical transaction into many events. |
| BEFORE values | Raw SQL on first observation (`write`, `_write_multi`, `unlink`), never ORM reads | Stored computed fields are persisted by `_flush -> _write_multi`; by then the cache already holds the new value, the DB still holds the old one. No flush, no compute side effects. |
| AFTER values | Raw SQL after the final flush | Evidence = what is actually persisted. A write back to the original value or a rolled-back savepoint yields no event. |
| Savepoints | `Savepoint.__init__` stores the journal length, `rollback()` truncates it | Work undone by a savepoint (incl. `execute_import(dryrun=True)`) never becomes evidence. |
| Retries | Patched `rollback()` drops the accumulator | `retrying()` on SerializationFailure cannot leave duplicate evidence. |
| Direct vs derived | Field in caller's vals = direct; changed but not written by caller = derived; set by PostgreSQL FK = database_fk | Rule `derived_policy`: direct / selected / all. |
| Many2many | Captured in `write()` before super (relation rows are written immediately, not at flush) | Also captures the inverse side (`res.groups.users` changes appear on `res.users.groups_id`). |
| FK effects | Before `unlink`, inverse many2one (`cascade`, `set null`) and many2many owners are captured | PostgreSQL performs these without calling Python. Nested cascades to depth 3, 20 000 records per relation. |
| Implicit child audit | Rule on a model also audits its *owned* one2many lines (inverse many2one with `ondelete='cascade'`) | `sale.order` rule audits `sale.order.line`; a rule on `res.company` does not audit every partner. |
| Read-only cursors | Read/export/report events from read-only transactions are written after commit in a separate cursor | Writing in a read-only cursor would make Odoo replay the whole request in read/write mode. |
| Failures | Recorded from `ir.http._handle_error` / RPC controllers, persisted from the request cursor's `postrollback` | Only client-visible failures; never savepoint-swallowed ones; never before the business rollback. |
| Bypass / source | Python `contextvars` only; source from the server route (`/web*`, `/jsonrpc`, `/xmlrpc`) and execution frames (cron, server/automated action, import) | A JSON-RPC client cannot send a context key that disables auditing or fakes the source. Mobile is stored as `claimed_client` (User-Agent, not verified). |
| Fail mode | Setting: `open` (default: business continues, `ENGINE_ERROR` event written separately) or `closed` (commit is blocked) | Compliance vs availability is a business decision. |
| Integrity | Rows commit unsealed; cron seals per chain (`c<company>-<year>` / `shared-<year>`) in **sealing order** (`seal_seq`), not id order | No writer contention on a chain tail; a late-committing transaction is sealed in the next run, never skipped. |
| Value digests | HMAC-SHA256 of each JSON value; canonical event hash uses digests | A governed redaction removes plaintext without breaking verification. Key from `nx_audit_hmac_key` in odoo.conf (recommended) or a generated DB parameter (settings warn). |
| Retention | hot `audit.log` -> `audit.log.archive` (searchable cold table) -> tombstone stub -> signed checkpoint | Verification keeps working after archive and purge. `prohibit_purge` policies are never purged. |
| Alerts | Outbox rows created with the evidence (same transaction), delivered by cron | An alert can never describe a rolled-back change; dedup window and hourly cap prevent storms. |
| Uninstall | `uninstall_hook` exports every audit table to `<data_dir>/nx_audit_log_exports/<db>/<timestamp>/*.jsonl.gz` | Uninstalling drops the tables. |
| Monitored module uninstall | `model_name` / `field_name` stored as Char; `ir.model` / `ir.model.fields` links are `ondelete='set null'` | Evidence survives. |

## 2. Security model

* Groups: Audit User < Audit Manager < Audit Administrator; plus *shared records* (implied by User), *cross-company auditor*, *restricted-fields override*.
* Nobody has create/write/unlink ACL on evidence; the models additionally refuse any write outside a named privileged internal operation (`persist`, `seal`, `bucket`, `redact`, `archive`, `purge`, `compact`, `uninstall`).
* Company: an event is visible to every company it touched (`visible_company_ids`: before and after company). Records without company are `is_shared`.
* Field level: lines store the `groups=` of their source field; a global record rule hides them from users not in those groups (unless override group). Restricted fields never enter snapshots.
* Configuration changes (rules, alert rules, retention, sensitive patterns, settings) produce `CONFIG` events.

## 3. Extension API (`services/api.py`)

```python
from odoo.addons.nx_audit_log.services.api import audit_action, audit_bypass, record_action

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @audit_action('Approve discount')
    def action_approve_discount(self):
        ...

    def _sync_from_erp(self):
        with audit_bypass('ERP mirror sync - audited on the ERP side'):
            ...
```

Model hook: override `_audit_dynamic_secret_fields(self, row)` to mask fields per row
(used by `ir.config_parameter` to mask secret parameter values).

## 4. Known limitations (documented, not hidden)

1. **Direct SQL** writes bypass the ORM. See `COVERAGE.md` (generated by `tools/sql_coverage_scan.py`). Notable: password storage (handled by a dedicated hook), reconciliation flags on `account.move.line`, account merge wizard.
2. **Install / upgrade** data loading is not audited (the registry is not ready). Module operations are visible in `ir.module.module` and server logs.
3. **Session expiry** is not an event in Odoo; only explicit logout (`/web/session/logout`, `/web/session/destroy`) is recorded.
4. **TOTP** is hooked on the registry class when `auth_totp` is installed (no hard dependency).
5. **Company-dependent many2one** values (jsonb) cleared by Odoo's own SQL on delete are not captured as FK effects.
6. Deleting a **company or user** referenced by sealed evidence nulls the link and is reported as a modification by verification; archive companies/users instead of deleting them.
7. Application-level hashes detect tampering; a PostgreSQL superuser can still rewrite rows and hashes together. For non-repudiation, periodically export `audit.chain` heads / checkpoints to external immutable storage.
8. Changes performed while `audit_bypass()` is active are logged in the server log (with caller), not as evidence.

## 5. Operations

* Crons: sealing (5 min), alert dispatch (5 min, also triggered on demand), retention (daily), integrity verification (daily).
* Large purges create dead tuples: schedule `VACUUM (ANALYZE) audit_log, audit_log_line, audit_log_archive;` after the first large retention runs; consider monthly partitioning of `audit_log_archive` at very high volume.
* Value search at scale: Settings > Audit > *Enable value search indexes* (pg_trgm GIN on previews).
* Backup: audit tables are part of the database backup; keep the HMAC key (odoo.conf) with the backup procedure, otherwise digests cannot be verified after restore.
* Storage growth: dashboard shows table sizes; text values are bounded by *Max stored text length* (larger values keep a digest + head).
