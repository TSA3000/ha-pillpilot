# v0.2.20

Full panel translation coverage.

## Changes

The translation framework added in v0.2.19 covered the most-visible strings; this release covers the rest of the panel. Now translated in English and Swedish:

- Status badges (due now, upcoming, taken, missed, skipped, snoozed)
- Per-dose buttons (Take, Snooze, Skip) and status labels with timestamps (Taken at, Skipped at, Snoozed until)
- Relative times (never, just now, minutes / hours / days ago)
- Schedule summaries (Daily, Weekly, Monthly, Every N days, weekday abbreviations, from / until)
- Sort dropdown and list column headers
- The per-medicine Visibility section
- Form validation and error messages
- Edit, Delete medicine, and Undo last action

Language follows the setting from v0.2.19: Auto (each user's HA language), English, or Svenska — in Settings → Devices & services → PillPilot → Configure.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. Hard-reload the panel (Ctrl+Shift+R) to pick up the new `panel.js`. No data migration.
