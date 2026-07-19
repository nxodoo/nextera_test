# HR Position Based Org Chart

This module changes the HR organizational chart source from employee manager relationships to the official job position hierarchy.

## Main Features

- Adds `Parent Position`, `Direct Sub Positions`, `Position Level`, `Headcount`, and computed filled/vacant status to Job Positions.
- Adds configurable Position Levels, including a dedicated Assistant level for side-branch assistant roles.
- Adds a position-based Org Chart client action with department and level filters.
- Keeps vacant positions visible in the chart when enabled.
- Synchronizes employee assignment through the standard `hr.employee.job_id` relation.
- Prevents quick creation of Job Positions from Employee and Recruitment forms.
- Adds `Application Deadline` and recruitment statuses to Job Positions.
- Blocks new applications for expired, closed, cancelled, or draft job postings.
- Adds a daily cron to mark open or active postings as expired after their application deadline.

## Usage

Create and maintain positions from:

`Employees > Configuration > Job Positions`

Rename or reorder organization levels from:

`Employees > Configuration > Position Levels`

Open the position-based chart from:

`Employees > Org Chart`

## Notes

Assistant positions are displayed beside the main reporting line and are not validated as normal child levels.

The module extends standard Odoo HR, HR Org Chart, and Recruitment modules. It does not replace the base models and keeps the existing employee/job assignment mechanism.
