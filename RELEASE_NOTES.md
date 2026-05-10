# v0.2.8

> Snooze UX. Drop-in upgrade from 0.2.7.

## What's new

Snooze is a first-class panel action now. The mobile notification has had a Snooze button since 0.1.0; the panel was missing it.

- **Snooze button on Due / Missed / Upcoming rows.** Three buttons per actionable row: Take / Snooze / Skip. Snooze defaults to 15 minutes, matching the mobile notification.
- **Snooze all due (15m)** in the per-person kebab menu — pushes every currently-due slot for that person out by 15 minutes in one tap.
- **Snooze all missed (15m)** likewise for missed slots.
- Existing snooze semantics from 0.2.7 unchanged: snoozed slots fire `pillpilot_dose_due` again when the snooze elapses; `pillpilot_dose_missed` stays suppressed for any slot the user engaged with via snooze.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.
