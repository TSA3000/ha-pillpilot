# v0.2.12

> Catalog schema v2 — per-medicine variants. Drop-in upgrade from 0.2.11.

## What's new

The bundled `medicines_se.json` ships in schema v2. Each medicine now carries a `variants` array — one entry per distinct strength/form combo. Concerta resolves to four variants (18/27/36/54 mg Depottablett), Trimbow to three combo strengths, Eliquis to six. 7331 medicines, 14477 variants.

When you pick a known medicine in the Add/Edit modal, a new read-only **Available strengths (from catalog)** section appears between the codes and prescriptions. It lists every variant as a chip: `5 mg — Filmdragerad tablett`, `10 mg — Filmdragerad tablett`, etc. The form itself is unchanged — strength is still free-text in this release.

## What's not changed yet

This release is the data plumbing only. The strength input is still a free-text number with the legacy mg unit. The variant-driven dropdown that replaces it lands in v0.2.13 along with the prescription-level data model migration.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. Existing prescriptions are unaffected; the loader back-derives `npl_id` and `common_forms` from the new variants for any code path still reading the legacy fields.

Stored medicine caches written by v0.2.11 (schema v1) auto-upgrade on first load — `_bundled_has_content_drift` now samples the variants field and force-loads the v2 bundle even though `list_version` stayed at `2026.05.10-1`.
