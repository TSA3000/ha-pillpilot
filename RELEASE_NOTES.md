# v0.2.19-beta2

Beta release. Two additions: a fourth sidebar visibility mode and a panel UI language override.

## Sidebar panel visibility

The Sidebar panel dropdown in Settings → Devices & services → PillPilot → Configure now reads:

- **Admins only** — only HA admins see the sidebar entry.
- **Selected users** — only HA users on the new allowlist see the useful panel content. Owner always has access.
- **Everyone** — anyone with PillPilot access sees the sidebar entry.
- **Hidden** — panel not registered at all.

When `Selected users` is picked, a multi-select user list appears under the dropdown. Add the users you want to grant access to. The owner is pre-checked as an informational hint (owner always has access regardless) and stripped from the stored list on save.

**Platform limitation worth noting.** Home Assistant's panel registration API does not support per-user allowlists at the frontend layer — a panel is either registered (visible to everyone or admins-only) or not registered at all. The `Selected users` mode works around this by registering the panel for everyone and gating the panel body client-side in `panel.js`. The sidebar entry itself is visible to all users in this mode; clicking it as a non-allowed user shows an access-denied placeholder instead of the medicines view. The mutating WS commands (`create_medicine`, `update_medicine`, `delete_medicine`) remain gated server-side and aren't affected by this limitation.

## Panel UI language

New **Panel language** field in the Configure form. Three options:

- **Auto** (default) — follows each user's HA language at render time.
- **English** — force English regardless of HA locale.
- **Svenska** — force Swedish regardless of HA locale.

The most-visible panel strings are translated in this beta: bulk action buttons (Take all / Take due / Take missed), Saving spinner, modal section titles, modal buttons (Save / Cancel / Delete / Add prescription), and loading / empty / access-denied placeholders. Status badges (Due / Taken / Missed / etc), schedule descriptions, and detailed form hints are not yet translated and stay English for now — TODO for the next beta.

The Configure form translations (the labels for each field) follow HA's normal translation system and respect each user's HA locale automatically.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. Hard-reload the panel (Ctrl+Shift+R) — the `?v=...` query string on the panel.js URL should bust the cache, but a hard reload guarantees it.

No data migration. Existing installs keep their current sidebar visibility setting and default to `Auto` language. Pre-v0.2.19 medicines keep `Everyone` visibility.
