# v0.2.10

> Two fixes from v0.2.9 testing. Drop-in upgrade from 0.2.9.

## What's fixed

**Bundled medicines list wins when newer.** Pre-v0.2.10 the stored copy in `.storage/pillpilot.medicines_se` always won over the integration's bundled file. So if you'd ever clicked **Refresh medicine list now** in an earlier release, you stayed stuck on that cached list across HACS upgrades — the v0.2.9 jump from 216 to 7331 entries was invisible until you manually refreshed again. `MedicineDatabase.async_load` now compares `list_version` on the two and picks the newer one. Explicit URL refreshes ahead of the bundle still take precedence.

**NPL ID auto-fills from the catalog.** When you pick a known medicine in the panel's Add/Edit modal, the NPL ID field now populates from the Läkemedelsverket export, the same way ATC code and active substance already do. Three spots that all had to be in sync: `_normalize_entry` preserves the field on load, `sanitize_for_ws` forwards it to the panel, and `_applyDrugNameAutoFill` writes it into the draft. Anything you typed yourself isn't overwritten.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.

Anyone on the v0.2.9 bundled list (`2026.05.10-1`) and a stored copy from before will be flipped to the bundled list on first load after this upgrade. Existing medicines configured before the upgrade are unaffected.
