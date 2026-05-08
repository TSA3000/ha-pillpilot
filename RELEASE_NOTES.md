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

Internal cleanup. No user-visible behavior change except #5.

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
