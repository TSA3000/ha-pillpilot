# v0.3.5

Fixes the date and time pickers in the Log a dose dialog.

## Changes

- Fix the Log a dose dialog's date and time pickers not opening on click. The native popups are now summoned explicitly; typing into the fields keeps working where popups aren't available.

## Upgrading

Update through HACS (or replace the `pillpilot` directory in `custom_components/` with the contents of this zip) and restart Home Assistant. Hard-refresh the browser to pick up the new panel.
