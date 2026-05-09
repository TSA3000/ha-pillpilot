# v0.2.0-beta3.1

> Hotfix for beta3. Install over the top — no data migration, no config changes, prescriptions keep their existing settings.

## What changed

**Fixed: coordinator crash on startup with interval-mode prescriptions.** Beta3 introduced "Every N days" frequency but the coordinator's prescription-state builder was missing the import for `SCHEDULE_TYPE_INTERVAL`, so any HA install where a user had created an interval-mode prescription hit a `NameError` on the first refresh tick. Symptom in the log:

```
NameError: name 'SCHEDULE_TYPE_INTERVAL' is not defined
```

Fix is one line — the missing import. No data needs migrating. Prescriptions created or edited under beta3 continue to work unchanged.

**Tests:** added a static name-resolution check that walks the core modules (`coordinator`, `config_flow`, `schedule`, `sensor`) and fails if any function body references a constant that wasn't imported at the top of the file. Catches this exact class of bug at CI time rather than runtime.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update the integration normally — the 0.2.0-beta3.1 tag will appear under "Beta versions enabled."
