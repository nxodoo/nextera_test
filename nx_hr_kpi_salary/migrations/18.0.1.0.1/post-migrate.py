from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Recompute stored KPI payouts after the KPI base calculation changed.

    Existing evaluation lines keep the value stored under the old formula
    (contract wage based), which is wrong for hourly and timesheet contracts.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["hr.kpi.evaluation.line"].search([])
    if not lines:
        return
    env.add_to_compute(lines._fields["payout_value"], lines)
    lines.flush_recordset(["payout_value"])
