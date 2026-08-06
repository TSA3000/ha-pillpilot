# v0.3.2

Fixes the Home Assistant 2026.8 breakage. Use this instead of 0.3.1, which crashed on startup.

## Changes

- Fix a startup crash in 0.3.1: the coordinator referenced a renamed variable when opening its history store, failing the integration setup. Dose history is unaffected — the storage key is unchanged.
- From 0.3.1: each medicine gets its own HA device instead of sharing a per-person / "Household Medicines" device. HA 2026.8 restricts a device to a single config subentry; the shared device made every medicine after the first fail to register its sensor, so the panel showed no medicines. Entity ids are unchanged; stale empty devices are removed automatically.
- From 0.3.1: the coordinator passes its config entry explicitly, as required by HA 2026.8.

## Upgrading

Update through HACS (or replace the `pillpilot` directory in `custom_components/` with the contents of this zip) and restart Home Assistant.
