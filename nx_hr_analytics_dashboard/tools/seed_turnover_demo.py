# -*- coding: utf-8 -*-
"""
Seed demo turnover data so the Employee Turnover chart draws a real pattern.

RUN ON A TEST DATABASE ONLY — this modifies hr.employee records.

    ./odoo-bin shell -d <your_db> < nx_hr_analytics_dashboard/tools/seed_turnover_demo.py

The turnover chart computes, per month:

    rate = departures_in_month / headcount_at_month_end * 100

so BOTH sides need realistic data:

  * `departure_date` spread across several months  -> the numerator
  * `create_date` backdated                        -> the denominator

Setting only departure dates yields 100% spikes, because headcount falls back
to 1 when no employee existed yet in that month.

`create_date` is a magic column, so it is set with SQL rather than the ORM.

To undo everything, see REVERT at the bottom of this file.
"""

from dateutil.relativedelta import relativedelta

from odoo import fields

# --------------------------------------------------------------------------
# Tuning
# --------------------------------------------------------------------------
# Months back from today in which a departure happened. Keep them distinct so
# the curve has visible peaks and troughs rather than one flat block.
DEPARTURE_MONTHS_AGO = [10, 8, 7, 5, 2]
# Employees are "hired" staggered between these bounds (months ago).
HIRE_SPREAD_MONTHS = (18, 3)

env = env  # noqa: F821  (provided by `odoo-bin shell`)

Employee = env["hr.employee"].with_context(active_test=False)
today = fields.Date.context_today(Employee)

employees = Employee.search([], order="id")
if len(employees) < len(DEPARTURE_MONTHS_AGO) + 3:
    raise SystemExit(
        "Need at least %d employees to seed a meaningful trend; found %d."
        % (len(DEPARTURE_MONTHS_AGO) + 3, len(employees))
    )

print("Seeding turnover demo data for %d employees..." % len(employees))

# --------------------------------------------------------------------------
# 1) Backdate create_date so historical headcount is non-zero.
# --------------------------------------------------------------------------
oldest, newest = HIRE_SPREAD_MONTHS
step = max(1, (oldest - newest) // max(1, len(employees) - 1))
for idx, emp in enumerate(employees):
    months_ago = max(newest, oldest - idx * step)
    hired = today.replace(day=1) - relativedelta(months=months_ago)
    env.cr.execute(
        "UPDATE hr_employee SET create_date = %s WHERE id = %s",
        (fields.Datetime.to_string(fields.Datetime.to_datetime(str(hired))), emp.id),
    )
print("  create_date backdated across %d-%d months." % (newest, oldest))

# --------------------------------------------------------------------------
# 2) Give a handful of employees a departure_date in distinct months.
# --------------------------------------------------------------------------
reason = None
if "departure_reason_id" in Employee._fields:
    reason = env["hr.departure.reason"].search([], limit=1)

leavers = employees[-len(DEPARTURE_MONTHS_AGO):]
for emp, months_ago in zip(leavers, DEPARTURE_MONTHS_AGO):
    # Mid-month, so the date lands unambiguously inside the bucket.
    dep = today.replace(day=15) - relativedelta(months=months_ago)
    vals = {"departure_date": dep, "active": False}
    if reason and "departure_reason_id" in Employee._fields:
        vals["departure_reason_id"] = reason.id
    emp.write(vals)
    print("  %-28s departed %s" % (emp.name[:28], dep))

env.cr.commit()

# --------------------------------------------------------------------------
# 3) Print the resulting trend so you can confirm before opening the UI.
# --------------------------------------------------------------------------
svc = env["nx.hr.dashboard.service"]
trend = svc._turnover_trend({})
head = svc._headcount_trend({})
print("\nTurnover trend (%):")
for label, value, hc in zip(trend["labels"], trend["values"], head["values"]):
    bar = "#" * int(round(value))
    print("  %-8s %6.2f%%  headcount %-4d %s" % (label, value, hc, bar))

nonzero = [v for v in trend["values"] if v]
print(
    "\n%d of 12 months are non-zero — the chart will draw a pattern."
    % len(nonzero)
    if nonzero
    else "\nAll months are still zero; check that departure_date actually saved."
)

# --------------------------------------------------------------------------
# REVERT — paste into `odoo-bin shell` to undo this seed.
# --------------------------------------------------------------------------
# E = env["hr.employee"].with_context(active_test=False)
# departed = E.search([("departure_date", "!=", False)])
# departed.write({"departure_date": False, "active": True})
# env.cr.execute("UPDATE hr_employee SET create_date = now() WHERE id IN %s",
#                (tuple(E.search([]).ids),))
# env.cr.commit()
