# v0.2.15

> Panel responsiveness pass. Drop-in upgrade from 0.2.14.

## What's fixed

Three things found in the audit pass on v0.2.14's optimistic UI:

**Bulk actions used to render N+1 times.** Take all on 10 doses did 11 panel rewrites in one click — each single-dose helper rendered, plus a final render. v0.2.15 batches: the loop sets the overrides, the panel renders once at the end.

**Optimistic badges no longer lie forever.** If a service call silently fails server-side, the override now expires after 60 seconds and the badge reverts to whatever the backend actually thinks. Pre-v0.2.15 a failed Take would leave the badge permanently green until a page reload.

**Entity-table walks consolidated.** `_getMedicines` is now cached per `hass.states` reference, so the multiple call sites (signature, render, person grouping) walk the table once per state push instead of 3-4 times. Material on instances with hundreds of non-PillPilot entities.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. Frontend-only fix.
