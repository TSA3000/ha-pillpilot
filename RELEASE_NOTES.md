# v0.1.0

Initial release. Take an HA backup before installing.

## Features

- Custom side panel showing what's due, what's been taken today, and per-person dose history
- Per-medicine sensor with state (`due` / `upcoming` / `taken` / `missed` / `skipped`) and full attributes
- **Multi-prescription medicines**: one medicine can have multiple prescriptions on it — different person, dose, and schedule per prescription. Each prescription appears as its own card in the panel under the assigned person's section
- **In-panel Add and Edit**: add or modify medicines directly from the panel without leaving for HA Settings. Add multiple prescriptions in one go
- Schedules: daily, weekly (specific weekdays), monthly (specific dates)
- Multiple times per day per prescription
- Assign each prescription to a person (or leave unassigned for household-wide)
- Configurable reminder window per prescription (default 60 min before "missed")
- Mark taken / skip / snooze / undo actions, both from the panel and via services
- Per-person bulk actions in the panel ("Take all", "Undo last")
- HA event triggers for automations: `pillpilot_dose_due`, `pillpilot_dose_missed`, `pillpilot_dose_taken`, `pillpilot_dose_skipped`, `pillpilot_dose_unmarked`
- Two automation blueprints bundled (notify_dose, handle_actions)
- Bundled Swedish medicine list with searchable dropdown (fuzzy match on aliases)
- Hot-reloadable medicine list — refresh without restarting HA
- Per-medicine identifiers (varunummer, NPL ID, ATC code) auto-filled from the bundled list
- Custom services: `mark_taken`, `skip`, `snooze`, `unmark_taken`, `refresh_medicines_database`
- HACS-installable

## Install

Manual: copy `custom_components/pillpilot/` into `<config>/custom_components/pillpilot/`, restart HA, add the integration from Settings → Devices & services.

HACS: add the repo as a custom Integration repository, install, restart, add the integration.
