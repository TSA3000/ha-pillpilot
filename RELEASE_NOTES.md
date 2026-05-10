# v0.2.6

> Blueprint hotfix. Drop-in upgrade from 0.2.5.

## What's fixed

The `handle_actions` blueprint failed with `UndefinedError: 'len' is undefined` whenever a Taken / Snooze / Skip button was tapped on a PillPilot notification. Home Assistant's Jinja2 sandbox doesn't expose Python's `len()` as a global, so `action[len('PILL_TAKEN_'):]` raised before the service call. The mobile_app integration dismisses the notification on action tap regardless of whether the automation succeeded, so the symptom was: notification disappears, dose stays unmarked.

Replaced the `len()` slicing with the `replace` filter, which works in the sandbox:

```yaml
medicine_id: "{{ action | replace('PILL_TAKEN_', '', 1) }}"
```

Same fix applied to all three branches (Taken, Snooze, Skip).

No integration code changed — blueprint-only fix.

Fixes [#3](https://github.com/TSA3000/ha-pillpilot/issues/3).

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally.

**Then re-import the `handle_actions` blueprint** so existing automations pick up the fix:

1. **Settings → Automations & Scenes → Blueprints**.
2. Find **PillPilot — handle notification actions**, click the ⋮ menu → **Re-import blueprint**.
3. **Developer Tools → YAML → Reload Automations** (or restart HA).

Existing automations created from the blueprint don't need to be re-created.
