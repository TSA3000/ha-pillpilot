# v0.2.0-beta1

> **Pre-release.** First beta of the scheduler rewrite. Daily / weekly / monthly prescriptions should behave identically to v0.1.5 — please report any drift. New schedule modes (every N days, courses, cycling) ship in later betas.

## What's coming in 0.2.x

The scheduler engine is being replaced. The form UI is unchanged in this beta, but the new engine unlocks schedules the old one couldn't express:

- Every N days that keeps its rhythm across month boundaries (every other day starting May 30 → May 30, Jun 1, Jun 3, Jun 5…).
- Antibiotic-style courses with a start and end date.
- Cyclical on/off — e.g. 21 on / 7 off, or 24 on / 4 off.
- A raw escape hatch for arbitrary patterns ("every first Monday of the month" and similar).

UI for these ships in 0.2.0-beta2, beta3, and beta4.

## In this beta

- New engine. Existing prescriptions migrate automatically on first start.
- `python-dateutil` added to manifest requirements (already pulled in by Home Assistant).
- Weekly with no weekdays selected is now rejected up front. Previously it was silently accepted and ran like daily.

## Upgrading

Drop-in. Restart HA after installing. You'll see one log line on first start:

```
Migrated N medicine subentry/subentries to v0.2.0 schedule shape
```

If a prescription starts firing on the wrong day or stops firing, open an issue with the schedule type and any selected weekdays / days-of-month.

## Known issues

See README.
