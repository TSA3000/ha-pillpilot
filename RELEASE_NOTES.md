# v0.2.0

> Stable promotion of the 0.2.0 beta cycle. Install over the top from any 0.1.x or 0.2.0-beta version — prescriptions migrate automatically.

## Headline changes since v0.1.5

### Scheduler

- **Every N days** frequency. Pick any interval 2–365 (every other day, every third day, etc). Survives month boundaries — every-other-day starting May 30 fires May 30, Jun 1, Jun 3, not "May 30 then resets to Jun 1, Jun 3."
- **End date** field, optional, available for any frequency. Useful for antibiotic courses or any time-limited prescription.
- **Different times per weekday.** Each prescription can specify its own times for each weekday — e.g. Mon-Fri 08:00, Sat-Sun 10:00. Empty rows mean skip that weekday.
- The underlying engine swapped to RRULE-backed storage. Existing prescriptions are migrated on first start; the migration is idempotent.

### Form UX

The Add medicine / Reconfigure medicine form (HA Settings → Devices & services → PillPilot) is reorganized into four collapsible sections:

- **Identity** (expanded) — name, type, dose, strength, notes, person.
- **Drug-database identifiers** (collapsed) — varunummer, NPL ID, ATC code.
- **Schedule** (expanded) — frequency, times, weekly days, monthly days, every-N-days interval, end date.
- **Per-weekday time overrides** (collapsed) — Mon-Sun rows for advanced schedules.

Plus a reminder-window field at the bottom.

The panel's prescription editor (sidebar → click a medicine → Edit) gets two UX upgrades:

- A **Times mode** radio — Same times every day vs Different times per weekday — that swaps which input is shown. Switching is lossless within an edit session.
- A **Days of week** chip selector with **Every day** / **Weekdays** / **Weekends** preset buttons. Tap a preset to overwrite the selection in one click; tap individual chips to fine-tune.

See [USER_MANUAL.md](USER_MANUAL.md) for the full walkthrough of both surfaces.

### Validation

Validation tightened across the new schedule shapes — Weekly without days surfaces `days_required`, every-N-days requires an interval 2–365, end-date requires `YYYY-MM-DD` format, per-weekday times are validated as 7 × comma-separated HH:MM lists.

### Internal

- New CI check walks the AST of core modules and fails if any function body references an unimported name. Catches the class of bug that produced the 0.2.0-beta3 startup crash before it ships again.
- The flow handler's section-input flattening keeps the validator's API independent of the HA Settings form layout — a future move to a multi-step config flow uses the same flat-shape contract.
- Panel lifecycle log statements are gated behind a `pillpilot_debug` localStorage flag (default off). Enable with `localStorage.setItem("pillpilot_debug", "1")` and reload to get verbose console output for troubleshooting.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally — the 0.2.0 release will appear when you update PillPilot.

If you're on a 0.2.0-beta installed from the beta channel and want to switch back to stable-only updates, untick "Show beta versions" in HACS after this release.

If the panel UI looks unchanged after the upgrade, hard-refresh your browser (Ctrl+Shift+R / Cmd+Shift+R) — HA bundles `panel.js` into the frontend cache.

## Compatibility

- Requires Home Assistant **2024.6.0** or newer (for the section schema construct used in the HA Settings form).
- Existing prescriptions from any 0.1.x or 0.2.0-beta version are migrated automatically. The migration is idempotent — re-running is a no-op.
- Migration helpers stay in place through the 0.x line; they will be removed at v1.0.0.
