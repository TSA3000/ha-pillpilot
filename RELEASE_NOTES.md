# v0.2.0-beta3.2

> Hotfix for beta3.1. Cosmetic-only change to the HA Settings form labels — install over the top, no data migration, prescriptions keep their existing settings.

## What changed

**Fixed: raw field keys showing in the HA Settings → Reconfigure medicine form.** The new beta3 fields (interval, end date, the seven per-weekday `times_*` rows) were rendering as `interval_days`, `ends_on`, `times_mon`, `times_tue` … because the labels weren't added to `strings.json` or the translation files. Now they show as:

- "Interval in days (Every-N-days only, 2–365)"
- "End date (optional, YYYY-MM-DD)"
- "Mon — times (leave blank to use 'Times of day')" through "Sun — times …"

Swedish localization ships with the same.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update the integration normally — the 0.2.0-beta3.2 tag will appear under "Beta versions enabled."

If you see the old raw labels after upgrading, hard-refresh the browser (Ctrl+Shift+R) — HA bundles translations into the frontend cache and a soft refresh sometimes keeps the old copy.
