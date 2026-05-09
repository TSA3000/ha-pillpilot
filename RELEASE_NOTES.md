# v0.2.0-beta3.5

> Panel UX cleanup. Install over the top — no data migration, prescriptions keep their existing settings.

## What changed

The panel's prescription form replaces the "Different times per day of week" checkbox with a radio pair:

- **Same times every day** — shows a single "Times of day" field. (Today's default.)
- **Different times per weekday** — shows seven Mon-Sun rows; leave a row blank to skip that weekday.

Only one input is visible at a time. The old layout kept "Times of day" visible while the per-weekday rows were also showing, with a paragraph of help text trying to explain which one took precedence. Mode picker removes the ambiguity.

Switching between modes is lossless within an edit session — both the single-field value and the seven per-weekday entries stay in the draft regardless of which mode is active, so flipping back and forth does not destroy what you typed. On save, only the active mode's data persists.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. Hard-refresh the browser (Ctrl+Shift+R) so the new `panel.js` loads instead of the cached copy.
