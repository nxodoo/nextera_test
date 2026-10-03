import logging
import random
from datetime import timedelta

from odoo import Command, api, fields, models

from . import demo_catalog as cat
from .check_check import CTX_DEMO_DATE

_logger = logging.getLogger(__name__)

DEMO_REF = "SA-DEMO"
QUIET = {"tracking_disable": True, "mail_create_nolog": True, "mail_notrack": True, "mail_create_nosubscribe": True}

# (scenario, weight). Deposit scenarios are generated in groups sharing one deposit slip.
INCOMING_SINGLE = [
    ("draft", 2), ("received_future", 14), ("received_overdue", 3), ("returned", 2), ("endorsed", 5),
    ("endorsed_bounced", 1), ("discounted", 2), ("discount_collected", 2), ("lost", 1), ("cancelled", 2),
    ("guarantee_held", 4), ("guarantee_released", 2),
]
INCOMING_DEPOSIT_SHARE = 0.55
DEPOSIT_OUTCOMES = [
    ("collected", 75), ("bounced", 8), ("redeposit_collected", 5), ("legal", 3), ("settled", 3), ("replaced", 3),
    ("collected_with_fee", 3),
]
OUTGOING = [
    ("draft", 3), ("pending_approval", 4), ("approved", 3), ("issued", 12), ("delivered", 14), ("presented", 4),
    ("cleared", 40), ("stopped", 2), ("rejected", 2), ("replaced", 1), ("cancelled", 3), ("lost", 1),
    ("guarantee_out", 4), ("stale", 3),
]


def _weighted(rng, choices):
    return rng.choices([name for name, _w in choices], weights=[w for _n, w in choices], k=1)[0]


class CheckDemoGenerator(models.AbstractModel):
    _name = "check.demo.generator"
    _description = "Check Demo Data Generator"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    @api.model
    def _generate(self, count, seed=1, start=0, incoming_share=65, months_back=12, months_ahead=6,
                  create_users=True, password=None):
        """Generate ``count`` checks; returns (created, failed, next index)."""
        env = self.sudo().with_context(**QUIET)
        master = env._ensure_master_data(create_users, password)
        env = env.with_context(sa_check_demo_users={role: users.ids for role, users in master["users"].items()})
        created = failed = 0
        index = start
        while created + failed < count:
            rng = random.Random(seed * 1_000_003 + index)
            size = 1
            try:
                with env.env.cr.savepoint():
                    size = env._generate_unit(rng, index, master, incoming_share, months_back, months_ahead,
                                              remaining=count - created - failed)
                created += size
            except Exception:  # noqa: BLE001 - demo data must keep going; the failure is logged
                _logger.exception("Check demo scenario %s failed", index)
                env.env.invalidate_all()
                failed += 1
            index += 1
        return created, failed, index

    def _generate_unit(self, rng, index, master, incoming_share, months_back, months_ahead, remaining=1):
        horizon = {"back": months_back * 30, "ahead": months_ahead * 30}
        if rng.randint(1, 100) > incoming_share:
            return self._run_outgoing(rng, index, master, horizon)
        if rng.random() < INCOMING_DEPOSIT_SHARE:
            return self._run_deposit_group(rng, index, master, horizon, remaining)
        return self._run_incoming_single(rng, index, master, horizon)

    # ------------------------------------------------------------------
    # Master data (created once, found again on later runs)
    # ------------------------------------------------------------------
    def _ensure_master_data(self, create_users=True, password=None):
        company = self.env.company
        company._sa_check_accounting_setup()
        company.write({"check_discount_enabled": True, "check_outgoing_approval_required": True})
        journals = self._ensure_bank_journals(company)
        master = {
            "company": company,
            "customers": self._ensure_partners("C", 150, cat.CUSTOMER_ACTIVITIES),
            "vendors": self._ensure_partners("V", 60, cat.VENDOR_ACTIVITIES),
            "lawyers": self._ensure_lawyers(),
            "banks": self._ensure_banks(),
            "journals": journals,
            "locations": self._ensure_locations(company),
            "income": self._account(company, "income"),
            "expense": self._account(company, "expense"),
            "reasons": self.env["check.bounce.reason"].search([]),
            "users": self._ensure_users(company, password) if create_users else {},
        }
        self._assign_reps(master)
        self._ensure_discount_term(journals[0])
        self._ensure_approval_stages(company)
        return master

    def _ensure_partners(self, kind, count, activities):
        Partner = self.env["res.partner"]
        refs = [f"{DEMO_REF}-{kind}-{n:04d}" for n in range(count)]
        existing = Partner.search([("ref", "in", refs)])
        known = set(existing.mapped("ref"))
        missing = [ref for ref in refs if ref not in known]
        lang = "ar_001" if self.env["res.lang"].search_count([("code", "=", "ar_001")]) else self.env.lang
        vals = []
        for ref in missing:
            n = int(ref[-4:])
            name = (f"{cat.COMPANY_PREFIXES[n % len(cat.COMPANY_PREFIXES)]} "
                    f"{cat.COMPANY_NAMES[(n * 7) % len(cat.COMPANY_NAMES)]} "
                    f"{activities[(n * 3) % len(activities)]}")
            if n >= len(cat.COMPANY_NAMES):
                name += f" - {cat.CITIES[n % len(cat.CITIES)]}"
            vals.append({"name": name, "ref": ref, "is_company": True, "city": cat.CITIES[n % len(cat.CITIES)],
                         "lang": lang})
        return (existing | Partner.create(vals)).sorted("ref")

    def _ensure_users(self, company, password=None):
        """One or more users per check role, reused on later runs; returns {role: users}."""
        lang = "ar_001" if self.env["res.lang"].search_count([("code", "=", "ar_001")]) else self.env.lang
        users = {}
        for login, name, role, groups in cat.DEMO_USERS:
            user = self.env["res.users"].with_context(active_test=False).search([("login", "=", login)], limit=1)
            if not user:
                group_ids = [self.env.ref("base.group_user").id] + [self.env.ref(xmlid).id for xmlid in groups]
                user = self.env["res.users"].with_context(no_reset_password=True).create({
                    "name": name, "login": login, "password": password or cat.DEFAULT_PASSWORD, "lang": lang,
                    "company_id": company.id, "company_ids": [Command.link(company.id)],
                    "groups_id": [Command.set(group_ids)],
                })
            users[role] = users.get(role, self.env["res.users"]) | user
        return users

    def _assign_reps(self, master):
        reps = master["users"].get("rep")
        if not reps:
            return
        people = master["locations"].filtered(lambda l: l.location_type == "person")
        for location, rep in zip(people, reps):
            if not location.user_id:
                location.user_id = rep

    def _user(self, role, record):
        """The user playing ``role`` for this record (stable per record); the admin when users are off."""
        ids = (self.env.context.get("sa_check_demo_users") or {}).get(role)
        if not ids:
            return self.env.user
        return self.env["res.users"].browse(ids[record.id % len(ids)])

    def _by(self, record, role, date):
        """``record`` acting as the user of ``role`` on ``date`` (with system rights, the user's name)."""
        return record.with_user(self._user(role, record)).sudo().with_context(**self._at(date))

    def _ensure_lawyers(self):
        Partner = self.env["res.partner"]
        result = Partner
        for n, name in enumerate(cat.LAWYERS):
            ref = f"{DEMO_REF}-L-{n}"
            result |= Partner.search([("ref", "=", ref)], limit=1) or Partner.create({"name": name, "ref": ref})
        return result

    def _ensure_banks(self):
        Bank = self.env["res.bank"]
        result = Bank
        for name, bic in cat.BANKS:
            result |= Bank.search([("bic", "=", bic)], limit=1) or Bank.create({"name": name, "bic": bic})
        return result

    def _ensure_bank_journals(self, company):
        Journal = self.env["account.journal"]
        journals = Journal
        for name, code in cat.COMPANY_BANK_JOURNALS:
            journal = Journal.search([("company_id", "=", company.id), ("code", "=", code)], limit=1)
            journals |= journal or Journal.create({"name": name, "code": code, "type": "bank", "company_id": company.id})
        return journals

    def _ensure_locations(self, company):
        Location = self.env["check.location"]
        result = Location
        for name, kind in cat.LOCATIONS:
            location = Location.search([("company_id", "=", company.id), ("name", "=", name)], limit=1)
            result |= location or Location.create({"name": name, "location_type": kind, "company_id": company.id})
        if not company.check_default_location_id:
            company.check_default_location_id = result[:1]
        return result

    def _ensure_discount_term(self, journal):
        Term = self.env["check.discount.term"]
        if not Term.search([("journal_id", "=", journal.id)]):
            Term.create({"journal_id": journal.id, "advance_rate": 80.0, "interest_rate": 18.0, "fixed_fee": 25.0})

    def _ensure_approval_stages(self, company):
        Rule = self.env["check.approval.rule"]
        if Rule.search_count([("company_id", "=", company.id)]):
            return
        Rule.create([
            {"name": "Finance Approval", "sequence": 10, "min_amount": 0.0, "company_id": company.id,
             "group_id": self.env.ref("sa_check_management.group_check_approver").id},
            {"name": "Check Manager", "sequence": 20, "min_amount": 200000.0, "company_id": company.id,
             "group_id": self.env.ref("sa_check_management.group_check_manager").id},
        ])

    def _account(self, company, account_type):
        Account = self.env["account.account"].with_company(company)
        return Account.search([*Account._check_company_domain(company), ("account_type", "=", account_type)], limit=1)

    # ------------------------------------------------------------------
    # Random building blocks
    # ------------------------------------------------------------------
    def _today(self):
        return fields.Date.context_today(self)

    def _amount(self, rng):
        tier = rng.random()
        if tier < 0.5:
            return round(rng.uniform(2_000, 20_000) / 50) * 50
        if tier < 0.9:
            return round(rng.uniform(20_000, 150_000) / 100) * 100
        return round(rng.uniform(150_000, 1_200_000) / 500) * 500

    def _snap_to_deposit_day(self, day, floor):
        """Banks are visited on Sundays and Wednesdays: deposits cluster on those days."""
        while day.weekday() not in (2, 6) and day > floor:
            day -= timedelta(days=1)
        return max(day, floor)

    def _at(self, date):
        return {CTX_DEMO_DATE: date}

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def _invoice(self, partner, amount, date, master, move_type="out_invoice"):
        account = master["income"] if move_type == "out_invoice" else master["expense"]
        move = self.env["account.move"].create({
            "move_type": move_type, "partner_id": partner.id, "invoice_date": date, "date": date,
            "invoice_line_ids": [Command.create({"name": "Demo goods", "price_unit": amount, "tax_ids": [],
                                                 "account_id": account.id})],
        })
        move.action_post()
        return move

    def _documents_for(self, rng, partner, amount, date, master, move_type):
        """One or two documents covering the check (sometimes leaving an unallocated remainder)."""
        covered = amount if rng.random() > 0.1 else round(amount * rng.uniform(0.6, 0.95), -1)
        if rng.random() < 0.3 and covered > 4000:
            first = round(covered * rng.uniform(0.3, 0.7), -1)
            return [self._invoice(partner, first, date, master, move_type),
                    self._invoice(partner, covered - first, date, master, move_type)]
        return [self._invoice(partner, covered, date, master, move_type)]

    def _allocate(self, check, documents):
        for move in documents:
            line = move.line_ids.filtered(lambda l: l.account_id.account_type in ("asset_receivable", "liability_payable"))
            self.env["check.allocation"].create({"check_id": check.id, "move_line_id": line.id,
                                                 "amount": abs(line.amount_residual_currency)})

    # ------------------------------------------------------------------
    # Incoming checks
    # ------------------------------------------------------------------
    def _new_incoming(self, rng, serial, master, receive_date, due_date, purpose="payment"):
        partner = rng.choice(master["customers"])
        amount = self._amount(rng)
        third_party = rng.random() < 0.15
        clerk = self._user("clerk", partner)
        check = self.env["check.check"].with_user(clerk).sudo().with_context(
            default_check_type="incoming", **self._at(receive_date)).create({
            "check_number": str(10_000_000 + serial),
            "partner_id": partner.id,
            "amount": amount,
            "issue_date": receive_date - timedelta(days=rng.randint(0, 4)),
            "due_date": due_date,
            "bank_id": rng.choice(master["banks"]).id,
            "drawer_is_partner": not third_party,
            "drawer_name": f"{rng.choice(cat.COMPANY_NAMES)} {rng.choice(cat.CITIES)}" if third_party else False,
            "drawer_account_number": f"{partner.id:05d}{rng.randint(100, 999)}" if not third_party
            else str(rng.randint(10_000_000, 99_999_999)),
            "purpose": purpose,
            "current_location_id": rng.choice(master["locations"][:3]).id,
            "responsible_user_id": self._user("treasury", partner).id,
            "is_demo": True,
        })
        if purpose == "payment":
            invoice_date = receive_date - timedelta(days=rng.randint(5, 60))
            self._allocate(check, self._documents_for(rng, partner, amount, invoice_date, master, "out_invoice"))
        return check

    def _receive(self, check, date):
        self._by(check, "treasury", date).action_receive()

    def _run_incoming_single(self, rng, index, master, horizon):
        scenario = _weighted(rng, INCOMING_SINGLE)
        today = self._today()
        if scenario in ("received_overdue", "discount_collected"):
            receive = today - timedelta(days=rng.randint(30, min(150, horizon["back"])))
            due = min(receive + timedelta(days=rng.randint(10, 90)), today - timedelta(days=2))
        else:
            receive = today - timedelta(days=rng.randint(1, 45))
            due = today + timedelta(days=rng.randint(20, max(21, horizon["ahead"])))
        purpose = "guarantee" if scenario.startswith("guarantee") else "payment"
        check = self._new_incoming(rng, index * 8, master, receive, due, purpose)
        if scenario == "draft":
            return 1
        self._receive(check, receive)
        self._maybe_handover(rng, check, master, receive)
        getattr(self, f"_incoming_{scenario}")(rng, check, master, receive)
        return 1

    def _incoming_received_future(self, rng, check, master, receive):
        pass

    def _incoming_received_overdue(self, rng, check, master, receive):
        pass

    def _incoming_guarantee_held(self, rng, check, master, receive):
        check.guarantee_expiry_date = check.due_date + timedelta(days=rng.randint(30, 365))
        check.guarantee_description = rng.choice(["مناقصة توريد", "عقد توزيع", "ضمان حسن تنفيذ", "تأمين مستأجر"])

    def _incoming_guarantee_released(self, rng, check, master, receive):
        self._incoming_guarantee_held(rng, check, master, receive)
        date = min(receive + timedelta(days=rng.randint(5, 40)), self._today())
        self._by(check, "manager", date)._apply_release("انتهاء التعاقد", "مندوب العميل", date)

    def _incoming_returned(self, rng, check, master, receive):
        date = min(receive + timedelta(days=rng.randint(1, 10)), self._today())
        self._by(check, "treasury", date)._apply_return("طلب العميل", "مندوب العميل", date)

    def _incoming_lost(self, rng, check, master, receive):
        date = min(receive + timedelta(days=rng.randint(1, 10)), self._today())
        self._by(check, "manager", date)._apply_lose("فُقد أثناء النقل", date)

    def _incoming_cancelled(self, rng, check, master, receive):
        self._by(check, "manager", receive)._apply_cancel("خطأ في التسجيل", receive)

    def _incoming_endorsed(self, rng, check, master, receive):
        vendor = rng.choice(master["vendors"])
        date = min(receive + timedelta(days=rng.randint(1, 10)), self._today())
        bill = self._invoice(vendor, round(check.amount * rng.uniform(0.7, 1.0), -1), date - timedelta(days=3),
                             master, "in_invoice")
        items = check._open_allocation_items(vendor, "liability_payable").filtered(lambda i: i.move_id == bill)
        shares = check._distribute_over_items(items, abs(sum(items.mapped("amount_residual_currency"))),
                                              check._reserved_amounts(items))
        self._by(check, "treasury", date)._apply_endorse(vendor, date, shares, "سداد مستحقات المورد")

    def _incoming_endorsed_bounced(self, rng, check, master, receive):
        self._incoming_endorsed(rng, check, master, receive)
        date = min(check.endorsed_date + timedelta(days=rng.randint(3, 15)), self._today())
        self._by(check, "treasury", date)._apply_endorse_bounce(master["reasons"][:1], date, False, False)

    def _incoming_discounted(self, rng, check, master, receive):
        journal = master["journals"][0]
        term = self.env["check.discount.term"].search([("journal_id", "=", journal.id)], limit=1)
        date = min(receive + timedelta(days=rng.randint(1, 4)), self._today())
        if date >= check.due_date:
            return
        advance = term._advance_for(check.amount)
        fee = term._charges_for(advance, (check.due_date - date).days)
        self._by(check, "treasury", date)._apply_discount(journal, date, advance, fee)

    def _incoming_discount_collected(self, rng, check, master, receive):
        self._incoming_discounted(rng, check, master, receive)
        if check.state == "discounted":
            date = min(check.due_date + timedelta(days=rng.randint(0, 3)), self._today())
            self._by(check, "treasury", date)._apply_discount_collect(date)

    def _maybe_handover(self, rng, check, master, date):
        if rng.random() > 0.1 or check.state != "received":
            return
        origin = check.current_location_id
        target = rng.choice(master["locations"] - origin)
        handover = self.env["check.handover"].create({
            "check_ids": [Command.set(check.ids)], "from_location_id": origin.id, "to_location_id": target.id,
            "date": fields.Datetime.to_datetime(date),
        })
        self._by(handover, "treasury", date).action_send()
        if handover.state == "pending":
            receiver = target.user_id or self._user("treasury", handover)
            handover.with_user(receiver).sudo().with_context(**self._at(date)).action_accept()

    # ------------------------------------------------------------------
    # Deposit groups: one slip, several checks, different outcomes
    # ------------------------------------------------------------------
    def _run_deposit_group(self, rng, index, master, horizon, remaining=5):
        today = self._today()
        open_group = rng.random() < 0.2
        if open_group:
            deposit_date = today - timedelta(days=rng.randint(1, 6))
        else:
            deposit_date = today - timedelta(days=rng.randint(8, max(9, horizon["back"] - 20)))
        deposit_date = self._snap_to_deposit_day(deposit_date, today - timedelta(days=horizon["back"] - 10))
        size = min(rng.randint(1, 5), max(remaining, 1))
        journal = rng.choice(master["journals"])
        checks = self.env["check.check"]
        for member in range(size):
            due = deposit_date + timedelta(days=rng.randint(-3, 25 if open_group else 2))
            receive = min(due, deposit_date) - timedelta(days=rng.randint(3, 75))
            check = self._new_incoming(rng, index * 8 + member, master, receive, max(due, receive), "payment")
            self._receive(check, receive)
            checks |= check
        deposit = self.env["check.deposit"].create({
            "journal_id": journal.id, "date": deposit_date, "reference": f"SLIP-{index:06d}",
            "line_ids": [Command.create({"check_id": check.id}) for check in checks],
        })
        self._by(deposit, "treasury", deposit_date).action_confirm()
        if not open_group:
            for check in checks:
                self._deposit_outcome(rng, check, master, deposit_date, journal)
        return size

    def _deposit_outcome(self, rng, check, master, deposit_date, journal):
        outcome = _weighted(rng, DEPOSIT_OUTCOMES)
        result_date = min(deposit_date + timedelta(days=rng.randint(1, 4)), self._today())
        getattr(self, f"_outcome_{outcome}")(rng, check, master, result_date, journal)

    def _outcome_collected(self, rng, check, master, date, journal):
        self._by(check, "treasury", date)._apply_collect(date)

    def _outcome_collected_with_fee(self, rng, check, master, date, journal):
        self._outcome_collected(rng, check, master, date, journal)
        self._by(check, "treasury", date)._post_bank_fee(round(rng.uniform(5, 30)), date, journal)

    def _outcome_bounced(self, rng, check, master, date, journal):
        reason = rng.choice(master["reasons"].filtered(lambda r: not r.requires_note))
        reference = f"REJ-{rng.randint(100000, 999999)}"
        self._by(check, "treasury", date)._apply_bounce(reason, date, False, reference)
        if rng.random() < 0.3:
            self._by(check, "treasury", date)._post_bank_fee(round(rng.uniform(25, 150)), date, journal,
                                                                label="رسوم ارتداد")

    def _outcome_redeposit_collected(self, rng, check, master, date, journal):
        self._outcome_bounced(rng, check, master, date, journal)
        redeposit_date = min(date + timedelta(days=rng.randint(3, 10)), self._today())
        deposit = self.env["check.deposit"].create({
            "journal_id": journal.id, "date": redeposit_date,
            "line_ids": [Command.create({"check_id": check.id})],
        })
        try:
            with self.env.cr.savepoint():
                self._by(deposit, "treasury", redeposit_date).action_confirm()
        except Exception:  # noqa: BLE001 - the invoice may have been settled meanwhile: keep the bounce
            self.env.invalidate_all()
            return
        collect_date = min(redeposit_date + timedelta(days=rng.randint(1, 3)), self._today())
        self._by(check, "treasury", collect_date)._apply_collect(collect_date)

    def _outcome_legal(self, rng, check, master, date, journal):
        self._outcome_bounced(rng, check, master, date, journal)
        legal_date = min(date + timedelta(days=rng.randint(7, 30)), self._today())
        self._by(check, "treasury", legal_date)._apply_legal(
            legal_date, f"{rng.randint(100, 9999)}/{legal_date.year}", rng.choice(master["lawyers"]),
            rng.choice(cat.COURTS), "جنحة شيك بدون رصيد",
        )

    def _outcome_settled(self, rng, check, master, date, journal):
        self._outcome_bounced(rng, check, master, date, journal)
        settle_date = min(date + timedelta(days=rng.randint(2, 20)), self._today())
        self._by(check, "treasury", settle_date)._apply_settle("سداد نقدي بالفرع", settle_date)

    def _outcome_replaced(self, rng, check, master, date, journal):
        self._outcome_bounced(rng, check, master, date, journal)
        replace_date = min(date + timedelta(days=rng.randint(3, 15)), self._today())
        self._by(check, "treasury", replace_date)._apply_replace({
            "check_number": str(9_000_000 + check.id),
            "amount": check.amount,
            "issue_date": replace_date,
            "due_date": replace_date + timedelta(days=rng.randint(10, 60)),
            "bank_id": check.bank_id.id,
            "drawer_account_number": check.drawer_account_number,
            "is_demo": True,
        }, transfer_allocations=True, receive_now=True)

    # ------------------------------------------------------------------
    # Outgoing checks
    # ------------------------------------------------------------------
    def _next_leaf(self, journal):
        Leaf = self.env["check.book.line"]
        leaf = Leaf.search([("journal_id", "=", journal.id), ("state", "=", "available"),
                            ("book_state", "=", "active")], order="number", limit=1)
        if leaf:
            return leaf
        last = self.env["check.book"].search([("journal_id", "=", journal.id), ("generation", "=", "range")],
                                             order="last_number desc", limit=1)
        start = (last.last_number or 100_000) + 1
        book = self.env["check.book"].create({"journal_id": journal.id, "first_number": start,
                                              "last_number": start + 999, "padding": 6})
        book.action_activate()
        return self._next_leaf(journal)

    def _run_outgoing(self, rng, index, master, horizon):
        scenario = _weighted(rng, OUTGOING)
        today = self._today()
        if scenario in ("cleared", "stopped", "rejected", "replaced", "lost"):
            due = today - timedelta(days=rng.randint(5, max(6, horizon["back"] - 30)))
            issue = due - timedelta(days=rng.randint(0, 60))
        elif scenario == "stale":
            issue = today - timedelta(days=rng.randint(200, max(201, horizon["back"])))
            due = issue + timedelta(days=rng.randint(0, 20))
        else:
            issue = today - timedelta(days=rng.randint(0, 20))
            due = today + timedelta(days=rng.randint(1, max(2, horizon["ahead"])))
        check = self._new_outgoing(rng, master, issue, due, "guarantee" if scenario == "guarantee_out" else "payment")
        getattr(self, f"_outgoing_{scenario}")(rng, check, issue)
        return 1

    def _new_outgoing(self, rng, master, issue, due, purpose):
        vendor = rng.choice(master["vendors"])
        journal = rng.choice(master["journals"])
        amount = self._amount(rng)
        clerk = self._user("clerk", vendor)
        check = self.env["check.check"].with_user(clerk).sudo().with_context(
            default_check_type="outgoing", **self._at(issue)).create({
            "check_number": "pending",
            "leaf_id": self._next_leaf(journal).id,
            "partner_id": vendor.id,
            "amount": amount,
            "issue_date": issue,
            "due_date": max(due, issue),
            "journal_id": journal.id,
            "purpose": purpose,
            "responsible_user_id": self._user("treasury", vendor).id,
            "is_demo": True,
        })
        if purpose == "payment":
            self._allocate(check, self._documents_for(rng, vendor, amount, issue - timedelta(days=rng.randint(5, 45)),
                                                      master, "in_invoice"))
        return check

    def _approve(self, check, date):
        self._by(check, "clerk", date).action_submit()
        while check.state == "pending_approval":
            stage = check.current_approval_line_id
            role = "manager" if stage.group_id == self.env.ref("sa_check_management.group_check_manager") else "approver"
            self._by(check, role, date).action_approve()

    def _issue(self, check, date):
        self._approve(check, date)
        self._by(check, "treasury", date).action_issue()

    def _deliver(self, rng, check, date):
        self._issue(check, date)
        day = date + timedelta(days=rng.randint(0, 3))
        self._by(check, "treasury", min(day, self._today()))._apply_deliver("مندوب المورد", min(day, self._today()))

    def _outgoing_draft(self, rng, check, issue):
        pass

    def _outgoing_pending_approval(self, rng, check, issue):
        self._by(check, "clerk", issue).action_submit()

    def _outgoing_approved(self, rng, check, issue):
        self._approve(check, issue)

    def _outgoing_issued(self, rng, check, issue):
        self._issue(check, issue)

    def _outgoing_delivered(self, rng, check, issue):
        self._deliver(rng, check, issue)

    def _outgoing_presented(self, rng, check, issue):
        self._deliver(rng, check, issue)
        self._by(check, "treasury", min(issue + timedelta(days=4), self._today())).action_mark_presented()

    def _outgoing_cleared(self, rng, check, issue):
        self._deliver(rng, check, issue)
        date = min(check.due_date + timedelta(days=rng.randint(0, 7)), self._today())
        self._by(check, "treasury", date)._apply_clear(date)

    def _outgoing_stopped(self, rng, check, issue):
        self._deliver(rng, check, issue)
        date = min(check.delivered_date + timedelta(days=rng.randint(1, 10)), self._today())
        self._by(check, "treasury", date)._apply_stop("نزاع مع المورد", date, f"STOP-{rng.randint(1000, 9999)}")

    def _outgoing_rejected(self, rng, check, issue):
        self._deliver(rng, check, issue)
        date = min(check.due_date + timedelta(days=rng.randint(0, 5)), self._today())
        reason = self.env.ref("sa_check_management.bounce_reason_insufficient_funds")
        self._by(check, "treasury", date)._apply_bank_reject(reason, date, False, f"REJ-{rng.randint(1000, 9999)}")

    def _outgoing_replaced(self, rng, check, issue):
        self._outgoing_rejected(rng, check, issue)
        date = min(check.last_bounce_date + timedelta(days=rng.randint(1, 7)), self._today())
        self._by(check, "treasury", date)._apply_replace({
            "check_number": "pending", "leaf_id": self._next_leaf(check.journal_id).id, "amount": check.amount,
            "issue_date": date, "due_date": date + timedelta(days=rng.randint(5, 30)),
            "journal_id": check.journal_id.id, "is_demo": True,
        }, transfer_allocations=True)

    def _outgoing_cancelled(self, rng, check, issue):
        self._issue(check, issue)
        self._by(check, "manager", issue)._apply_cancel("خطأ في الطباعة", issue)

    def _outgoing_lost(self, rng, check, issue):
        self._deliver(rng, check, issue)
        self._by(check, "manager", check.delivered_date)._apply_lose("فقده المندوب", check.delivered_date)

    def _outgoing_guarantee_out(self, rng, check, issue):
        check.guarantee_expiry_date = check.due_date + timedelta(days=rng.randint(60, 365))
        check.guarantee_description = rng.choice(["تأمين ابتدائي لمناقصة", "ضمان إيجار مخزن", "تأمين نهائي لعقد"])
        self._deliver(rng, check, issue)

    def _outgoing_stale(self, rng, check, issue):
        self._deliver(rng, check, issue)
