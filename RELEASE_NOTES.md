# v0.2.0-beta3.6

> Panel UX cleanup. Install over the top — no data migration, prescriptions keep their existing settings.

## What changed

The "Days of week" picker that appears when frequency is set to "Weekly" replaces seven checkboxes with chip buttons and three quick presets:

- **Every day** — selects all seven days.
- **Weekdays** — selects Mon-Fri.
- **Weekends** — selects Sat-Sun.

Below the presets is the chip row: tap a chip to toggle that day in or out. The active preset (if your selection matches one) is highlighted. Picking a custom subset just leaves no preset highlighted — chips still work the same.

Same data underneath as before: a set of weekday indices 0-6. Validator, on-disk format, and the WebSocket payload are unchanged.

If you have prescriptions where Weekly was set with all seven days ticked (functionally identical to Daily), tapping **Weekdays** now reduces it to Mon-Fri in one click — the original motivation for the rework.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. Hard-refresh the browser (Ctrl+Shift+R) so the new `panel.js` loads instead of the cached copy.
