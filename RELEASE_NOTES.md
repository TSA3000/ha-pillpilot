# v0.1.5

First stable release of the 0.1.x line. Matches v0.1.5-beta6 unchanged. If you've been on the beta channel, no action needed. If you're upgrading from v0.1.0, here's what changed.

## Validation now catches bad input cleanly

The Add/Edit medicine modal previously had cases where unusual input could either crash the WebSocket handler or silently accept things it shouldn't. All fixed:

- Days-of-month, weekdays, and times all get format- and range-checked. Bad input shows a clear error in the modal banner instead of silently breaking.
- Time strings are normalized — `9:00` and `09:00` are both accepted and stored as `09:00`.
- Frequency must be daily, weekly, or monthly.
- Two prescriptions can't share an id (would have caused silent data loss when saving).
- ATC code, NPL ID, and Varunummer are trimmed before storage, so `Levaxin ` and `Levaxin` no longer become two duplicate medicines.

## UX

- Reminder-window field in both forms (HA Settings and the in-panel sub-modal) is now a paired slider + editable number, range 5–240 minutes step 5. Drag the slider for quick adjustment or tap the number to type a precise value.
- Gear button next to **+ Add medicine** opens the integration config directly.
- The prescription summary in the Add/Edit modal now uses the right unit (drop / injection / pill) instead of always saying "pill".

## Under the hood

- Drug-identity edits (changing the medicine type, or editing ATC code) now correctly trigger a panel refresh.
- Type strings (`pill`, `drops`, `injection`) consolidated into shared constants.
- Removed several pieces of dead code and pre-canonical migration helpers.

## Known issues

See the README's [Known issues](https://github.com/TSA3000/ha-pillpilot#known-issues) section for the current list.

## Upgrading

Upgrade via HACS as usual. No data migration needed — all storage shapes are unchanged from 0.1.0.

# v0.1.5-beta6

> Pre-release. HACS users on the stable channel won't see this update — only those with "show beta versions" enabled.

Validation hardening across both forms (HA Settings reconfigure + in-panel modal). Mostly defensive — the existing UI already constrained input — but the validator now rejects malformed data consistently regardless of where it came from.

## Fixes

- **Frequency must be daily, weekly, or monthly.** Other values (typos, hostile WS input) are rejected with a friendly error.
- **Weekday list is range-checked.** Values outside 0–6 (Monday=0 through Sunday=6) no longer slip through.
- **Time strings are validated against HH:MM and normalized.** `9:00` is accepted but stored as `09:00`. Out-of-range hours like `25:00` and minutes like `07:60` are rejected.
- **ATC code, NPL ID, and Varunummer are trimmed.** Leading/trailing whitespace is stripped before save, so `"Levaxin "` and `"Levaxin"` are treated as the same medicine. Whitespace-only values collapse to empty.
- **Panel re-renders correctly when you change drug type or ATC code.** Previously those edits could be missed by the change-detection signature; now they always trigger a refresh.

## Internal

- Added `_normalize_times` and `_strip_or_none` helpers shared by both validators — first step toward removing the longstanding validator duplication. Translations for the new error keys (`frequency_invalid`, `days_range`, `times_invalid`) added for English and Swedish.

# v0.1.5-beta5

> Pre-release. HACS users on the stable channel won't see this update — only those with "show beta versions" enabled.

Brings the panel and HA Settings forms into sync.

## UX

- **Reminder-window field is now consistent across both forms.** The panel's prescription sub-modal previously had a plain number input while HA Settings (after beta2) had a slider with a linked editable number. The panel now matches: paired slider + number, both synced. Drag the slider for quick adjustment, tap the number to type a precise value. Range 5–240 minutes, step 5.

## Internal

- Single-prescription validator now wraps the `days` list parse in try/except, surfacing `days_invalid` on malformed input instead of crashing. Same hardening as the multi-prescription validator got in beta3. In normal HA Settings usage the form's selector pre-validates, so the crash surface was narrow, but defensive consistency matters.

# v0.1.5-beta4

> Pre-release. HACS users on the stable channel won't see this update — only those with "show beta versions" enabled.

Validator hardening and a small dead-code cleanup.

## Fixes

- **Duplicate prescription ids no longer cause silent data loss.** If the panel ever sends two prescriptions with the same id (whether through a panel bug or hostile WS input), the validator now flags both offending rows in the modal banner with a clear "Each prescription must have a unique id" message. Previously the merge would silently let the second overwrite the first.
- **Removed a dead `form_ids_seen` set.** Was populated in two branches of `merge_v2_prescriptions_into_existing` but never read. Pure dead code from an earlier iteration. Cleanup, not behavior change.

# v0.1.5-beta3

> Pre-release. HACS users on the stable channel won't see this update — only those with "show beta versions" enabled.

Hardens the multi-prescription validator against malformed list inputs.

## Fixes

- **No more crashes on bad list input.** Previously, sending `days_of_month: ["abc"]` or `days: ["Mon", "Tue"]` from the WS client (or any future bug in the panel's draft serializer) caused an unhandled `ValueError` in the WS handler. The validator now catches both `ValueError` and `TypeError` on the list-branch parsing for both fields and surfaces a friendly error in the modal banner. Also handles `None` and other non-numeric junk gracefully.
- **New error key:** `days_invalid` for the weekday-list parsing path. Translations added for English and Swedish.

# v0.1.5-beta2

> Pre-release. HACS users on the stable channel won't see this update — only those with "show beta versions" enabled.

Two small UX additions on top of beta1.

## New

- **⚙ Configure-integration button** in the panel header, sitting next to "+ Add medicine". One tap takes you to HA Settings → Devices & Services → PillPilot. Useful as a shortcut to the parent reconfigure form (panel visibility, medicines DB URL) without navigating through the side menu.

## UX

- **Missed-after-minutes is now a proper slider with a linked number input.** Drag the slider for quick adjustment, or tap the number to type a precise value — both stay in sync. Range 5–240 minutes, step 5. Mobile-friendly drag target with tap-to-enter fallback for narrow screens.

# v0.1.5-beta1

> Pre-release. HACS users on the stable channel won't see this update — only those with "show beta versions" enabled. Open the integration in HACS → three dots → Redownload → enable beta to install.

Internal cleanup. One small visible change: prescription summary in the Add/Edit modal now shows the right unit (drop / drops, injection / injections) instead of always saying "pill".

## Fixes

- **Prescription summary in the Edit/Add modal now shows the right unit.** Previously every prescription said `"1 pill × N mg"` regardless of medicine type because the unit-label check read `p.frequency` (which is daily/weekly/monthly) instead of the drug's type. Drops show `"drop"` / `"drops"`, injections show `"injection"` / `"injections"`.

## Internal

- Medicine-type strings are now constants (`MED_TYPE_PILL/DROPS/INJECTION`) in both `const.py` and `panel.js`. Wire format unchanged.
- Removed `_retitle_medicine_subentries`, a pre-existing migration helper that was a no-op on canonical 0.1.0+ data.
- Removed a defensive id-presence filter in `merge_v2_prescriptions_into_existing` that's no longer load-bearing now that every stored prescription has an id.
- Cleaned up 37 mechanical version-history annotations in code comments.

# v0.1.4

## Fixes

- **Delete medicine now actually deletes.** v0.1.3's call to `async_remove_subentry` used the wrong calling convention (passed the subentry object + awaited a non-coroutine); now passes `subentry_id` and treats it as the synchronous callback it is, matching how `async_update_subentry` is already called elsewhere in the integration.
- **Modal error banner now shows the underlying exception.** When a backend WS call fails (delete, save, create), the actual exception type and message are surfaced under the friendly error text so failures don't require digging through HA logs.

# v0.1.3

Adds an in-panel Delete button to the Edit medicine modal, so removing a medicine no longer requires going to HA Settings → Integrations → PillPilot.

## New

- **Delete medicine** button in the Edit modal footer (left side, danger-styled). Confirms before deleting. Removes the subentry, the sensor entity, and any per-medicine device.

# v0.1.2

## Fixes

- **Add medicine in the panel no longer fails with "Couldn't reach Home Assistant"**. The `ConfigSubentry` constructor in current Home Assistant versions requires `unique_id` (no default), even when the value is `None`; v0.1.1 dropped that argument as part of the canonical-id cleanup.

# v0.1.1

Bug fixes for the in-panel Add and Edit modals.

## Fixes

- **Edit medicine no longer fails with "This medicine no longer exists".** The medicine identity is now exclusively the subentry id that Home Assistant assigns. The previous code stamped a separate uuid into subentry data on create and looked up by that, which silently mismatched the id the panel exposes.
- **Drug-name autocomplete in the Add and Edit modals** now suggests entries from the bundled Swedish medicine list (and your existing medicines), with alias matching for common misspellings. Picking a known entry auto-fills ATC code and active substance into the notes field.

# v0.1.0

Initial release. Take an HA backup before installing.

## Features

- Custom side panel showing what's due, what's been taken today, and per-person dose history
- Per-medicine sensor with state (`due` / `upcoming` / `taken` / `missed` / `skipped`) and full attributes
- **Multi-prescription medicines**: one medicine can have multiple prescriptions on it — different person, dose, and schedule per prescription. Each prescription appears as its own card in the panel under the assigned person's section
- **In-panel Add and Edit**: add or modify medicines directly from the panel without leaving for HA Settings. Add multiple prescriptions in one go
- Schedules: daily, weekly (specific weekdays), monthly (specific dates)
- Multiple times per day per prescription
- Assign each prescription to a person (or leave unassigned for household-wide)
- Configurable reminder window per prescription (default 60 min before "missed")
- Mark taken / skip / snooze / undo actions, both from the panel and via services
- Per-person bulk actions in the panel ("Take all", "Undo last")
- HA event triggers for automations: `pillpilot_dose_due`, `pillpilot_dose_missed`, `pillpilot_dose_taken`, `pillpilot_dose_skipped`, `pillpilot_dose_unmarked`
- Two automation blueprints bundled (notify_dose, handle_actions)
- Bundled Swedish medicine list with searchable dropdown (fuzzy match on aliases)
- Hot-reloadable medicine list — refresh without restarting HA
- Per-medicine identifiers (varunummer, NPL ID, ATC code) auto-filled from the bundled list
- Custom services: `mark_taken`, `skip`, `snooze`, `unmark_taken`, `refresh_medicines_database`
- HACS-installable

## Install

Manual: copy `custom_components/pillpilot/` into `<config>/custom_components/pillpilot/`, restart HA, add the integration from Settings → Devices & services.

HACS: add the repo as a custom Integration repository, install, restart, add the integration.
