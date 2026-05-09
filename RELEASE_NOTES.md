# v0.2.2

> UX bugfix release. Drop-in upgrade from 0.2.1.

## What's fixed

- Prescriptions with no dose times — empty in simple mode, or per-weekday mode with all rows blank — now fail validation with a clear error. Previously they saved silently and never fired reminders.
- The Add medicine / Edit medicine modal and its prescription sub-modal close on Escape. Suppressed during save so an in-flight request can't be dismissed.
- The modal backdrop is no longer clickable while a save is in progress, matching the already-disabled Cancel and X buttons.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.
