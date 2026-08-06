# v0.3.3

Log a past dose.

## Changes

- New "Log a dose…" item in each list row's menu. Opens a dialog with a date and time picker (defaulting to now, future times rejected) and records the dose as taken at that moment. The record binds to the schedule slot closest to the picked time, so a weekly injection logged a few days late lands on the right day, not today.
- The `mark_taken` service's `when` field now accepts naive datetimes, treated as local time. Usable from Developer Tools: `pillpilot.mark_taken` with `medicine_id` and `when: "2026-08-02 17:00:00"`.

## Upgrading

Update through HACS (or replace the `pillpilot` directory in `custom_components/` with the contents of this zip) and restart Home Assistant. Hard-refresh the browser to pick up the new panel.
