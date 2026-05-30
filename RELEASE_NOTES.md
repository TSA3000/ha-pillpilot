# v0.2.19-beta3

Bugfix release.

## Fixed

Updating, creating, or deleting a medicine from the panel froze the window. The access-control decorators added in v0.2.18 were written as async wrappers, but Home Assistant's websocket dispatcher calls the outermost command handler synchronously — so the handler's coroutine was created and then discarded without being awaited. The log showed `RuntimeWarning: coroutine '_ws_update_medicine' was never awaited` and the request never completed.

Both decorators are now synchronous, matching the pattern Home Assistant uses for its own `require_admin` decorator. Manager and per-medicine visibility checks are unchanged in behavior — they just run in the right execution context now.

This affected every medicine create / edit / delete from the panel since v0.2.18. Dose actions (Take / Skip / Snooze) were never affected — they go through service calls, not these websocket commands.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. No data migration.
