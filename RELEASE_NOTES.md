# v0.2.19

Stable release. Consolidates the v0.2.19 betas (per-medicine visibility, selected-users sidebar mode, panel language) and adds two fixes: the medicine-edit freeze and slow dose registration.

## Access control

**Per-medicine visibility** — each medicine now has a Visibility setting in the panel's Add / Edit modal:

- **Everyone** (default) — anyone with panel access sees it.
- **Linked person only** — only the HA users linked to the medicine's prescriptions.
- **Admins only** — owner, managers, and HA admins.
- **Specific users** — an explicit allowlist you pick.

Owner and managers always have access. The panel hides medicines a user isn't allowed to see, and the create / edit / delete commands enforce the same check on the backend.

**Selected users sidebar mode** — the Sidebar panel dropdown adds a fourth option, so it now reads Admins only / Selected users / Everyone / Hidden. In Selected users mode you pick which HA users can use the panel. Note the platform limitation: Home Assistant's panel API can't hide a sidebar entry from specific users, so the entry stays visible to everyone in this mode and non-allowed users see an access-denied screen when they open it. The medicine management commands are still gated on the backend regardless.

## Panel language

A Panel language setting (Auto / English / Svenska) in the Configure form. Auto follows each user's HA language. The most-visible panel strings are translated; status badges and detailed form hints stay English for now.

## Fixes

**Medicine edit froze the window.** The access-control decorators added in v0.2.18 were async, but Home Assistant calls the websocket handler synchronously, so the request's coroutine was never awaited and the window hung (`RuntimeWarning: coroutine '_ws_create_medicine' was never awaited`). Fixed by making the decorators synchronous. This affected every create / edit / delete from the panel since v0.2.18.

**Dose actions were slow to register.** Two causes:

- Single actions used Home Assistant's debounced refresh, which could defer the state update by several seconds when an action landed near the once-a-minute background scan. They now refresh immediately, so the row flips to Taken / Skipped / Snoozed as soon as the backend records it.
- Bulk actions (Take all / Take due / Take missed, plus bulk snooze and bulk Undo) fired one service call per dose, each with its own disk write and full recompute. They now send a single batched call that records every dose with one save and one refresh — near-instant regardless of how many doses the button targets.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. Hard-reload the panel (Ctrl+Shift+R) to pick up the new `panel.js`. No data migration; existing installs keep their current settings and default new ones (visibility `Everyone`, language `Auto`).
