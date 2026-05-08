# Changelog

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
