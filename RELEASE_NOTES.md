# v0.2.4

> Fixes a long-standing bug in Every-N-days scheduling and adds a configurable Start date. Drop-in upgrade from 0.2.2.

## What's fixed

The Every-N-days frequency was missing two related things — both reported in [#2](https://github.com/TSA3000/ha-pillpilot/issues/2) — and both fixed in this release.

**No way to set the start day.** A user adding a 14-day shot 7 days after their last dose had no way to anchor the cycle correctly. The integration would fire 14 days from today instead of 7. There's now a Start date field on Every-N-days prescriptions: set it to the date of your last dose (or any cycle anchor) and the next-due math lines up. Blank stays "start today."

**Cycle phase shifted on HA restart.** The rrule's DTSTART was implicitly `date.today()` at every load. An "every 14 days" schedule that had been firing on Mondays would silently start firing on Wednesdays after a Wednesday reboot. The anchor is now stored on the prescription and stable across restarts. Existing interval prescriptions get their anchor stamped automatically on first load after upgrade.

## What's new

- **Start date** field on the prescription form (panel and HA Settings), shown only for Every-N-days mode since that's the only mode where the anchor matters. Past dates are accepted.
- Panel schedule line for interval prescriptions now reads "Every 14 days from May 4 · 08:00" — anchor visible inline.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.

Existing Every-N-days prescriptions will have their start date stamped automatically on first boot after upgrade — preserving whatever cycle phase they had at the moment of upgrade. After that, the phase is stable.
