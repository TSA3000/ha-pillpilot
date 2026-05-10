# v0.2.7

> Snooze fix. Drop-in upgrade from 0.2.6.

## What's fixed

Snooze didn't work pre-0.2.7. Tapping `Snooze 15m` on a PillPilot notification (or calling `pillpilot.snooze` directly) wrote a junk `DoseRecord` with `scheduled_for = now + 15min` and called it done. That synthetic time never matched any of the medicine's RRULE-derived slots, so:

- The original dose stayed `due` and then flipped to `missed` after the remind window, exactly as if no snooze had been tapped.
- No follow-up `pillpilot_dose_due` event ever fired, so the blueprint never re-sent the notification.
- The orphan record sat in `.storage/pillpilot.history.<entry>` forever.

## What's new

Snooze now stamps `snoozed_until` on the `DoseRecord` for the original scheduled slot. The tick re-fires `pillpilot_dose_due` when the snooze elapses, and `notify_dose` sends a fresh notification with Taken / Snooze / Skip. Snoozed slots are exempt from `pillpilot_dose_missed` — the user already engaged.

- New `pillpilot_dose_snoozed` event with `medicine_id`, `scheduled_for`, `snoozed_until`, `minutes`, `person_id`.
- New `snoozed` sensor state. Per-slot `today_doses` carries `snoozed_until`.
- `pillpilot.snooze` accepts an optional `scheduled_for` for multi-slot medicines.
- Panel renders snoozed slots as "⏰ Snoozed until HH:MM" with inline Take / Skip override buttons.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.

Pre-0.2.7 orphan snooze records are harmless — they don't match any scheduled slot, so the new lookup ignores them. To purge them now, stop HA, delete `.storage/pillpilot.history.<entry_id>`, restart. (Note: this also clears your taken/skipped history.)
