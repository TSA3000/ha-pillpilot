# v0.2.0-beta2

> **Pre-release.** Fixes a crash that hid the side panel after upgrading from v0.1.5. v0.2.0-beta1 is retracted.

If you installed v0.2.0-beta1 and lost the panel: redownload this version, restart HA, panel comes back.

## What was broken

The new scheduler's `next_after` mixed timezone-naive and timezone-aware datetimes. HA always passes aware datetimes, so the very first coordinator update raised `TypeError` and the panel never finished registering.

## Fix

Walk dates by offset (the same shape v0.1.x used) and apply `now.tzinfo` to the result. Regression test added for the aware-input path so this can't slip again.

## Upgrading

- From v0.1.5: drop-in. Migration runs once on first start.
- From v0.2.0-beta1: drop-in. Storage was already converted, so the migration is a no-op.

## Known issues

See README.
