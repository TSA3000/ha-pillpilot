# v0.3.0-beta3

Beta release.

## Changes

- List view: the per-row Edit and Stock actions are now in a kebab (⋮) menu at the end of each row. This keeps rows aligned to their columns — the earlier inline Stock button pushed a second control outside the grid. Card view is unchanged (Edit and Stock buttons in the footer).

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. The panel is cache-busted by version. No data migration.
