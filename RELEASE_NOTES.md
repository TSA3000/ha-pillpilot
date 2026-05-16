# v0.2.16

Revert optimistic dose-state overlay. Add pending-action spinner.

## Changes

Dose badges no longer flip on click. They flip when Home Assistant pushes the new state, same as pre-v0.2.14.

Click Take, Skip, Snooze or Undo on a dose and the action buttons are replaced by a **Saving…** spinner until the backend confirms. 30 s safety TTL so the spinner clears if a service call silently fails.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS: update normally. Hard-reload the panel (Ctrl+Shift+R) — HACS doesn't bust the browser cache of `panel.js`.
