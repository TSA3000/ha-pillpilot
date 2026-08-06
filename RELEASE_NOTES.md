# v0.3.4

Fixes the Log a dose dialog from 0.3.3.

## Changes

- Fix the Log a dose dialog's buttons doing nothing: its event listeners were only attached while the Stock dialog was open. Cancel, close, and Log dose now work.

## Upgrading

Update through HACS (or replace the `pillpilot` directory in `custom_components/` with the contents of this zip) and restart Home Assistant. Hard-refresh the browser to pick up the new panel.
