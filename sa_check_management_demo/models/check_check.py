from datetime import datetime, time

from odoo import fields, models

CTX_DEMO_DATE = "sa_check_demo_date"


class CheckCheck(models.Model):
    """While generating demo data, actions and history carry the scenario date instead of today."""

    _inherit = "check.check"

    is_demo = fields.Boolean(readonly=True, copy=False, index=True)

    def _action_default_vals(self, action):
        vals = super()._action_default_vals(action)
        demo_date = self.env.context.get(CTX_DEMO_DATE)
        if demo_date:
            today = fields.Date.context_today(self)
            vals = {key: (demo_date if value == today else value) for key, value in vals.items()}
        return vals

    def _prepare_event_vals(self, event_type, old_state, new_state, note, source):
        vals = super()._prepare_event_vals(event_type, old_state, new_state, note, source)
        demo_date = self.env.context.get(CTX_DEMO_DATE)
        if demo_date:
            vals["date"] = datetime.combine(demo_date, time(9 + (self.id % 8), (self.id * 7) % 60))
        return vals
