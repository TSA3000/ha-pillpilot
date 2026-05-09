# v0.2.5

> Bugfix release. Drop-in upgrade from 0.2.4.

## What's fixed

Every field inside a section in the medicine reconfigure form (Identity, Identifiers, Schedule, Per-weekday) was rendering with its raw constant name — `days_of_month`, `interval_days`, `starts_on`, `ends_on`, `name`, `varunummer`, `times_mon`, and so on — instead of the human-readable label.

The cause was a translation-key nesting issue: the labels lived at the form's step level, but HA looks them up under each section's `data` slot when the field is wrapped in a `section()`. Restructured the three translation files (`strings.json`, `en.json`, `sv.json`) to put each section's field labels in the right place.

This bug pre-dates v0.2.4 — it's been latent in every version that used the sectioned form, but became impossible to ignore once `starts_on` was added in v0.2.4.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.
