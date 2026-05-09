# v0.2.1

> Security release. Drop-in upgrade from 0.2.0.

## What's fixed

In multi-user HA setups, non-admin users could previously add, edit, or delete medicines via the panel's WebSocket API, and could call `pillpilot.refresh_medicines_database` with an arbitrary URL. Both paths are now admin-only. The URL field on the refresh service is also restricted to `http`/`https` schemes so it can't be pointed at `file://` or other local-resource schemes.

Single-user installs are unaffected — admin-only is the same as the only user.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.
