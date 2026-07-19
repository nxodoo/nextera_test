from datetime import timedelta

import pytz

from odoo import _, api, fields, models


ELIGIBLE_MOVE_WEEKDAYS = {6, 0, 1, 2}
THURSDAY_WEEKDAY = 3


class ResourceCalendarLeaves(models.Model):
    _inherit = "resource.calendar.leaves"

    def _get_effective_calendar(self, values=None):
        """Resolve the calendar used to evaluate a public holiday."""
        values = values or {}
        calendar_id = values.get("calendar_id", self.calendar_id.id if self else False)
        company_id = values.get("company_id", self.company_id.id if self else self.env.company.id)
        calendar = self.env["resource.calendar"].browse(calendar_id) if calendar_id else False
        if calendar:
            return calendar
        company = self.env["res.company"].browse(company_id) if company_id else self.env.company
        return company.resource_calendar_id

    def _get_effective_public_holiday_values(self, values=None):
        """Build the effective values used to evaluate a public holiday move."""
        self.ensure_one()
        values = values or {}
        return {
            "resource_id": values.get("resource_id", self.resource_id.id or False),
            "calendar_id": values.get("calendar_id", self.calendar_id.id or False),
            "company_id": values.get("company_id", self.company_id.id or self.env.company.id),
            "date_from": values.get("date_from", self.date_from),
            "date_to": values.get("date_to", self.date_to),
        }

    @api.model
    def _normalize_public_holiday_values(self, values):
        """Normalize create/write payload values for public holiday evaluation."""
        return {
            "resource_id": values.get("resource_id", False),
            "calendar_id": values.get("calendar_id", False),
            "company_id": values.get("company_id", self.env.company.id),
            "date_from": values.get("date_from"),
            "date_to": values.get("date_to"),
        }

    @api.model
    def _get_calendar_timezone(self, calendar):
        """Return the timezone used to evaluate working days for a calendar."""
        timezone_name = calendar.tz or self.env.user.tz or "UTC"
        return pytz.timezone(timezone_name)

    @api.model
    def _to_calendar_local_datetime(self, value, calendar):
        """Convert a UTC-naive datetime value into the calendar timezone."""
        if not value:
            return False
        datetime_value = fields.Datetime.to_datetime(value)
        if not datetime_value:
            return False
        return pytz.utc.localize(datetime_value).astimezone(self._get_calendar_timezone(calendar))

    @api.model
    def _calendar_has_working_day(self, calendar, weekday):
        """Check whether the calendar contains attendances for the given weekday."""
        return bool(calendar.attendance_ids.filtered(lambda attendance: int(attendance.dayofweek) == weekday))

    @api.model
    def _get_local_public_holiday_range(self, date_from, date_to, calendar):
        """Build a stable local datetime range for the holiday row.

        The editable list view may not always provide a reliable `date_to` while a new
        row is being saved, so we derive a safe end datetime from `date_from` when needed.
        """
        local_date_from = self._to_calendar_local_datetime(date_from, calendar)
        if not local_date_from:
            return False, False

        local_date_to = self._to_calendar_local_datetime(date_to, calendar) if date_to else False
        if not local_date_to or local_date_to.date() < local_date_from.date():
            local_date_to = local_date_from.replace(hour=23, minute=59, second=59, microsecond=0)
        return local_date_from, local_date_to

    @api.model
    def _normalize_public_holiday_same_day(self, values, record=False):
        """Keep public holiday end datetimes on the same local day as the start date."""
        effective_values = (
            record._get_effective_public_holiday_values(values)
            if record
            else self._normalize_public_holiday_values(values)
        )
        if effective_values.get("resource_id") or not effective_values.get("date_from"):
            return values

        calendar = (record or self)._get_effective_calendar(effective_values)
        if not calendar:
            return values

        local_date_from, local_date_to = self._get_local_public_holiday_range(
            effective_values.get("date_from"),
            effective_values.get("date_to"),
            calendar,
        )
        if not local_date_from:
            return values

        if not local_date_to or local_date_to.date() != local_date_from.date():
            target_local_date_to = local_date_from.replace(hour=23, minute=59, second=59, microsecond=0)
            values["date_to"] = fields.Datetime.to_string(
                target_local_date_to.astimezone(pytz.utc).replace(tzinfo=None)
            )
        return values

    @api.model
    def _get_target_thursday_datetimes(self, local_date_from, local_date_to):
        """Return the target Thursday datetimes in the same local week."""
        days_to_thursday = (THURSDAY_WEEKDAY - local_date_from.weekday()) % 7
        return (
            local_date_from + timedelta(days=days_to_thursday),
            local_date_to + timedelta(days=days_to_thursday),
        )

    @api.model
    def _to_user_datetime_string(self, value):
        """Return a naive datetime string in the current user's timezone.

        The frontend save flow expects local wall-clock datetime strings for
        edited values. Returning raw UTC strings here can shift the chosen day
        in the date picker by one day for non-UTC users.
        """
        if not value:
            return False
        user_tz_name = self.env.user.tz or self.env.context.get("tz") or "UTC"
        user_tz = pytz.timezone(user_tz_name)
        user_dt = pytz.utc.localize(value).astimezone(user_tz).replace(tzinfo=None)
        return fields.Datetime.to_string(user_dt)

    @api.model
    def _has_public_holiday_conflict(self, date_from, date_to, calendar, company, excluded_record=False):
        """Check whether another public holiday already overlaps the target Thursday."""
        conflict_domain = [
            ("resource_id", "=", False),
            ("company_id", "=", company.id),
            ("date_from", "<=", date_to),
            ("date_to", ">=", date_from),
        ]
        if excluded_record:
            conflict_domain.append(("id", "!=", excluded_record.id))
        conflicting_leaves = self.search(conflict_domain)
        if not calendar:
            return bool(conflicting_leaves)
        return bool(
            conflicting_leaves.filtered(
                lambda leave: not leave.calendar_id or leave.calendar_id == calendar
            )
        )

    @api.model
    def _build_public_holiday_move_plan(self, values, record=False):
        """Compute whether the public holiday should prompt a Thursday move.

        Parameters
        ----------
        values: dict
            Effective record values after the pending create/write change.
        record: resource.calendar.leaves
            Existing public holiday record when editing, or an empty recordset on create.

        Returns
        -------
        dict
            A UI-friendly payload that indicates whether a prompt should be shown and,
            when applicable, which Thursday dates should be applied.

        Example
        -------
        self.env["resource.calendar.leaves"]._build_public_holiday_move_plan({
            "calendar_id": calendar.id,
            "date_from": "2026-07-21 09:00:00",
            "date_to": "2026-07-21 18:00:00",
        })
        """
        calendar = self.env["resource.calendar"].browse(values.get("calendar_id")) if values.get("calendar_id") else False
        company = self.env["res.company"].browse(values.get("company_id")) if values.get("company_id") else self.env.company
        effective_calendar = calendar or company.resource_calendar_id
        date_from = fields.Datetime.to_datetime(values.get("date_from"))
        date_to = fields.Datetime.to_datetime(values.get("date_to"))

        if values.get("resource_id") or not effective_calendar or not date_from:
            return {"should_prompt": False}

        local_date_from, local_date_to = self._get_local_public_holiday_range(
            date_from,
            date_to,
            effective_calendar,
        )
        if not local_date_from:
            return {"should_prompt": False}

        weekday = local_date_from.weekday()
        if weekday not in ELIGIBLE_MOVE_WEEKDAYS:
            return {"should_prompt": False}

        if not self._calendar_has_working_day(effective_calendar, weekday):
            return {"should_prompt": False}

        if not self._calendar_has_working_day(effective_calendar, THURSDAY_WEEKDAY):
            return {"should_prompt": False}

        target_local_from, target_local_to = self._get_target_thursday_datetimes(local_date_from, local_date_to)
        if target_local_from.date() == local_date_from.date():
            return {"should_prompt": False}

        target_date_from = target_local_from.astimezone(pytz.utc).replace(tzinfo=None)
        target_date_to = target_local_to.astimezone(pytz.utc).replace(tzinfo=None)
        if self._has_public_holiday_conflict(
            target_date_from,
            target_date_to,
            calendar,
            company,
            excluded_record=record,
        ):
            return {"should_prompt": False}

        return {
            "should_prompt": True,
            "target_date_from": self._to_user_datetime_string(target_date_from),
            "target_date_to": self._to_user_datetime_string(target_date_to),
            "message": _(
                "This public holiday falls on a working day. Do you want to move it to Thursday?"
            ),
        }

    @api.model
    def get_public_holiday_thursday_move_data(self, values, record_id=False):
        """Return the save-time decision data for the public holiday Thursday move prompt."""
        record = self.browse(record_id) if record_id else self.env["resource.calendar.leaves"]
        effective_values = (
            record._get_effective_public_holiday_values(values)
            if record
            else self._normalize_public_holiday_values(values)
        )
        return self._build_public_holiday_move_plan(effective_values, record=record)

    @api.model_create_multi
    def create(self, vals_list):
        """Normalize public holiday dates before create."""
        normalized_vals_list = [
            self._normalize_public_holiday_same_day(dict(values))
            for values in vals_list
        ]
        return super().create(normalized_vals_list)

    def write(self, vals):
        """Normalize public holiday dates before write."""
        if len(self) == 1:
            vals = self._normalize_public_holiday_same_day(dict(vals), record=self)
        return super().write(vals)
