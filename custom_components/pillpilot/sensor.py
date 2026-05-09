"""Sensor platform: one entity per medicine."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MedicineCoordinator, MedicineState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add medicine sensors and keep the entity/device registries in sync.

    Each medicine is a config subentry; the entity gets registered with
    its subentry via ``config_subentry_id`` so HA can clean up the
    entity automatically when the subentry is removed (deleted from
    the integration card). On every coordinator tick we still diff
    current vs. known to handle in-flight additions and to clean up
    empty per-person devices.
    """
    coordinator: MedicineCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    known_ids: set[str] = set()

    @callback
    def _sync_entities() -> None:
        current_ids = set((coordinator.data or {}).keys())
        to_add = current_ids - known_ids
        to_remove = known_ids - current_ids

        if to_add:
            # Every medicine's id IS the subentry_id (see
            # _medicines_from_subentries in __init__.py), so the link
            # is direct. config_subentry_id ties the entity to the
            # subentry so HA cleans up the entity automatically when
            # the subentry is deleted.
            subentry_ids = set(entry.subentries.keys())
            for med_id in to_add:
                if med_id not in subentry_ids:
                    _LOGGER.error(
                        "PillPilot: coordinator emitted med_id %s with no "
                        "matching subentry — skipping entity creation",
                        med_id,
                    )
                    continue
                async_add_entities(
                    [MedicineSensor(coordinator, med_id)],
                    config_subentry_id=med_id,
                )
            known_ids.update(to_add)

        if to_remove:
            ent_reg = er.async_get(hass)
            for med_id in to_remove:
                unique_id = f"{DOMAIN}_{med_id}"
                entity_id = ent_reg.async_get_entity_id(
                    "sensor", DOMAIN, unique_id
                )
                if entity_id:
                    ent_reg.async_remove(entity_id)
            known_ids.difference_update(to_remove)
            _cleanup_empty_devices(hass, entry)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


@callback
def _cleanup_empty_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove devices belonging to this entry that have no entities left.

    PillPilot creates one device per ``person.*`` plus a shared
    "Household Medicines" device. When you delete the last medicine
    assigned to Alice, her device becomes empty — we want it gone, not
    lingering as an orphan in the UI.
    """
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    for device in list(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)):
        remaining = er.async_entries_for_device(
            ent_reg, device.id, include_disabled_entities=True
        )
        if not remaining:
            dev_reg.async_remove_device(device.id)


class MedicineSensor(CoordinatorEntity[MedicineCoordinator], SensorEntity):
    """One entity per medicine. Grouped under a per-person 'device' in HA."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MedicineCoordinator, medicine_id: str) -> None:
        super().__init__(coordinator)
        self._medicine_id = medicine_id
        self._attr_unique_id = f"{DOMAIN}_{medicine_id}"
        self._attr_icon = "mdi:pill"

    @property
    def _state(self) -> MedicineState | None:
        return (self.coordinator.data or {}).get(self._medicine_id)

    @property
    def name(self) -> str | None:
        s = self._state
        return s.name if s else None

    @property
    def native_value(self) -> str | None:
        s = self._state
        return s.last_state if s else None

    @property
    def device_info(self) -> DeviceInfo:
        """Group all of a person's medicines under one HA device.

        Medicines without an assigned person fall under a shared
        "Household Medicines" device.
        """
        s = self._state
        person_id = s.person_id if s else None
        if person_id:
            owner = s.person_name or person_id
            return DeviceInfo(
                identifiers={(DOMAIN, f"person:{person_id}")},
                name=f"{owner}'s Medicines",
                manufacturer="PillPilot",
                model="Per-person medicine schedule",
                entry_type=DeviceEntryType.SERVICE,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, "household")},
            name="Household Medicines",
            manufacturer="PillPilot",
            model="Shared medicine schedule",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._state
        if not s:
            return {}
        attrs: dict[str, Any] = {
            "medicine_id": s.id,
            # The bare medicine name (e.g. "Levaxin"). Distinct from
            # ``friendly_name`` which HA constructs by prefixing with
            # the device name (e.g. "Sam's Medicines Levaxin"). The
            # panel uses this attribute so its rows aren't cluttered
            # with the device prefix; HA-native dialogs continue to
            # use friendly_name where the device context is helpful.
            "medicine_name": s.name,
            "med_type": s.med_type,
            "notes": s.notes,
            # Full per-prescription detail. The panel reads this to render
            # multi-prescription medicines. Each prescription has a stable
            # `id` that frontend uses as the merge key when sending updates
            # back to the WS commands.
            "prescriptions": [
                {
                    "id": p.id,
                    "person_id": p.person_id,
                    "person_name": p.person_name,
                    "dose": p.dose,
                    "unit_count": p.unit_count,
                    "unit_strength_mg": p.unit_strength_mg,
                    "total_dose_mg": p.total_dose_mg,
                    "frequency": p.frequency,
                    "scheduled_times": p.times,
                    "scheduled_days": p.days,
                    "scheduled_days_of_month": p.days_of_month,
                    "interval_days": p.interval_days,
                    "ends_on": p.ends_on,
                    "starts_on": p.starts_on,
                    "times_per_weekday": p.times_per_weekday,
                    "remind_window_minutes": p.remind_window_minutes,
                    "next_dose_at": _iso(p.next_dose_at),
                    "last_taken_at": _iso(p.last_taken_at),
                    "today_doses": p.today_doses,
                    "state": p.state,
                }
                for p in s.prescriptions
            ],
            # ---- backward-compat flat fields (read from prescriptions[0]) ----
            # Existing automations / blueprints / panel.js read these
            # exact attribute names. v0.2.24 keeps them populated from
            # the first prescription so nothing breaks. After v0.2.25
            # ships the per-prescription UI, these stay as the sensible
            # default for "the medicine's current state at a glance"
            # — they collapse a multi-prescription medicine to the
            # first person's view, which matches how a single-person
            # household would experience it.
            "unit_count": s.unit_count,
            "unit_strength_mg": s.unit_strength_mg,
            "total_dose_mg": s.total_dose_mg,
            "dose": s.dose,
            "scheduled_times": s.times,
            "scheduled_days": s.days,
            # expose frequency + monthly days so the panel can
            # render the schedule correctly. Pre-v0.2.19 the panel
            # blindly printed "Daily · ..." for every medicine because
            # those attributes weren't reachable, leading to weekly /
            # monthly entries being mislabeled as daily on their cards.
            "frequency": s.frequency,
            "scheduled_days_of_month": s.days_of_month,
            # surfaced so the in-panel edit modal pre-fills the
            # existing value instead of resetting to the default.
            "remind_window_minutes": s.remind_window_minutes,
            "next_dose_at": _iso(s.next_dose_at),
            "last_taken_at": _iso(s.last_taken_at),
            "person_id": s.person_id,         # may be None for household
            "person_name": s.person_name,     # friendly name, or None
            # Per-slot status for today's doses. The
            # panel uses this to decide whether each slot's row shows
            # action buttons or a "✓ Taken at HH:MM" label.
            "today_doses": s.today_doses,
        }
        if s.npl_id:
            attrs["npl_id"] = s.npl_id
        if s.varunummer:
            attrs["varunummer"] = s.varunummer
        if s.atc_code:
            attrs["atc_code"] = s.atc_code
        if s.enrichment:
            for src_id, payload in s.enrichment.items():
                attrs[f"source_{src_id}"] = payload
            attrs["info"] = _flatten(s.enrichment)
        return attrs

    @property
    def available(self) -> bool:
        return self._state is not None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _flatten(enrichment: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """First-non-empty wins, in the order sources happened to register.

    Pre-v0.2.14 this iterated a hard-coded ``("vara", "fass", "rms")``
    priority. Those built-in sources are gone — we now just iterate
    the enrichment dict in insertion order, which is the order
    ``build_sources`` returned them. With no sources registered the
    output is empty.
    """
    keys = (
        "name",
        "strength",
        "pharmaceutical_form",
        "route_of_administration",
        "atc_code",
        "atc_label",
        "active_substances",
        "manufacturer",
        "pack_size",
        "narcotic",
    )
    out: dict[str, Any] = {}
    for k in keys:
        for payload in enrichment.values():
            if payload and payload.get(k) not in (None, "", []):
                out[k] = payload[k]
                break
    return out
