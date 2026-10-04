# Audit Log & Compliance Engine (nx_audit_log) - Odoo 18

Enterprise audit trail for any Odoo model without per-model code: field-level
evidence (direct / derived / database cascade), deleted-record forensics,
business actions, data access (export, print, bulk API reads), authentication,
alerts, hash-chain integrity, retention with archive/purge and governed GDPR
redaction.

## Install

1. Copy `nx_audit_log` to your addons path and install it.
2. Add to `odoo.conf` (recommended): `nx_audit_hmac_key = <64 random hex chars>`
3. Audit > Configuration > Audit Rules: default rules are created for installed
   apps. After installing new apps use Settings > Audit > *Load default rules*.
4. The broad rule *All business models* is shipped **inactive**: review its
   excluded models, then activate it if you want near-total coverage.

## Run the tests

    odoo-bin -d test_db -i nx_audit_log --test-enable --test-tags nx_audit --stop-after-init

See `doc/ARCHITECTURE.md` for design decisions and limitations and
`doc/COVERAGE.md` for the direct-SQL inventory.
