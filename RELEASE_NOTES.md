# v0.2.14

> Optimistic UI for dose actions. Drop-in upgrade from 0.2.13.

## What's fixed

Tapping **Take**, **Skip**, **Snooze**, or **Undo** on a dose now flips the badge immediately. Same for the bulk actions (**Take all**, **Take all due**, **Take all missed**, **Snooze all due**, **Snooze all missed**). Pre-v0.2.14 the panel waited for the backend's websocket round-trip before re-rendering, which made single-dose actions feel sluggish and made bulk actions look broken — you had to reload the page to see the change.

The fix is panel-side optimistic UI. The new `_optimisticOverrides` map records the intended new status (taken / skipped / snoozed) for each clicked dose slot, the renderer overlays it on top of the slot data immediately, and the override is automatically pruned as soon as the backend's actual state catches up. If the service call fails on the backend, the next state push reverts the badge to its real status.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. No data changes — frontend-only fix.
