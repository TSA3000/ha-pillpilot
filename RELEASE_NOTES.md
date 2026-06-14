# v0.2.21

Fix: prescriptions with an end date.

## Changes

- A prescription with an end date but no start date scheduled only a single dose, on the end date. It now schedules doses across the full range — from the start date (today when none is set) up to and including the end date. Daily, weekly, monthly, and interval schedules are all corrected.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. No data migration.
