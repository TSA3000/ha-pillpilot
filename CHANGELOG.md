# Changelog

## [0.2.10] — 2026-05-10

Two fixes from v0.2.9 testing. Drop-in upgrade from 0.2.9.

- **Bundled medicines list wins when newer.** `MedicineDatabase.async_load` now compares `list_version` between the integration's bundled file and the user's stored copy; the lexicographically newer one wins (the `YYYY.MM.DD-N` format sorts correctly that way). Pre-v0.2.10, anyone who'd ever clicked **Refresh medicine list now** stayed pinned to that cached list across integration upgrades — the v0.2.9 jump from 216 to 7331 bundled entries was invisible until a manual re-refresh. Explicit URL refreshes ahead of the bundle still win.
- **NPL ID auto-fills from the catalog.** Picking a known medicine in the Add/Edit modal now populates the NPL ID field the same way ATC code and active substance already do. Three spots fixed: `_normalize_entry` preserves `npl_id` on load (was being stripped), `sanitize_for_ws` forwards it to the panel over `pillpilot/get_medicines_db`, and `_applyDrugNameAutoFill` copies it into the draft when empty. User-entered NPL IDs are never overwritten.

## [0.2.9] — 2026-05-10

Medicine list rebuilt from Läkemedelsverket. Drop-in upgrade from 0.2.8.

- **List source switched to Läkemedelsverket's open-data register** ([dataset 140_5467](https://www.dataportal.se/datasets/140_5467) — Sök läkemedelsfakta, distribution `Lakemedelsprodukter.xlsx`). 216 hand-curated entries → 7331. Covers every human medicine currently `Godkänd` or `Registrerad`; veterinary and deregistered products filtered at build time. Snapshot 2026-05-10. Each entry now carries `npl_id`, and `aliases` picks up former product names from the `Tidigare läkemedelsnamn` column.
- **Build tool** at `tools/build_medicines_se.py`. Reads `Lakemedelsprodukter.xlsx` (also csv/tsv/xml/json), groups per-strength rows by name, preserves curated aliases on existing entries, bumps `list_version`. Not shipped in the integration zip.

## [0.2.8] — 2026-05-10

Snooze UX. Drop-in upgrade from 0.2.7.

- **Snooze button on every actionable row.** Due, missed, and upcoming slots now render Take / Snooze / Skip in the panel, matching the mobile notification's button set. Tapping Snooze calls `pillpilot.snooze` with `minutes=15` and the slot's `scheduled_for`.
- **Snooze all due (15m)** and **Snooze all missed (15m)** in the per-person kebab menu. Iterates the matching slots and fires one snooze per slot. Disabled when there's nothing in that bucket.
- **No new bus events or schema changes.** Same `pillpilot.snooze` service, same `pillpilot_dose_snoozed` event, same `DoseRecord` fields. Drop-in upgrade.

## [0.2.7] — 2026-05-10

Snooze fix. Drop-in upgrade from 0.2.6.

- **Snooze actually works.** Tapping Snooze 15m on a notification (or calling `pillpilot.snooze`) used to be a no-op: the integration wrote a junk `DoseRecord` with `scheduled_for = now + 15min`, which never matched any RRULE-derived slot. The original dose stayed `due`, then flipped to `missed`, no follow-up notification ever fired, and the orphan record sat in `.storage` forever. Snooze now writes `snoozed_until` onto the record for the original scheduled slot; the tick re-fires `pillpilot_dose_due` once the snooze elapses, and the bundled `notify_dose` blueprint sends a fresh notification with the same Taken / Snooze / Skip buttons.
- **New `pillpilot_dose_snoozed` event** on the bus. Fires immediately when a snooze is recorded, with `medicine_id`, `scheduled_for`, `snoozed_until`, `minutes`, and `person_id`. Useful for logbook entries and custom automations.
- **New `snoozed` sensor state and per-slot status.** `sensor.<medicine>` reports `snoozed` while any of its prescriptions is in an active snooze window. The panel's `today_doses` array carries `snoozed_until` per slot.
- **`pillpilot_dose_missed` is suppressed for snoozed slots.** The user already engaged via snooze; firing missed on top would be redundant. Slots that are never snoozed still go to missed normally.
- **`pillpilot.snooze` accepts `scheduled_for`.** Lets callers pin the snooze to a specific slot for medicines with multiple times per day. Defaults to the closest scheduled time when omitted.
- **Panel UI.** Snoozed slots show "⏰ Snoozed until HH:MM" inline with Take / Skip buttons, so the user can override the snooze. Section header surfaces the snoozed count between missed and upcoming. Status sort priority: due > missed > snoozed > upcoming > taken > skipped.
- **`DoseRecord` schema:** added `snoozed_until: str | None`. Forward-compatible — existing records load with `snoozed_until=None` and behave exactly as before.
- **Pre-0.2.7 orphan snooze records are harmless.** They wrote a synthetic `scheduled_for` that doesn't match any RRULE-derived slot, so the new lookup in `_today_doses_for` quietly ignores them. Manually purge `.storage/pillpilot.history.<entry>` to clear them if you want a clean slate.

## [0.2.6] — 2026-05-10

Blueprint hotfix. Drop-in upgrade from 0.2.5.

- **`handle_actions` blueprint fixed.** Tapping Taken / Snooze / Skip on a PillPilot notification did nothing — the trace showed `UndefinedError: 'len' is undefined`, the matching `pillpilot.*` service never ran, and the dose stayed unmarked. The mobile_app integration dismisses the notification on action tap whether the automation succeeded or not, hiding the failure. Cause: `action[len('PILL_TAKEN_'):]` used Python's `len()`, which HA's Jinja2 sandbox doesn't expose. Replaced with the `replace` filter (`{{ action | replace('PILL_TAKEN_', '', 1) }}`) in all three branches. No integration code changed. Users need to re-import the blueprint and reload automations after upgrading. Fixes #3.

## [0.2.5] — 2026-05-09

Bugfix release. Drop-in upgrade from 0.2.4.

- **HA Settings form labels.** Every field inside a section in the medicine reconfigure form (Identity, Identifiers, Schedule, Per-weekday) was rendering as its raw constant name — `days_of_month`, `interval_days`, `starts_on`, `ends_on`, `name`, `varunummer`, `times_mon`, etc. — instead of the human-readable label. Cause: the labels lived at `config_subentries.medicine.step.<step>.data.<field>` but HA looks them up under `sections.<section_name>.data.<field>` for fields inside a `section()`. Restructured all three translation files (`strings.json`, `translations/en.json`, `translations/sv.json`) to put each section's field labels in the right slot. Parity held at 178/178/178.

## [0.2.4] — 2026-05-09

Fixes a long-standing bug in interval-mode scheduling and adds a configurable Start date. Drop-in upgrade from 0.2.2.

- **Start date for interval prescriptions.** New optional field on Every-N-days schedules. Set it to a past date when adding a medicine retroactively (e.g. last shot taken 7 days ago for a 14-day cycle) — the next-due math anchors to that date, not to today. Blank means "start today" and stamps today's date at save time so the anchor persists.
- **Anchor now stored persistently.** Pre-0.2.4 the rrule's DTSTART was implicitly `date.today()` at every load. The cycle phase shifted on every HA restart — an "every 14 days" schedule that had been firing on Mondays would silently start firing on Wednesdays after a Wednesday reboot. The anchor is now stored on the prescription and stable across restarts.
- **Existing interval prescriptions migrated automatically.** `_migrate_subentries_to_v024_starts_on` stamps today's date on any pre-0.2.4 interval prescription that lacks `starts_on`. Idempotent. Carries `# REMOVE AT v1.0.0` markers (one in the helper docstring, one at the call site) — total marker count goes from 4 to 6.
- New translation key `starts_on_invalid` (en + sv). Two new field labels for the HA Settings form (en + sv).
- Panel summary line for interval prescriptions now reads "Every N days from <date> · <times>" — surfaces the anchor inline so a misalignment is visible at a glance.

## [0.2.2] — 2026-05-09

UX bugfix and docs release. Drop-in upgrade from 0.2.1.

- **Empty schedules now rejected.** A prescription with no dose times in simple mode, or with all-empty rows in per-weekday mode, is rejected at validation. Previously such prescriptions were saved silently and never fired reminders. New translation keys `times_required` and `times_per_weekday_required` (en + sv).
- **Modal closes on Escape.** Pressing Escape closes the prescription sub-modal first if open, otherwise the Add/Edit medicine modal. Suppressed during save so an in-flight request can't be dismissed.
- **Backdrop click blocked during save.** Clicking outside the Add/Edit modal or sub-modal while a save is in progress no longer closes it. The Cancel and X buttons were already disabled during save; the backdrop now matches.
- **Privacy docs.** New `Privacy` section in `README.md` plus a longer companion file `PRIVACY.md` — what's stored locally, who can read it, recorder leak surface, actionable mitigations (HA backup encryption, recorder excludes), and an explanation of why integration-level encryption isn't offered.

## [0.2.1] — 2026-05-09

Security release. No data-shape changes; drop-in upgrade from 0.2.0.

- Mutating WebSocket commands (`pillpilot/create_medicine`, `pillpilot/update_medicine`, `pillpilot/delete_medicine`) now require admin. Non-admin HA users can no longer add, edit, or remove medicines via the panel's WS API. The read-only `pillpilot/get_medicines_db` stays open so the panel keeps working for non-admin viewers.
- `pillpilot.refresh_medicines_database` service now requires admin. The handler reads `call.context.user_id` and raises `Unauthorized` for non-admin callers.
- URL scheme for `refresh_medicines_database` restricted to `http`/`https`. Other schemes (`file`, `ftp`, etc.) are rejected at validation time.
- Removed `error_detail` exception string from the `delete_medicine` failure response. The exception still hits the HA log; it just doesn't echo back to the client.

## [0.2.0] — 2026-05-09

Promotion of the 0.2.0 beta cycle to stable. Headline changes from 0.1.5:

- **Scheduler engine rewrite.** Storage now holds an RRULE plus a `schedule_type`. Every-N-days schedules survive month boundaries (May 30 → Jun 1 → Jun 3, not "May 30 then resets to Jun 1, Jun 3"). Existing prescriptions are migrated automatically on first start.
- **Every N days** frequency. Set the interval (2–365). Useful for every-other-day prescriptions and similar rhythms.
- **End date** field, optional, available for any frequency. Useful for antibiotic courses or other time-limited prescriptions.
- **Different times per weekday.** Each prescription can specify its own times for each weekday (e.g. Mon-Fri 08:00, Sat-Sun 10:00). Empty rows in this mode mean skip that weekday entirely.
- **HA Settings form reorganized.** Add medicine / Reconfigure medicine forms now group fields into four collapsible sections (Identity / Drug-database identifiers / Schedule / Per-weekday time overrides) plus a reminder-window field. Optional and advanced sections are collapsed by default.
- **Panel prescription editor UX.** The schedule block uses a Same-vs-Different-times-per-weekday radio mode picker, and the days-of-week selector uses chip buttons with Every-day / Weekdays / Weekends presets. Switching between times modes is lossless within an edit session.
- **Validation hardening.** Weekly without selected days now surfaces `days_required` (was missed in earlier validation work). Interval mode requires an interval between 2 and 365. End date requires `YYYY-MM-DD`. Per-weekday times are validated as 7 entries × HH:MM lists.
- **Internal:** new module-level static name-resolution check in CI catches missing-import bugs before they reach users. New `_flatten_section_input` helper isolates the validator from form-layout concerns. Eight error keys added to `strings.json` to match `translations/en.json` and `translations/sv.json`. Lifecycle log statements in the panel are gated behind a `pillpilot_debug` localStorage flag (default off; enable with `localStorage.setItem("pillpilot_debug", "1")`).

For per-beta detail see the 0.2.0-beta1 through 0.2.0-beta3.6 entries below.

## [0.2.0-beta3.6] — 2026-05-09

UX: panel weekday selector replaces 7 checkboxes with chip buttons + quick presets.

- Days-of-week field (shown when frequency is "Weekly") now renders as a row of 7 chip buttons (Mon … Sun) with three preset buttons above — **Every day**, **Weekdays**, **Weekends**. Tapping a preset overwrites the day selection in one click; tapping individual chips toggles them in or out. The active preset (if the current selection matches one) is highlighted; a custom selection shows no preset highlighted.
- Same data model as before (`draft.daysOfWeek` is still a `Set<string>` of "0".."6"). Validator, on-disk shape, and WebSocket payload are unchanged.
- The old `<input type="checkbox">` markup and the `.day-checkbox` CSS are removed; the `daysOfWeek` branch in the data-sub-field dispatcher is gone (chip clicks route through `data-action="weekday-toggle"` and presets through `data-action="weekday-preset"`).

## [0.2.0-beta3.5] — 2026-05-09

UX: panel prescription form replaces the "Different times per day of week" checkbox with a mode picker.

- Times mode is now a radio pair — **Same times every day** vs **Different times per weekday** — that determines which times input appears below. The single "Times of day" field and the seven per-weekday rows are mutually exclusive in the UI; only one is shown at a time. The previous checkbox toggle that left "Times of day" visible above the per-weekday rows is gone.
- Switching between modes is lossless within an edit session: both `draft.times` and `draft.timesPerWeekday` stay alive in the draft regardless of which mode is active. Switching to per-weekday only seeds the seven rows from "Times of day" if they are currently empty (first-time helper); subsequent switches preserve whatever the user has typed. Switching back to "Same times every day" no longer wipes the per-weekday entries. On save, only the active mode's data persists — same on-disk shape as before.
- Validator, WebSocket contract, and on-disk format are unchanged. Pure rendering and event-handler change in `panel.js` (~30 LOC delta).

## [0.2.0-beta3.4] — 2026-05-09

UX: HA Settings form is now organized into collapsible sections instead of one flat ~22-field stack.

- Add medicine / Reconfigure medicine forms group fields into four sections — **Identity** (drug + dose), **Drug-database identifiers** (varunummer / NPL ID / ATC code, collapsed by default), **Schedule** (frequency + frequency-conditional fields), and **Per-weekday time overrides** (collapsed by default — Mon-Fri / Sat-Sun-style schedules). The reminder-window field stays at the top level. Sections use HA's native `section()` schema construct, so collapse/expand behavior comes from HA's form renderer.
- `_flatten_section_input` in `MedicineSubentryFlow` unwraps the nested user input HA delivers into the flat shape `validate_medicine_input` expects. The validator and on-disk storage are section-unaware; only the flow handler knows about form layout. A future migration to a multi-step config flow uses the same boundary.
- Tests: new `test_v020_beta3_4_sections.py` covers flatten semantics, section-name constants, and an end-to-end round-trip from sectioned form input through the validator. The 6 existing tests that stub Home Assistant got a one-line `homeassistant.data_entry_flow` shim so they continue to load `config_flow.py` after the new import.

## [0.2.0-beta3.3] — 2026-05-09

Hotfix for beta3.2.

- Fix: medicine-name autocomplete in the panel's Add/Edit modal failed to appear when the user opened the modal before the catalog websocket fetch resolved (the common case on first panel load). The fetch resolves async; the modal was already rendered with an empty `<datalist>` and the panel's re-render is suppressed while a modal is open, so the catalog never reached the dropdown until the user closed and reopened the modal. Now the cache-resolve handler refreshes the open modal's `<datalist>` options surgically without disturbing the rest of the form, so autocomplete fills in as soon as the catalog lands.

## [0.2.0-beta3.2] — 2026-05-09

Hotfix for beta3.1.

- Fix: HA Settings → Reconfigure medicine form was rendering raw field keys (`interval_days`, `ends_on`, `times_mon` …) instead of human labels for the new beta3 fields. Added the missing entries to `strings.json`, `translations/en.json`, and `translations/sv.json` for both the `user` and `reconfigure` steps. Existing prescriptions are unaffected.

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
