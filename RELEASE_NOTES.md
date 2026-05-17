# v0.2.18

Per-user manager allowlist.

## Changes

Settings → Devices & services → PillPilot → Configure now has a **Managers** field — a multi-select of HA users with rights to create, edit, and delete medicines from the panel.

Owner always has manager rights. The owner is pre-checked in the selector as a visual reminder; saving with only the owner checked stores an empty list, which keeps the default behavior (every admin can manage). To restrict management to specific users, add them to the list — only the owner and the listed users will be able to mutate; every other user gets a read-only view.

Dose actions (Take, Skip, Snooze, Undo) and mobile notification actions stay open to all users. Only medicine management is gated.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS: update normally. No data migration; existing installs keep current behavior until users are added to the Managers list.
