# v0.2.0-beta3

> **Pre-release.** Three new schedule fields. Cycle mode (birth-control style) ships in beta4; the raw RRULE escape hatch in beta5.

## What's new

**Every N days.** Open a prescription's Add/Edit form, pick "Every N days" in the Frequency dropdown, set the interval. Examples:

- `2` — every other day
- `3` — every third day
- `14` — every two weeks (e.g. once-fortnightly meds)
- `84` — every 12 weeks (long-acting injection schedule)

The rhythm survives month boundaries. An every-other-day prescription that starts May 30 fires May 30, Jun 1, Jun 3, Jun 5… It doesn't restart on the 1st of the month like a cron `*/2` schedule would.

**End date.** New optional field, visible for every frequency. Set a date and the prescription stops firing after it. Empty means no end date (the default for ongoing meds). Common uses:

- Antibiotic courses: pick Daily, two times of day, end date 7 days out.
- Steroid tapers paired with another tracking strategy.
- Any prescription with a planned cutoff.

**Different times per day of week.** New optional toggle in the prescription form. Default is off — the existing "Times of day" field continues to apply every firing day. Flip the toggle on and seven per-weekday rows appear (Mon, Tue, …, Sun), each with its own comma-separated times. Common patterns:

- **Later on weekends:** Mon-Fri `08:00`, Sat-Sun `10:00`. One prescription, no duplicates.
- **Skip a day entirely:** Mon-Sat `08:00`, Sun blank. The blank row means no doses fire that weekday.
- **Different cadence on different days:** Mon `08:00, 20:00`, Tue `09:00`, Wed-Fri `08:00, 20:00`, Sat-Sun blank.

Toggling on copies "Times of day" into all seven rows so you have a starting point. Toggling off discards per-weekday entries and reverts to the simple flat field.

## Upgrading

Drop-in from any 0.2.x. Existing prescriptions keep their current behavior — the three new fields are opt-in, blank by default.

## HA Settings vs. panel

The panel exposes the per-weekday toggle for everyday editing. The HA Settings → Devices integration form also shows seven per-weekday text fields directly (no toggle); leave them all blank to use the simple "Times of day" field for every weekday, or fill any of them in to override. The panel is generally easier for this kind of editing.

## Known issues

See README.
