# v0.2.13

> Variant-driven strength selector. Drop-in upgrade from 0.2.12.

## What's new

Strength is no longer a free-text mg number — it's a catalog variant. When you Add or Edit a prescription for a medicine that's in `medicines_se.json`, the Strength field is a dropdown of every variant Läkemedelsverket has: `5 mg — Filmdragerad tablett`, `10 mg — Filmdragerad tablett`, etc. Pick one. The form, NPL ID and the rendered dose string all populate from your choice.

Off-catalog medicines (or values that aren't in the catalog) get two free-text fields instead: Strength (any string, e.g. `0,15 mg` or `100 IU`) and Form (e.g. `tablet`). Pick **Custom…** at the bottom of the dropdown to switch modes.

The dose-display string follows: `1 pill × 5 mg Filmdragerad tablett = 5 mg`, `1 puff × 87 mikrogram/5 mikrogram/9 mikrogram Inhalationsspray`, `10 units × 100 E/ml Injektionsvätska`. The `= total mg` suffix only appears when the strength is a simple `<number> mg` — combos, concentrations, IUs etc. don't have a meaningful total to compute.

## Migration

Every existing prescription auto-migrates at integration setup. The legacy `unit_strength_mg: 5.0` becomes `variant_strength: "5 mg"` with empty form and NPL ID. Open Edit on any medicine and the dropdown shows `"5 mg (current)"` pre-selected — Save without changes preserves the value. Pick a real catalog variant from the dropdown to attach a form.

`unit_strength_mg` stays on disk for this release as a downgrade safety net — anyone pausing the upgrade and rolling back to v0.2.12 reads the legacy value cleanly. It'll be removed at v1.0.0.

`total_dose_mg` sensor attribute is now computed live — it stays populated for any mg-parseable variant (all migrated data + any mg variant you pick from the catalog) and becomes `unknown` for combo / IU / mL / % variants where the math doesn't apply.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. The migration runs once at setup; the log line to look for is `Migrated N medicine subentry/subentries to v0.2.13 variants`.
