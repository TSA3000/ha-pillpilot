# v0.2.17

Take missed promoted to a top-level button.

## Changes

The per-person header now has three visible bulk-action buttons instead of two: **Take all**, **Take due**, **Take missed**. The kebab `⋮` menu drops to three items (snooze all due, snooze all missed, undo last action).

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS: update normally. Hard-reload the panel (Ctrl+Shift+R).
