# v0.2.0-beta3.4

> Form UX rework. Install over the top — no data migration, prescriptions keep their existing settings.

## What changed

The Add medicine / Reconfigure medicine form is now organized into collapsible sections instead of one ~22-field stack:

- **Identity** (expanded) — name, type, per-dose count, strength, notes, person.
- **Drug-database identifiers** (collapsed) — varunummer, NPL ID, ATC code. Auto-filled when you pick a medicine from the dropdown.
- **Schedule** (expanded) — frequency, times, weekly days, monthly days, every-N-days interval, end date. Field labels include "(Weekly only)" / "(Monthly only)" / "(Every-N-days only)" markers so it's clear which apply.
- **Per-weekday time overrides** (collapsed) — Mon-Sun rows for schedules like "Mon-Fri 08:00, Sat-Sun 10:00."

Reminder window stays as a single field below the sections.

Uses Home Assistant's native `section()` schema construct. Requires Home Assistant 2024.5 or newer.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.

If section names show as `identity_section` / `schedule_section` instead of "Identity" / "Schedule," hard-refresh the browser (Ctrl+Shift+R) to clear cached translations.
