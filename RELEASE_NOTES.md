# v0.3.0

Stock and inventory tracking.

## Changes

- Per-prescription stock tracking, off until enabled. Current stock is derived from a ledger of set / refill / adjust events minus the units consumed by taken doses, so undoing a dose or recording several at once keeps the count right.
- Stock is counted in the prescription's per-dose unit. A refill adds pack size times the number of packs. Injection stock reports both injections left and the pen/pack equivalent.
- Refill reminder with a threshold measured in units left, doses left, or days until run-out. The run-out date is projected forward from the prescription's schedule.
- Editable expiry date per prescription, with expiring and expired events.
- Managed from the panel: a Stock button on each medicine card and list row opens a per-prescription dialog for setting the count, refilling by packs, adjusting, toggling tracking, and editing pack size, refill reminder, and expiry. Tracked prescriptions show a compact readout with low-stock and expiry badges.
- New services: `configure_stock`, `set_stock`, `adjust_stock`, `refill`.
- New events: `pillpilot_stock_low`, `pillpilot_stock_expiring`, `pillpilot_stock_expired`.
- New per-prescription sensor attributes: `track_stock`, `stock`, `stock_unit`, `pack_size`, `packs_left`, `doses_left`, `days_left`, `run_out_date`, `expiry_date`, `low_stock`. A medicine-level `low_stock` flag is true when any tracked prescription is below its threshold.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. The panel is cache-busted by version. No data migration.
