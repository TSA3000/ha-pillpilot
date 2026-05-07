"""The PillPilot integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_MED_ID,
    CONF_MED_NAME,
    CONF_MED_PRESCRIPTIONS,
    CONF_MEDICINES_DB_URL,
    CONF_PANEL_VISIBILITY,
    DOMAIN,
    PLATFORMS,
    SERVICE_MARK_TAKEN,
    SERVICE_REFRESH_MEDICINES_DATABASE,
    SERVICE_SKIP,
    SERVICE_SNOOZE,
    SERVICE_UNMARK_TAKEN,
    SUBENTRY_TYPE_MEDICINE,
)
from .coordinator import MedicineCoordinator
from .config_flow import (
    build_subentry_title,
    merge_v2_prescriptions_into_existing,
    validate_medicine_input_multi,
)
from .medicines import DEFAULT_MEDICINES_DB_URL, MedicineDatabase, sanitize_for_ws
from .panel import async_register_panel, async_unregister_panel
from .sources import build_sources

_LOGGER = logging.getLogger(__name__)

MARK_TAKEN_SCHEMA = vol.Schema(
    {
        vol.Required("medicine_id"): cv.string,
        # v0.2.24: optional, lets callers pin the action to a specific
        # prescription for multi-prescription medicines. None / omitted
        # falls back to the closest-by-time prescription resolver.
        vol.Optional("person_id"): vol.Any(cv.string, None),
        vol.Optional("when"): cv.datetime,
        vol.Optional("scheduled_for"): cv.datetime,
    }
)
SKIP_SCHEMA = vol.Schema(
    {
        vol.Required("medicine_id"): cv.string,
        vol.Optional("person_id"): vol.Any(cv.string, None),
        vol.Optional("scheduled_for"): cv.datetime,
    }
)
SNOOZE_SCHEMA = vol.Schema(
    {
        vol.Required("medicine_id"): cv.string,
        vol.Optional("person_id"): vol.Any(cv.string, None),
        vol.Required("minutes", default=15): vol.All(int, vol.Range(min=1, max=240)),
    }
)
UNMARK_TAKEN_SCHEMA = vol.Schema(
    {
        vol.Required("medicine_id"): cv.string,
        vol.Optional("person_id"): vol.Any(cv.string, None),
        vol.Optional("scheduled_for"): cv.datetime,
    }
)
REFRESH_MEDICINES_DB_SCHEMA = vol.Schema(
    {
        vol.Optional("url"): cv.url,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _medicines_from_subentries(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Extract medicine config dicts from this entry's subentries.

    The medicine's identity is its HA-assigned ``subentry_id``. We
    inject that into ``CONF_MED_ID`` on the in-memory dict so the rest
    of the codebase can keep using ``med[CONF_MED_ID]`` as the lookup
    key without caring where it came from.
    """
    out: list[dict[str, Any]] = []
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_TYPE_MEDICINE:
            continue
        med = dict(sub.data)
        med[CONF_MED_ID] = sub.subentry_id
        out.append(med)
    return out


def _retitle_medicine_subentries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure every medicine subentry's title is the canonical
    "name — person" form (or just "name" for household).

    Pre-v0.2.9 subentries were titled with the bare medicine name,
    making same-name-different-person pairs indistinguishable on the
    integration card. This migration walks all medicine subentries
    once on setup and fixes any that don't already match the canonical
    title. Skips subentries where the title is already correct, so
    re-runs are no-ops.
    """
    for sub in list(entry.subentries.values()):
        if sub.subentry_type != "medicine":
            continue
        new_title = build_subentry_title(hass, dict(sub.data))
        if new_title != sub.title:
            hass.config_entries.async_update_subentry(entry, sub, title=new_title)


# ---------------------------------------------------------------------------
# Setup / unload
# ---------------------------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PillPilot from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Set canonical "name — person" titles on medicine subentries.
    _retitle_medicine_subentries(hass, entry)

    # Medicines list (Swedish meds) is shared
    # across all entries — there's only ever one PillPilot
    # entry, but using a hass.data slot makes it accessible from the
    # config flow without entry plumbing. Loaded once: stored copy from
    # disk if a refresh has happened, else the bundled JSON.
    medicine_db = hass.data[DOMAIN].get("medicine_db")
    if medicine_db is None:
        medicine_db = MedicineDatabase(hass)
        await medicine_db.async_load()
        hass.data[DOMAIN]["medicine_db"] = medicine_db

    # If the Reconfigure flow asked for a refresh (transient toggle),
    # honor it now — fetch from URL, persist, then strip the toggle so
    # we don't re-fetch on every reload.
    if entry.data.get("refresh_medicines_now"):
        url = entry.data.get(CONF_MEDICINES_DB_URL) or DEFAULT_MEDICINES_DB_URL
        ok, msg = await medicine_db.async_refresh_from_url(url)
        if ok:
            _LOGGER.info("Medicines list refreshed: version %s", msg)
        else:
            _LOGGER.warning("Medicines list refresh failed: %s", msg)
        # Strip the transient regardless of outcome so it doesn't re-fire.
        new_data = {k: v for k, v in entry.data.items() if k != "refresh_medicines_now"}
        hass.config_entries.async_update_entry(entry, data=new_data)

    session = async_get_clientsession(hass)
    # No built-in sources ship in v0.2.14 — build_sources returns an
    # empty list. Future v0.2.16 FASS-web-link source will plug in here.
    sources = build_sources(enabled=[], config=dict(entry.data), session=session)

    medicines = _medicines_from_subentries(entry)

    coordinator = MedicineCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        medicines=medicines,
        sources=sources,
    )
    await coordinator.async_load()
    await coordinator.async_setup_sources()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    _register_websocket_commands(hass)
    await async_register_panel(hass, entry)

    # Snapshot the reload-requiring settings so the update listener can
    # tell whether a real reload is needed or just a coordinator refresh.
    # Without this snapshot every entry-data change (taking a dose,
    # editing a subentry, retitle migration on next boot) would trigger
    # a full async_reload — which unregisters and re-registers the
    # panel mid-navigation and produces HA's InvalidStateError, leaving
    # the user with a blank disconnected panel until full page reload.
    hass.data[DOMAIN][entry.entry_id]["reload_keys_snapshot"] = (
        _reload_keys_snapshot(entry)
    )
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


# Settings whose change *requires* a full entry reload (re-registers
# panel, etc.). Everything else can be picked up by the coordinator
# without unloading. As of v0.2.14 only panel visibility qualifies —
# all source-related keys were removed.
_RELOAD_REQUIRING_KEYS = (CONF_PANEL_VISIBILITY,)


def _reload_keys_snapshot(entry: ConfigEntry) -> tuple:
    """Tuple of values for reload-requiring keys, comparable across calls."""
    data = entry.data
    return tuple(
        tuple(data.get(k)) if isinstance(data.get(k), list) else data.get(k)
        for k in _RELOAD_REQUIRING_KEYS
    )


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config-entry data changes WITHOUT a full reload when possible.

    The original v0.2.3 listener called ``async_reload`` unconditionally on
    every entry update. That tore down and re-registered the side panel each
    time anyone took a dose, edited a medicine, or any subentry shuffle
    occurred — which races with HA's own router when the user is sitting on
    the panel and produces an ``InvalidStateError`` that leaves the panel
    disconnected from the DOM until full page reload.

    Now: compare a snapshot of reload-requiring keys (panel visibility,
    source URLs/credentials) before vs after. Only call async_reload when
    one of those genuinely changed. For routine subentry edits and dose
    actions, just refresh the coordinator's medicine list — same effect as
    a reload from the user's perspective, no panel disconnect.
    """
    bucket = hass.data[DOMAIN][entry.entry_id]
    new_snapshot = _reload_keys_snapshot(entry)
    old_snapshot = bucket.get("reload_keys_snapshot")
    if new_snapshot != old_snapshot:
        # A reload-requiring setting changed: do the full reload.
        bucket["reload_keys_snapshot"] = new_snapshot
        await hass.config_entries.async_reload(entry.entry_id)
        return
    # Routine update — just refresh medicines; leave panel registration
    # alone. v0.2.14 removed the source-rebuild branch (no built-in
    # sources to rebuild).
    coord: MedicineCoordinator = bucket["coordinator"]
    coord.update_medicines(_medicines_from_subentries(entry))
    await coord.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        bucket = hass.data[DOMAIN].pop(entry.entry_id, None)
        if bucket:
            await bucket["coordinator"].async_close()
        await async_unregister_panel(hass)
    return unload_ok


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_MARK_TAKEN):
        return

    async def _resolve(medicine_id: str) -> MedicineCoordinator | None:
        # ``hass.data[DOMAIN]`` mixes per-entry buckets (dicts keyed by
        # entry_id, holding "coordinator" + "reload_keys_snapshot") with
        # the ``"medicine_db"`` singleton (a MedicineDatabase instance,
        # added in v0.2.15). The isinstance guard skips non-bucket values
        # — without it ``bucket["coordinator"]`` raises
        # ``'MedicineDatabase' object is not subscriptable`` and breaks
        # all three dose services. ``bucket.get("coordinator")`` (vs
        # ``bucket["coordinator"]``) gives one more layer of safety in
        # case a future bucket is added without a coordinator key.
        for bucket in hass.data.get(DOMAIN, {}).values():
            if not isinstance(bucket, dict):
                continue
            coord: MedicineCoordinator | None = bucket.get("coordinator")
            if coord is not None and coord.data and medicine_id in coord.data:
                return coord
        return None

    async def handle_mark_taken(call: ServiceCall) -> None:
        med_id = call.data["medicine_id"]
        person_id: str | None = call.data.get("person_id")
        when: datetime | None = call.data.get("when")
        scheduled_for: datetime | None = call.data.get("scheduled_for")
        coord = await _resolve(med_id)
        if coord:
            await coord.async_mark_taken(
                med_id, when=when, scheduled_for=scheduled_for, person_id=person_id
            )

    async def handle_skip(call: ServiceCall) -> None:
        med_id = call.data["medicine_id"]
        person_id: str | None = call.data.get("person_id")
        scheduled_for: datetime | None = call.data.get("scheduled_for")
        coord = await _resolve(med_id)
        if coord:
            await coord.async_skip(
                med_id, scheduled_for=scheduled_for, person_id=person_id
            )

    async def handle_snooze(call: ServiceCall) -> None:
        med_id = call.data["medicine_id"]
        person_id: str | None = call.data.get("person_id")
        coord = await _resolve(med_id)
        if coord:
            await coord.async_snooze(
                med_id, call.data["minutes"], person_id=person_id
            )

    async def handle_unmark_taken(call: ServiceCall) -> None:
        """Remove the most recent ``taken`` record for a medicine.

        The panel calls this from the per-dose hover-undo and the
        per-person ``Undo last action`` menu item. It always passes
        ``scheduled_for`` so the right slot gets undone for medicines
        with multiple times per day.

        v0.2.24: accepts optional ``person_id`` so undo on a
        multi-prescription medicine is restricted to that person's
        records.
        """
        med_id = call.data["medicine_id"]
        person_id: str | None = call.data.get("person_id")
        scheduled_for: datetime | None = call.data.get("scheduled_for")
        coord = await _resolve(med_id)
        if coord:
            await coord.async_unmark_taken(
                med_id, scheduled_for=scheduled_for, person_id=person_id
            )

    async def handle_refresh_medicines_database(call: ServiceCall) -> None:
        """Pull a fresh copy of medicines_se.json from the configured URL.

        URL is read from the integration entry's data
        (``medicines_db_url``); falls back to ``DEFAULT_MEDICINES_DB_URL``.
        On success the in-memory cache is updated immediately — the
        autocomplete dropdown picks up the new entries the next time
        the Add Medicine form is opened. No reload required.
        """
        medicine_db: MedicineDatabase | None = hass.data.get(DOMAIN, {}).get(
            "medicine_db"
        )
        if medicine_db is None:
            _LOGGER.warning(
                "refresh_medicines_database called before integration setup"
            )
            return
        # Resolve URL: per-call override beats per-entry config beats default.
        url = call.data.get("url")
        if not url:
            for entry_id, bucket in hass.data[DOMAIN].items():
                if not isinstance(bucket, dict):
                    continue
                # Fish the entry out of HA's registry to read entry.data
                cfg = hass.config_entries.async_get_entry(entry_id)
                if cfg is not None:
                    url = cfg.data.get(CONF_MEDICINES_DB_URL)
                    if url:
                        break
        url = url or DEFAULT_MEDICINES_DB_URL
        ok, msg = await medicine_db.async_refresh_from_url(url)
        if ok:
            _LOGGER.info("Medicines list refreshed: version %s", msg)
        else:
            _LOGGER.warning("Medicines list refresh failed: %s", msg)

    hass.services.async_register(
        DOMAIN, SERVICE_MARK_TAKEN, handle_mark_taken, schema=MARK_TAKEN_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SKIP, handle_skip, schema=SKIP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SNOOZE, handle_snooze, schema=SNOOZE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNMARK_TAKEN,
        handle_unmark_taken,
        schema=UNMARK_TAKEN_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_MEDICINES_DATABASE,
        handle_refresh_medicines_database,
        schema=REFRESH_MEDICINES_DB_SCHEMA,
    )


# ---------------------------------------------------------------------------
# WebSocket commands (v0.2.21)
# ---------------------------------------------------------------------------
#
# The panel pushes medicine edits + new medicine creation back to the
# integration via two custom websocket commands:
#
#   * pillpilot/update_medicine — replaces an existing subentry's data.
#     Match-by-id semantics on prescriptions: existing prescriptions
#     update, new ones are added, missing ones are deleted.
#
#   * pillpilot/create_medicine — creates a new subentry with one or
#     more prescriptions in a single round trip.
#
# Both take the multi-prescription nested input shape:
#
#   data: {
#     drug: {name, type, notes, atc_code, npl_id, varunummer},
#     prescriptions: [{id?, person_id, unit_count, ...}, ...]
#   }
#
# On validation failure both return:
#
#   {success: False, errors: {drug: {...}, prescriptions: [{...}, ...], base: ""}}
#
# Returning errors as a successful WS result (vs send_error) keeps the
# error path uniform — the panel always parses ``result.errors`` instead
# of having to disambiguate "validation failed" from "WS protocol error".
#
# Note: HA Settings reconfigure flow uses the single-prescription
# validate_medicine_input + merge_v2_form_into_existing in config_flow.py.
# That codepath is unchanged.


# ---------------------------------------------------------------------------
# pillpilot/update_medicine — WS command for the panel-side Edit modal
# ---------------------------------------------------------------------------
#
# Updates an existing medicine subentry from the panel's edit modal.
# Takes the multi-prescription nested input shape:
#
#   {
#     medicine_id: "<existing-medicine-id>",
#     data: {
#       drug: {name, type, notes, atc_code, npl_id, varunummer},
#       prescriptions: [
#         {id?, person_id, unit_count, unit_strength_mg, frequency, ...},
#         ...
#       ]
#     }
#   }
#
# Match-by-id semantics on prescriptions:
#   * prescription with id present in stored → update
#   * prescription with new id (or no id) → add
#   * stored prescription whose id absent from form → DELETE
#
# Returns the same uniform shape as create_medicine:
#   * {success: True}
#   * {success: False, errors: {drug: {...}, prescriptions: [{...}, ...], base: "..."}}
#
# Note: the HA Settings reconfigure flow uses validate_medicine_input +
# merge_v2_form_into_existing (single-prescription, preserves id of the
# first prescription). That codepath is unchanged. Only the panel-side
# WS command uses the multi-prescription shape.


@websocket_api.websocket_command(
    {
        vol.Required("type"): "pillpilot/update_medicine",
        vol.Required("medicine_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def _ws_update_medicine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Update a medicine subentry from the panel's edit modal."""
    medicine_id: str = msg["medicine_id"]
    payload: dict[str, Any] = msg["data"] or {}
    drug: dict[str, Any] = payload.get("drug") or {}
    prescriptions: list[dict[str, Any]] = payload.get("prescriptions") or []

    # 1. Locate the subentry by medicine_id (which IS the subentry_id —
    # see _medicines_from_subentries).
    target_entry: ConfigEntry | None = None
    target_subentry: ConfigSubentry | None = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        sub = entry.subentries.get(medicine_id)
        if sub is not None and sub.subentry_type == SUBENTRY_TYPE_MEDICINE:
            target_entry = entry
            target_subentry = sub
            break

    if target_entry is None or target_subentry is None:
        connection.send_result(
            msg["id"],
            {"success": False, "errors": {"base": "medicine_not_found"}},
        )
        return

    # 2. Validate via the multi-prescription helper.
    med, errors = validate_medicine_input_multi(hass, drug, prescriptions)
    if med is None:
        connection.send_result(
            msg["id"], {"success": False, "errors": errors}
        )
        return

    # 3. Merge by prescription id. Drug-identity fields from `med`
    # override existing; prescriptions match by id (update / add / delete).
    drug_identity = {k: v for k, v in med.items() if k != CONF_MED_PRESCRIPTIONS}
    new_data = merge_v2_prescriptions_into_existing(
        drug_identity,
        med[CONF_MED_PRESCRIPTIONS],
        dict(target_subentry.data),
    )
    # CONF_MED_ID is not persisted in subentry data — the canonical
    # identity is the subentry_id, which HA owns. Strip any stale value
    # in case the merge carried one over from older code paths.
    new_data.pop(CONF_MED_ID, None)
    new_title = build_subentry_title(hass, new_data)
    try:
        hass.config_entries.async_update_subentry(
            target_entry,
            target_subentry,
            data=new_data,
            title=new_title,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Update subentry failed for %s", medicine_id)
        connection.send_result(
            msg["id"],
            {"success": False, "errors": {"base": "update_failed"}},
        )
        return

    # 4. Refresh the coordinator. NOT async_reload — full reload tears
    # down and re-registers the side panel, which races with HA's router
    # when the user is sitting on the panel mid-edit and produces an
    # InvalidStateError that leaves the panel disconnected until full
    # page reload. The routine refresh path gives identical visible
    # behavior with no panel disconnect.
    bucket = hass.data[DOMAIN].get(target_entry.entry_id)
    if bucket and bucket.get("coordinator"):
        coord: MedicineCoordinator = bucket["coordinator"]
        coord.update_medicines(_medicines_from_subentries(target_entry))
        await coord.async_request_refresh()
    connection.send_result(msg["id"], {"success": True})


# ---------------------------------------------------------------------------
# pillpilot/create_medicine — WS command for the panel-side Add modal
# ---------------------------------------------------------------------------
#
# Creates a new medicine subentry with one or more prescriptions in a
# single round trip. Mirrors what HA's SubentryFlow does when the user
# clicks "+ Add medicine" in Settings, but takes the multi-prescription
# nested input shape the panel modal produces:
#
#   {
#     "drug": {name, type, notes, atc_code, npl_id, varunummer},
#     "prescriptions": [{person_id, unit_count, ..., times, days}, ...]
#   }
#
# Returns:
#   * {success: True, medicine_id: "..."} — created
#   * {success: False, errors: {drug: {...}, prescriptions: [{...}, ...], base: "..."}}
#
# Same uniform error shape as _ws_update_medicine: errors come back as
# a successful WS result so the panel parses one path.


@websocket_api.websocket_command(
    {
        vol.Required("type"): "pillpilot/create_medicine",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def _ws_create_medicine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Create a new medicine subentry from the panel's add modal."""
    payload: dict[str, Any] = msg["data"] or {}
    drug: dict[str, Any] = payload.get("drug") or {}
    prescriptions: list[dict[str, Any]] = payload.get("prescriptions") or []

    # 1. Locate the PillPilot config entry to attach the new subentry to.
    # There's normally exactly one entry per HA install. Fail loud if the
    # invariant is broken.
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(
            msg["id"],
            {"success": False, "errors": {"base": "no_pillpilot_entry"}},
        )
        return
    if len(entries) > 1:
        _LOGGER.warning(
            "PillPilot: %d config entries found; create_medicine attaches to "
            "the first. This is unexpected — investigate why multiple entries "
            "exist.", len(entries),
        )
    target_entry = entries[0]

    # 2. Validate via the multi-prescription helper.
    med, errors = validate_medicine_input_multi(hass, drug, prescriptions)
    if med is None:
        connection.send_result(
            msg["id"], {"success": False, "errors": errors}
        )
        return

    # 3. Persist as a new ConfigSubentry. HA assigns subentry_id on
    # construction; that is the canonical medicine_id and is what the
    # rest of the integration looks up by. CONF_MED_ID is not stored in
    # data — _medicines_from_subentries injects it from sub.subentry_id.
    # ``unique_id`` is required by the ConfigSubentry dataclass (no
    # default), but None is a valid value — the subentry_id alone
    # identifies this medicine.
    title = build_subentry_title(hass, med)
    new_sub = ConfigSubentry(
        data=med,
        subentry_type=SUBENTRY_TYPE_MEDICINE,
        title=title,
        unique_id=None,
    )
    try:
        hass.config_entries.async_add_subentry(target_entry, new_sub)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Create medicine failed")
        connection.send_result(
            msg["id"],
            {"success": False, "errors": {"base": "create_failed"}},
        )
        return
    medicine_id = new_sub.subentry_id

    # 4. Refresh the coordinator so the new medicine shows up immediately
    # in sensors and panel without waiting for the next tick. Same
    # "rebuild medicines list, refresh, no async_reload" pattern as
    # _ws_update_medicine — full reload would tear down the panel.
    bucket = hass.data[DOMAIN].get(target_entry.entry_id)
    if bucket and bucket.get("coordinator"):
        coord: MedicineCoordinator = bucket["coordinator"]
        coord.update_medicines(_medicines_from_subentries(target_entry))
        await coord.async_request_refresh()

    connection.send_result(
        msg["id"], {"success": True, "medicine_id": medicine_id}
    )


# ---------------------------------------------------------------------------
# pillpilot/delete_medicine — remove a medicine subentry from the panel
# ---------------------------------------------------------------------------
#
# Mirrors the "Delete" button on HA Settings → Integrations → PillPilot
# but lives in the panel's Edit modal so users don't have to leave the
# panel to remove a medicine. Cascade-removal of the medicine's sensor
# entity and any per-medicine devices is handled automatically by HA
# because the entity is registered with config_subentry_id.


@websocket_api.websocket_command(
    {
        vol.Required("type"): "pillpilot/delete_medicine",
        vol.Required("medicine_id"): cv.string,
    }
)
@websocket_api.async_response
async def _ws_delete_medicine(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Remove a medicine subentry by id."""
    medicine_id: str = msg["medicine_id"]

    target_entry: ConfigEntry | None = None
    target_subentry: ConfigSubentry | None = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        sub = entry.subentries.get(medicine_id)
        if sub is not None and sub.subentry_type == SUBENTRY_TYPE_MEDICINE:
            target_entry = entry
            target_subentry = sub
            break

    if target_entry is None or target_subentry is None:
        connection.send_result(
            msg["id"],
            {"success": False, "errors": {"base": "medicine_not_found"}},
        )
        return

    # HA's `async_remove_subentry` in the current API is a sync
    # @callback that removes the subentry from the entry and triggers
    # registry cleanup via update listeners. It mirrors the calling
    # convention of `async_update_subentry` already used in this file:
    # pass the subentry object, no await. (Despite the `async_` prefix,
    # this family of methods on ConfigEntries are callbacks — `async_`
    # here means "must be called from the event loop", not coroutine.)
    try:
        hass.config_entries.async_remove_subentry(
            target_entry, target_subentry.subentry_id
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.exception("Delete medicine failed for %s", medicine_id)
        connection.send_result(
            msg["id"],
            {
                "success": False,
                "errors": {"base": "delete_failed"},
                # Surface the underlying exception to the panel so the
                # user (and we) can see what HA actually complained
                # about, instead of a generic "delete_failed".
                "error_detail": f"{type(exc).__name__}: {exc}",
            },
        )
        return

    # Refresh coordinator so the deleted med disappears from sensors and
    # the panel without waiting for the next tick. Same pattern as create
    # / update — entry-update listener also fires but the explicit refresh
    # narrows the visible delay.
    bucket = hass.data[DOMAIN].get(target_entry.entry_id)
    if bucket and bucket.get("coordinator"):
        coord: MedicineCoordinator = bucket["coordinator"]
        coord.update_medicines(_medicines_from_subentries(target_entry))
        await coord.async_request_refresh()

    connection.send_result(msg["id"], {"success": True})


# ---------------------------------------------------------------------------
# pillpilot/get_medicines_db — read-only catalog access for the panel modal
# ---------------------------------------------------------------------------
#
# The panel-side Add/Edit modal uses this to populate its drug-name
# autocomplete and to auto-fill ATC code + active substance when the
# user picks a known entry. The HA Settings config-flow path uses the
# same MedicineDatabase singleton via lookup_by_name.
#
# Returns:
#   {success: True, list_version: "...", medicines: [{name, aliases,
#    active_substance, atc_code}, ...]}
#
# If the integration's medicine DB hasn't loaded yet (rare — only at
# very early boot), returns an empty list rather than failing, so the
# panel's autocomplete just falls back to "names of meds you've already
# added" instead of breaking the modal.


@websocket_api.websocket_command(
    {
        vol.Required("type"): "pillpilot/get_medicines_db",
    }
)
@websocket_api.async_response
async def _ws_get_medicines_db(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return the in-memory medicines catalog for panel autocomplete."""
    medicine_db: MedicineDatabase | None = (
        hass.data.get(DOMAIN, {}).get("medicine_db")
    )
    if medicine_db is None:
        connection.send_result(
            msg["id"],
            {"success": True, "list_version": "unknown", "medicines": []},
        )
        return
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "list_version": medicine_db.list_version,
            "medicines": sanitize_for_ws(medicine_db.medicines),
        },
    )


@callback
def _register_websocket_commands(hass: HomeAssistant) -> None:
    """Register PillPilot's websocket commands once per HA lifetime.

    Idempotent: HA's ``async_register_command`` raises on double-register
    in some versions, so we gate on a sentinel in ``hass.data[DOMAIN]``.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("ws_commands_registered"):
        return
    websocket_api.async_register_command(hass, _ws_update_medicine)
    websocket_api.async_register_command(hass, _ws_create_medicine)
    websocket_api.async_register_command(hass, _ws_delete_medicine)
    websocket_api.async_register_command(hass, _ws_get_medicines_db)
    domain_data["ws_commands_registered"] = True
