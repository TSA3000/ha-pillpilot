# v0.3.0-beta2

Beta release. Stock tracking now has a panel UI.

## What's in this build

- A Stock button on every medicine card and list row opens a per-prescription stock dialog.
- The dialog covers both the count and the settings:
  - Set the current count, refill by packs, or adjust up/down.
  - Toggle tracking, set pack size, configure the refill reminder (units / doses / days with a threshold), and set an expiry date.
- Tracked prescriptions show a compact readout on the card: count, doses left, run-out date, and low-stock / expiry badges.
- Card readout is translated (English and Swedish).

## Trying it

1. Open a medicine's Stock button on its card.
2. Turn on Track stock, set a pack size, and (optionally) a refill reminder, then Save settings.
3. Set a starting count, or Refill to add packs.
4. Mark doses taken and watch the readout update; the low badge appears at the threshold.

Stock can still be driven by the services (`configure_stock`, `set_stock`, `refill`, `adjust_stock`) — the panel calls the same ones.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. The panel is cache-busted by version, so a hard refresh isn't needed. No data migration.
