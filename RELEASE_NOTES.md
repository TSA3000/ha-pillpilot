# v0.2.19-beta1

Beta release. Access control: per-medicine visibility.

## What's new

Each medicine now has a **Visibility** setting in the panel's Add and Edit modal. Four modes:

- **Everyone** — default, backward-compat with pre-v0.2.19 medicines. Anyone with panel access can see and (if a manager) edit.
- **Linked person only** — only the HA users whose person entity is the `person_id` of any prescription on this medicine, plus owner and managers.
- **Admins only** — only owner, managers, and HA admins.
- **Specific users** — explicit allowlist. A multi-select of HA users appears beneath the mode dropdown; pick the ones who should see the medicine. Owner is pre-checked as an informational hint (owner always has access regardless) and stripped from the stored list on save.

Owner and managers always have access regardless of mode — visibility is the gate for everyone else.

Mutating WS commands (`update_medicine`, `delete_medicine`) now check both manager status and visibility. A manager who can't see a medicine cannot edit it via the WS either.

## Known limitations

Sensors stay globally readable. Any HA user with access to Developer Tools can still read the sensor state of a restricted medicine. That's a Home Assistant platform limitation — entity registry permissions are admin / non-admin only, no per-user filtering. Tier 2 stops at panel-level visibility. Sensor gating (skip creating sensors for restricted medicines) is Tier 3 and deferred.

HA Settings reconfigure flow does not yet expose visibility. Panel-only for this beta. Visibility can only be set via the Add / Edit medicine modal in the panel.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users on the beta channel: update normally. Hard-reload the panel (Ctrl+Shift+R) — HACS doesn't bust the browser cache of `panel.js`.

Pre-v0.2.19 medicines keep their current behavior — `everyone` is the effective mode until you edit a medicine and pick a different one.
