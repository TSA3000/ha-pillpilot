# v0.3.0-beta1

Beta release. Stock / inventory tracking, exposed through services and sensor attributes.

## What's in this build

- Per-prescription stock tracking, off until enabled. Current stock is derived from a ledger of set / refill / add / remove events minus the units consumed by taken doses, so undoing a dose or recording several at once keeps the count right.
- Stock is counted in the prescription's per-dose unit. A refill adds pack size times the number of packs. Injection stock reports both injections left and the pen/pack equivalent.
- Refill reminder with a threshold measured in units left, doses left, or days until run-out. The run-out date is projected from the prescription's schedule.
- Editable expiry date per prescription.
- Services: `configure_stock`, `set_stock`, `adjust_stock`, `refill`.
- Events: `pillpilot_stock_low`, `pillpilot_stock_expiring`, `pillpilot_stock_expired`.
- Per-prescription sensor attributes: `track_stock`, `stock`, `stock_unit`, `pack_size`, `packs_left`, `doses_left`, `days_left`, `run_out_date`, `expiry_date`, `low_stock`; plus a medicine-level `low_stock`.
- Dose records carry the prescription id and units consumed; older records are matched to their prescription on load.

## Trying it

Stock is controlled by services in this build (Developer Tools → Actions):

1. Find the `medicine_id` and the prescription `id` in the medicine sensor's attributes (`prescriptions` list).
2. Call `pillpilot.configure_stock` with `track_stock: true`, a `pack_size`, and optionally `reminder_enabled: true` with a `reminder_mode` (`units` / `doses` / `days`) and `reminder_threshold`.
3. Set a starting count with `pillpilot.set_stock` (or add packs with `pillpilot.refill`).
4. Mark doses taken and watch `stock`, `doses_left`, `days_left`, and `run_out_date` update on the sensor. `low_stock` flips on at the threshold and the stock events fire for automations.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. No data migration.
