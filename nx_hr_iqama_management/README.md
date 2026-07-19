# NX HR Residency and Visa Management

This module manages the full residency and visa request lifecycle for Odoo HR.

## Features

- Residency and visa type configuration by country and duration
- Auto-generated request numbers by country and year
- Workflow with new, under review, under processing, active, cancelled, rejected, and expired statuses
- Required documents loaded automatically from the selected residency/visa type
- Fees, timeline, travel request integration, and family members
- Expiry reminder cron and automatic expiry status update
- Employee smart button and residency/visa history on the employee form
- Arabic translation support in `i18n/ar.po`

## Configuration

Go to:

- `HR > Iqama Management > Configuration > Notification Settings`

Set the number of days before expiry to trigger reminders.
