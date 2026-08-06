# v0.3.1

Fix for Home Assistant 2026.8. If your medicines disappeared from the panel after updating HA, this release restores them.

## Changes

- Each medicine now gets its own HA device instead of sharing a per-person / "Household Medicines" device. HA 2026.8 restricts a device to a single config subentry; with the shared device, every medicine after the first failed to register its sensor and the panel showed no medicines. Entity ids are unchanged, so automations and blueprints keep working; the old empty devices are removed automatically on the first update after restart.
- The coordinator passes its config entry explicitly, as required by HA 2026.8.

## Upgrading

Update through HACS (or replace the `pillpilot` directory in `custom_components/` with the contents of this zip) and restart Home Assistant.
