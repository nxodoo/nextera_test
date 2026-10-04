# Direct SQL coverage inventory - Odoo 18.0

ORM interception cannot see raw SQL writes. This inventory lists every direct
`INSERT` / `UPDATE` / `DELETE` found in `account`, `stock` and `mail` of the
targeted build (tests and migrations excluded). Regenerate after each upgrade:

    python3 tools/sql_coverage_scan.py /opt/odoo/addons account stock mail

## Assessment of the business-relevant entries

| Location | Effect | Audit consequence / compensation |
|---|---|---|
| `res.users._set_encrypted_password` (base) | Password hash stored with SQL | **Compensated**: dedicated hook records ACTION "Password changed" with a masked line. |
| `account.move.line._toggle_reconcile_to_true/false` | Flips `reconciled` flags | Not captured as field change. Reconciliation itself creates `account.partial.reconcile` / `account.full.reconcile` through the ORM: audit those models for evidence. |
| `account.merge.wizard._action_merge` | Merges accounts (UPDATE/DELETE `account_account`) | Not captured. The wizard is an administrative action: add `@audit_action` in a bridge module or restrict it to audited administrators. |
| `account.account._action_unmerge`, `chart_template.preserve_existing_tags_on_taxes` | `ir_model_data` maintenance | Technical, no business evidence needed. |
| `account.group._adapt_parent_account_group` | Parent group hierarchy | Derived structure; low risk. |
| `account.account.tag._translate_tax_tags` | Tag translations during localisation | Setup only. |
| `res.partner._clear_removed_edi_formats` (account) | Clears EDI format on partners | Low risk; captured nowhere. |
| `account.move.send._send_mail` | Re-links attachments | Attachment audit (ir.attachment rule) does not see the re-link. |
| mail: `discuss.channel`, `mail.guest`, `mail.canned.response`, `mail.message` | Chat / pin / timezone housekeeping | Excluded models (chatter is not evidence). |

## Raw scan output
| Module | File | Function | Line | Statement | Table |
|---|---|---|---|---|---|
| account | wizard/account_merge_wizard.py | `_action_merge` | 185 | UPDATE | `account_account` |
| account | wizard/account_merge_wizard.py | `_action_merge` | 197 | DELETE | `account_account` |
| account | wizard/account_merge_wizard.py | `_action_merge` | 209 | UPDATE | `account_account` |
| account | models/account_account.py | `_toggle_reconcile_to_true` | 918 | UPDATE | `account_move_line` |
| account | models/account_account.py | `_toggle_reconcile_to_false` | 944 | UPDATE | `account_move_line` |
| account | models/account_account.py | `_action_unmerge` | 1403 | UPDATE | `ir_model_data` |
| account | models/account_account.py | `_adapt_parent_account_group` | 1582 | UPDATE | `account_group` |
| account | models/account_account_tag.py | `_translate_tax_tags` | 94 | UPDATE | `account_account_tag` |
| account | models/account_move_send.py | `_send_mail` | 499 | UPDATE | `ir_attachment` |
| account | models/chart_template.py | `preserve_existing_tags_on_taxes` | 42 | UPDATE | `ir_model_data` |
| account | models/partner.py | `_clear_removed_edi_formats` | 1187 | UPDATE | `res_partner` |
| mail | controllers/thread.py | `mail_message_post` | 140 | UPDATE | `mail_canned_response` |
| mail | models/ir_model.py | `unlink` | 61 | DELETE | `mail_message` |
| mail | models/ir_model.py | `unlink` | 65 | DELETE | `mail_message` |
| mail | models/ir_model.py | `unlink` | 39 | DELETE | `mail_message` |
| mail | models/ir_model.py | `unlink` | 42 | DELETE | `mail_message` |
| mail | models/ir_model.py | `unlink` | 45 | DELETE | `mail_message` |
| mail | models/ir_model.py | `unlink` | 48 | DELETE | `mail_message` |
| mail | models/discuss/discuss_channel.py | `set_message_pin` | 857 | UPDATE | `mail_message` |
| mail | models/discuss/discuss_channel.py | `channel_fetched` | 1148 | UPDATE | `discuss_channel_member` |
| mail | models/discuss/mail_guest.py | `_update_timezone` | 114 | UPDATE | `mail_guest` |
