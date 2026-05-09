# Changelog

## [0.2.0-beta3.1] — 2026-05-09

Hotfix for beta3.

- Fix: `NameError` on coordinator startup when any prescription used interval mode. `SCHEDULE_TYPE_INTERVAL` was referenced in the prescription-state builder but never imported. Added the missing import; existing prescriptions continue to work without changes.
- Tests: added a static name-resolution check across the core modules (coordinator, config_flow, schedule, sensor) so this class of "function-body references a constant that isn't imported at module top" bug fails CI before shipping rather than at user runtime.

## [0.2.0-beta3] — 2026-05-09

Adds three schedule shapes the old engine couldn't express. UI lives in the prescription Add/Edit modal.

- New: **Every N days** mode. Pick "Every N days" in the Frequency dropdown, set the interval (2 or more). Rhythm survives month boundaries — every-other-day starting May 30 fires May 30, Jun 1, Jun 3, etc., not "May 30, then resets to Jun 1, Jun 3".
- New: **End date** field. Optional, available for any frequency. Useful for antibiotic courses ("daily for 7 days") or any time-limited prescription.
- New: **Different times per day of week**. Optional toggle in the prescription form. When enabled, replaces the single "Times of day" field with seven per-weekday rows (Mon … Sun). Set Mon-Fri to `08:00` and Sat-Sun to `10:00` for a "later on weekends" rhythm in one prescription instead of two. Leave a row blank to skip doses on that weekday entirely.
- Validation: weekly without selected days now surfaces `days_required` (was missed in beta1's hardening). Interval mode requires an interval between 2 and 365.

## [0.2.0-beta2] — 2026-05-09

Fixes a crash in v0.2.0-beta1 that hid the side panel after upgrading from v0.1.5. v0.2.0-beta1 is retracted.

- Fix: `Schedule.next_after` mixed naive and aware datetimes when called with HA's `dt_util.now()` (always aware). Coordinator update raised `TypeError` on first tick. Now walks dates by offset like the v0.1.x scheduler did and grafts `now.tzinfo` onto results.
- Regression test added covering tz-aware input in daily and weekly modes.

## [0.2.0-beta1] — 2026-05-09

First beta of the scheduler rewrite. Engine swapped to an RRULE-backed implementation. Existing prescriptions are migrated on first start. UI unchanged in this beta.

- New: storage holds an `rrule` + `schedule_type` instead of `frequency` / `days` / `days_of_month`. Lets future betas add every-N-days, courses with end dates, and cyclical on/off.
- New: `python-dateutil` declared in manifest requirements.
- Fix: weekly without selected weekdays is rejected with `days_required`. Pre-v0.2.0 it was silently accepted and ran like daily.
- Migration: ran once at setup. Re-run is a no-op.

## [0.1.5] — 2026-05-08

First stable release after the v0.1.0 → v0.1.5 beta cycle. Promotes v0.1.5-beta6 unchanged. Cumulative highlights for users coming from 0.1.0:

- **Validation hardening**: frequency must be `daily` / `weekly` / `monthly`; weekday list range-checked 0–6; time strings format-validated against HH:MM and normalized (`9:00` is accepted, stored as `09:00`); days-of-month list range-checked 1–31; malformed list inputs now surface a friendly error instead of crashing the WS handler.
- **Data integrity**: duplicate prescription ids are detected and rejected. ATC code, NPL ID, and Varunummer fields are trimmed before storage so `"Levaxin "` and `"Levaxin"` aren't treated as separate medicines.
- **UX**: reminder-window field is a paired slider + editable number input in both forms (HA Settings and panel sub-modal). Gear button next to + Add medicine opens the integration config directly. Modal banner shows friendly text for every validation key.
- **Panel rendering**: drug-identity edits (medicine type, ATC code) correctly trigger re-render. Add/Edit modal's prescription summary uses the right unit ("drop" / "injection" / "pill") instead of always saying "pill".
- **Internal**: type strings consolidated into shared constants. Pre-canonical migration helpers removed. Shared validator helpers (`_normalize_times`, `_strip_or_none`) extracted for use by both validators.

(See per-beta entries below for which fix shipped in which prerelease.)

## [0.1.5-beta6] — 2026-05-08

- Fix: Frequency must now be one of `daily`, `weekly`, `monthly` — invalid values are rejected with a friendly error instead of silently accepted.
- Fix: Weekday list is now range-checked. Values outside 0–6 (Mon=0 through Sun=6) are rejected.
- Fix: Time strings must match HH:MM format and are normalized — single-digit hours like `9:00` are accepted and stored as `09:00` for consistency.
- Fix: Optional drug fields (ATC code, NPL ID, Varunummer) are now stripped of leading/trailing whitespace before storage. `"Levaxin "` and `"Levaxin"` no longer appear as duplicate medicines.
- Fix: Panel re-render signature now includes drug-level fields (medicine type, ATC code) — edits to those fields trigger the panel to update without needing a manual refresh.
- New translation keys: `frequency_invalid`, `days_range`, `times_invalid` (en + sv).
- Internal: Added `_normalize_times` and `_strip_or_none` helpers shared by both validators — small step toward removing the validator duplication.

## [0.1.5-beta5] — 2026-05-08

- UX: Reminder-window field in the panel's prescription sub-modal now matches HA Settings — paired slider + editable number input, both synced. Drag the slider for quick adjustment or tap the number to type a precise value.
- Internal: Single-prescription validator hardened against malformed `days` list input — now returns `days_invalid` instead of crashing on non-numeric or `None` entries, matching the multi-prescription validator's behavior.

## [0.1.5-beta4] — 2026-05-08

- Fix: `validate_medicine_input_multi` now detects when two prescriptions in the form share an id and flags both rows with `duplicate_prescription_id`. Previously the merge would silently overwrite one with the other and the user wouldn't know data was lost. Translation key added (en/sv).
- Internal: Removed dead `form_ids_seen` set in `merge_v2_prescriptions_into_existing` — populated but never read.

## [0.1.5-beta3] — 2026-05-08

- Fix: `validate_medicine_input_multi` no longer crashes on malformed `days_of_month` or `days` lists. Hostile or buggy WS input (e.g. `["abc"]`, `["Mon"]`, `[None]`) now surfaces a friendly `days_of_month_invalid` / `days_invalid` error in the modal banner instead of raising an unhandled `ValueError`/`TypeError` in the WS handler. New translation key `days_invalid` (en/sv).

## [0.1.5-beta2] — 2026-05-08

- New: ⚙ button in the panel header next to "+ Add medicine" — opens the integration's config page in HA Settings without leaving the SPA.
- UX: missed-after-minutes setting in the config / reconfigure form now uses HA's slider-with-linked-number-input selector. Mobile-friendly drag target plus a tappable input for precise entry. Range 5–240 min, step 5.

## [0.1.5-beta1] — 2026-05-08

- Fix: prescription summary in the modal now shows the correct unit for drops and injections (was always saying "pill").
- Internal: medicine-type strings consolidated as constants, dead pre-canonical helpers removed, comment cleanup.

## [0.1.4] — 2026-05-07

- Fix: Delete medicine now works — corrected the `async_remove_subentry` call signature.
- Fix: Modal error banner shows the underlying exception detail when a WS call fails.

## [0.1.3] — 2026-05-07

- New: Delete button in the Edit medicine modal — remove a medicine without leaving the panel.

## [0.1.2] — 2026-05-07

- Fix: Add medicine in the panel no longer fails with "Couldn't reach Home Assistant" — pass the required `unique_id=None` to `ConfigSubentry`.

## [0.1.1] — 2026-05-07

- Fix: editing a medicine no longer fails with "This medicine no longer exists". Medicine identity is now the subentry id.
- Fix: drug-name field in the Add and Edit modals autocompletes from the bundled medicine list with alias matching, and auto-fills ATC code + active substance on a known pick.

## [0.1.0] — 2026-05-07

Initial release.
