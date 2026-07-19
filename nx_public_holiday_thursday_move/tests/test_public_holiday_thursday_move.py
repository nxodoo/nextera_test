from odoo.tests.common import SavepointCase


class TestPublicHolidayThursdayMove(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Sunday to Thursday",
                "tz": "Asia/Riyadh",
                "attendance_ids": [
                    (0, 0, {"name": "Sunday", "dayofweek": "6", "hour_from": 8, "hour_to": 17}),
                    (0, 0, {"name": "Monday", "dayofweek": "0", "hour_from": 8, "hour_to": 17}),
                    (0, 0, {"name": "Tuesday", "dayofweek": "1", "hour_from": 8, "hour_to": 17}),
                    (0, 0, {"name": "Wednesday", "dayofweek": "2", "hour_from": 8, "hour_to": 17}),
                    (0, 0, {"name": "Thursday", "dayofweek": "3", "hour_from": 8, "hour_to": 17}),
                ],
            }
        )
        cls.no_thursday_calendar = cls.env["resource.calendar"].create(
            {
                "name": "Sunday to Wednesday",
                "tz": "Asia/Riyadh",
                "attendance_ids": [
                    (0, 0, {"name": "Sunday", "dayofweek": "6", "hour_from": 8, "hour_to": 17}),
                    (0, 0, {"name": "Monday", "dayofweek": "0", "hour_from": 8, "hour_to": 17}),
                    (0, 0, {"name": "Tuesday", "dayofweek": "1", "hour_from": 8, "hour_to": 17}),
                    (0, 0, {"name": "Wednesday", "dayofweek": "2", "hour_from": 8, "hour_to": 17}),
                ],
            }
        )
        cls.company = cls.env.company
        cls.resource_leave_model = cls.env["resource.calendar.leaves"]

    def test_prompt_is_returned_for_midweek_public_holiday(self):
        move_data = self.resource_leave_model.get_public_holiday_thursday_move_data(
            {
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-21 06:00:00",
                "date_to": "2026-07-21 15:00:00",
            }
        )

        self.assertTrue(move_data["should_prompt"])
        self.assertEqual(move_data["target_date_from"], "2026-07-23 06:00:00")
        self.assertEqual(move_data["target_date_to"], "2026-07-23 15:00:00")

    def test_prompt_is_returned_for_sunday_public_holiday(self):
        move_data = self.resource_leave_model.get_public_holiday_thursday_move_data(
            {
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-19 06:00:00",
                "date_to": "2026-07-19 15:00:00",
            }
        )

        self.assertTrue(move_data["should_prompt"])
        self.assertEqual(move_data["target_date_from"], "2026-07-23 06:00:00")
        self.assertEqual(move_data["target_date_to"], "2026-07-23 15:00:00")

    def test_prompt_works_when_date_to_is_missing(self):
        move_data = self.resource_leave_model.get_public_holiday_thursday_move_data(
            {
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-20 06:00:00",
            }
        )

        self.assertTrue(move_data["should_prompt"])
        self.assertEqual(move_data["target_date_from"], "2026-07-23 06:00:00")

    def test_create_normalizes_public_holiday_end_date_to_same_day(self):
        public_holiday = self.resource_leave_model.create(
            {
                "name": "One Day Holiday",
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-05-17 07:00:00",
                "date_to": "2026-05-31 00:59:59",
            }
        )

        self.assertEqual(public_holiday.date_from.date(), public_holiday.date_to.date())

    def test_write_normalizes_public_holiday_end_date_to_same_day(self):
        public_holiday = self.resource_leave_model.create(
            {
                "name": "Editable Holiday",
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-05-17 07:00:00",
                "date_to": "2026-05-17 19:00:00",
            }
        )

        public_holiday.write({"date_to": "2026-05-31 00:59:59"})

        self.assertEqual(public_holiday.date_from.date(), public_holiday.date_to.date())

    def test_prompt_is_skipped_when_thursday_is_not_working_day(self):
        move_data = self.resource_leave_model.get_public_holiday_thursday_move_data(
            {
                "calendar_id": self.no_thursday_calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-21 06:00:00",
                "date_to": "2026-07-21 15:00:00",
            }
        )

        self.assertFalse(move_data["should_prompt"])

    def test_prompt_is_skipped_when_target_thursday_already_has_public_holiday(self):
        self.resource_leave_model.create(
            {
                "name": "Existing Thursday Holiday",
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-23 06:00:00",
                "date_to": "2026-07-23 15:00:00",
            }
        )

        move_data = self.resource_leave_model.get_public_holiday_thursday_move_data(
            {
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-21 06:00:00",
                "date_to": "2026-07-21 15:00:00",
            }
        )

        self.assertFalse(move_data["should_prompt"])

    def test_prompt_is_skipped_for_weekend_public_holiday(self):
        move_data = self.resource_leave_model.get_public_holiday_thursday_move_data(
            {
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-24 06:00:00",
                "date_to": "2026-07-24 15:00:00",
            }
        )

        self.assertFalse(move_data["should_prompt"])

    def test_prompt_is_skipped_when_public_holiday_is_already_on_thursday(self):
        move_data = self.resource_leave_model.get_public_holiday_thursday_move_data(
            {
                "calendar_id": self.calendar.id,
                "company_id": self.company.id,
                "date_from": "2026-07-23 06:00:00",
                "date_to": "2026-07-23 15:00:00",
            }
        )

        self.assertFalse(move_data["should_prompt"])
