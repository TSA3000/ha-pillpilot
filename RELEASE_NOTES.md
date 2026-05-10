# v0.2.11

> Catalog auto-fill cleanup. Drop-in upgrade from 0.2.10.

## What's fixed

**NPL ID now auto-fills in the HA Settings reconfigure flow.** The v0.2.10 fix only covered the panel's Add/Edit modal — when you reconfigured a medicine from **Settings → Devices & services → PillPilot**, the NPL ID field stayed empty even when the catalog had a match. Mirrors the existing ATC code auto-fill logic in both single-prescription and multi-prescription paths.

**Bundled list reload also triggers on content drift, not just version diff.** v0.2.10 added `npl_id` per entry without bumping `list_version`, so on upgrade `async_load` saw equal versions and stuck with the stored cache (which v0.2.9's normalizer had stripped of `npl_id`). The fix samples up to 500 entries from each side: if bundled has a field populated on more than 25% of entries while stored has it on less than 5%, that's a schema upgrade — bundled wins.

## What's new

**`pillpilot.backfill_from_catalog` service.** Catches up medicines configured before catalog auto-fill landed. One call walks every medicine you've added, looks each up by name in the catalog, and fills in any empty NPL ID and ATC code from the match. Anything you've typed yourself is preserved.

Trigger it from the panel: the header now has a `⋮` menu next to the gear with a **Backfill empty fields from catalog** item. A toast confirms completion. Or call `pillpilot.backfill_from_catalog` from **Developer Tools → Actions** if you prefer. Either way, the log shows the count: `backfill_from_catalog: filled N medicine(s), skipped M`.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. Existing medicines are unaffected — backfill is opt-in via the new service.
