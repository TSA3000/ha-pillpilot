"""
Coordinator: tick every minute, evaluate medicine schedules, fire bus
events, persist history, and (when sources are registered) enrich each
medicine via every source.

No built-in sources ship — ``self._sources`` is an empty list and the
enrichment loop is a no-op. The plumbing is kept for future source
plug-ins.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MED_ATC_CODE,
    CONF_MED_CYCLE_ANCHOR,
    CONF_MED_CYCLE_OFF_DAYS,
    CONF_MED_CYCLE_ON_DAYS,
    CONF_MED_DAYS,
    CONF_MED_DAYS_OF_MONTH,
    CONF_MED_DOSE,
    CONF_MED_ENDS_ON,
    CONF_MED_STARTS_ON,
    CONF_MED_FREQUENCY,
    CONF_MED_ID,
    CONF_MED_NAME,
    CONF_MED_NOTES,
    CONF_MED_NPL_ID,
    CONF_MED_PERSON,
    CONF_MED_PRESCRIPTIONS,
    CONF_MED_REMIND_WINDOW,
    CONF_MED_RRULE,
    CONF_MED_SCHEDULE_TYPE,
    CONF_MED_TIMES,
    CONF_MED_TIMES_PER_WEEKDAY,
    CONF_MED_TYPE,
    CONF_MED_UNIT_COUNT,
    CONF_MED_VARIANT_FORM,
    CONF_MED_VARIANT_NPL_ID,
    CONF_MED_VARIANT_STRENGTH,
    CONF_MED_VARUNUMMER,
    CONF_MEDICINES,
    CONF_PRESCRIPTION_ID,
    CONF_STOCK_EXPIRY,
    CONF_STOCK_PACK_SIZE,
    CONF_STOCK_REMINDER_ENABLED,
    CONF_STOCK_REMINDER_MODE,
    CONF_STOCK_REMINDER_THRESHOLD,
    CONF_STOCK_TRACK,
    DEFAULT_REMIND_WINDOW,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STOCK_EXPIRY_LEAD_DAYS,
    DEFAULT_STOCK_REMINDER_MODE,
    DOMAIN,
    EVENT_DOSE_DUE,
    EVENT_DOSE_MISSED,
    EVENT_DOSE_SKIPPED,
    EVENT_DOSE_SNOOZED,
    EVENT_DOSE_TAKEN,
    EVENT_DOSE_UNMARKED,
    EVENT_STOCK_EXPIRED,
    EVENT_STOCK_EXPIRING,
    EVENT_STOCK_LOW,
    FREQ_DAILY,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    MED_TYPE_DROPS,
    MED_TYPE_INJECTION,
    MED_TYPE_PILL,
    SCHEDULE_TYPE_DAILY,
    SCHEDULE_TYPE_INTERVAL,
    SCHEDULE_TYPE_MONTHLY,
    SCHEDULE_TYPE_WEEKLY,
    SOURCE_LOOKUP_TTL,
    STATE_DUE,
    STATE_MISSED,
    STATE_SKIPPED,
    STATE_SNOOZED,
    STATE_TAKEN,
    STATE_UPCOMING,
    STOCK_EVENT_ADD,
    STOCK_EVENT_REFILL,
    STOCK_EVENT_REMOVE,
    STOCK_EVENT_SET,
    STOCK_REMINDER_MODES,
    STOCK_RUNOUT_LOOKAHEAD_DAYS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .sources import LookupKey, LookupResult, MedicineSource
from .schedule import Schedule, rrule_to_friendly
from .dose import Dose
from .stock import (
    StockEvent,
    current_stock,
    expiry_status,
    is_low,
    project_runout,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DoseRecord:
    medicine_id: str
    scheduled_for: str
    # per-prescription routing. For multi-prescription medicines
    # we need to know WHICH prescription a record belongs to — Sam and
    # Josef sharing Levaxin both have 8am slots, the record needs to
    # disambiguate. Default None for legacy records loaded from storage
    # that pre-date this field. New records always populate it from the
    # prescription resolver.
    person_id: str | None = None
    taken_at: str | None = None
    skipped_at: str | None = None
    missed_at: str | None = None
    # v0.2.7: ISO timestamp of when the snooze expires. Set by
    # async_snooze on the record for the original scheduled slot
    # (matched on scheduled_for, not on a new synthetic time). The
    # tick re-fires EVENT_DOSE_DUE once now >= snoozed_until and the
    # slot is still untaken/unskipped. A snooze record without
    # taken_at/skipped_at is "open"; once the user takes or skips,
    # the same record gets stamped with taken_at/skipped_at and the
    # snooze fields stay as historical breadcrumb.
    snoozed_until: str | None = None
    # v0.3.0: which prescription this record belongs to. Populated at
    # action time from the resolved prescription's id; backfilled on load
    # for records that pre-date the field by matching person_id to the
    # medicine's single prescription for that person. Makes per-prescription
    # stock attribution and same-person disambiguation exact rather than
    # first-match on person_id.
    prescription_id: str | None = None
    # v0.3.0: units removed from stock when this dose was taken (the
    # prescription's unit_count at take time). Stored on the record so the
    # figure survives later edits to the dose size. None on non-taken
    # records and on taken records that pre-date the field.
    units_consumed: float | None = None


@dataclass
class PrescriptionState:
    """One prescription's worth of state — person, dose, schedule, today.

    A medicine has one or more prescriptions; this struct holds the
    per-prescription tick output. The aggregated MedicineState references
    a list of these.
    """
    id: str
    person_id: str | None
    person_name: str | None
    dose: str
    unit_count: float
    variant_strength: str
    variant_form: str
    variant_npl_id: str | None
    total_dose_mg: float | None
    frequency: str
    times: list[str]
    days: list[int]
    days_of_month: list[int]
    remind_window_minutes: int
    next_dose_at: datetime | None
    last_taken_at: datetime | None
    state: str  # one of STATE_DUE / STATE_TAKEN / STATE_MISSED / STATE_SKIPPED / STATE_UPCOMING
    today_doses: list[dict[str, Any]] = field(default_factory=list)
    # v0.2.0 schedule modes beyond legacy daily/weekly/monthly. None
    # for prescriptions on those legacy modes; populated for interval
    # mode (and later cycle / custom modes).
    interval_days: int | None = None
    ends_on: str | None = None  # ISO "YYYY-MM-DD" or None
    starts_on: str | None = None  # ISO "YYYY-MM-DD" or None — interval anchor
    # times_per_weekday is the WS-friendly shape (list of 7 lists of
    # HH:MM strings) — what panel.js consumes via sensor attributes.
    # None means simple mode (use ``times`` for every firing day).
    times_per_weekday: list[list[str]] | None = None
    # v0.3.0: stock / inventory. All null/absent unless track_stock is on
    # for this prescription. stock is derived (never stored); packs_left is
    # the pack-equivalent for injection display; run_out_date / expiry_date
    # are ISO dates.
    track_stock: bool = False
    stock: float | None = None
    stock_unit: str | None = None
    pack_size: float | None = None
    packs_left: float | None = None
    doses_left: int | None = None
    days_left: int | None = None
    run_out_date: str | None = None
    expiry_date: str | None = None
    low_stock: bool = False
    reminder_enabled: bool = False
    reminder_mode: str | None = None
    reminder_threshold: float | None = None


@dataclass
class MedicineState:
    """Top-level state for a medicine.

    v0.2.24: split into drug-identity (top-level fields) and
    prescriptions (the list). Backward-compat properties expose the
    flat fields existing callers (sensor.py attributes, panel.js)
    expect — they read from prescriptions[0]. With one prescription
    (the migrated single-person case) this is identical to v0.2.23.
    With multiple prescriptions, callers that haven't been updated
    yet see the first one; v0.2.25 lights up the multi-prescription
    UI and updates those callers.
    """
    id: str
    name: str
    notes: str
    npl_id: str | None
    varunummer: str | None
    atc_code: str | None
    med_type: str | None
    enrichment: dict[str, dict[str, Any]]
    prescriptions: list[PrescriptionState]
    # v0.2.19: panel-level visibility metadata. The panel filters
    # _getMedicines() against these plus the current user. Sensor
    # state stays globally readable — HA entity permissions can't
    # filter per-user.
    visibility: str = "everyone"
    visibility_users: tuple[str, ...] = ()
    last_state: str = STATE_UPCOMING

    # ---- backward-compat properties (read from prescriptions[0]) -----
    # These look like fields to existing call sites but are computed.
    # When the caller wants to be explicit it can use ``for_person()``
    # or walk ``prescriptions`` directly.

    @property
    def person_id(self) -> str | None:
        return self.prescriptions[0].person_id if self.prescriptions else None

    @property
    def person_name(self) -> str | None:
        return self.prescriptions[0].person_name if self.prescriptions else None

    @property
    def dose(self) -> str:
        return self.prescriptions[0].dose if self.prescriptions else ""

    @property
    def unit_count(self) -> float:
        return self.prescriptions[0].unit_count if self.prescriptions else 0.0

    @property
    def variant_strength(self) -> str:
        return (
            self.prescriptions[0].variant_strength if self.prescriptions else ""
        )

    @property
    def variant_form(self) -> str:
        return (
            self.prescriptions[0].variant_form if self.prescriptions else ""
        )

    @property
    def variant_npl_id(self) -> str | None:
        return (
            self.prescriptions[0].variant_npl_id if self.prescriptions else None
        )

    @property
    def total_dose_mg(self) -> float | None:
        return (
            self.prescriptions[0].total_dose_mg if self.prescriptions else None
        )

    @property
    def frequency(self) -> str:
        return (
            self.prescriptions[0].frequency if self.prescriptions else FREQ_WEEKLY
        )

    @property
    def times(self) -> list[str]:
        return self.prescriptions[0].times if self.prescriptions else []

    @property
    def days(self) -> list[int]:
        return (
            self.prescriptions[0].days if self.prescriptions else list(range(7))
        )

    @property
    def days_of_month(self) -> list[int]:
        return self.prescriptions[0].days_of_month if self.prescriptions else []

    @property
    def remind_window_minutes(self) -> int:
        return (
            self.prescriptions[0].remind_window_minutes
            if self.prescriptions else DEFAULT_REMIND_WINDOW
        )

    @property
    def next_dose_at(self) -> datetime | None:
        return (
            self.prescriptions[0].next_dose_at if self.prescriptions else None
        )

    @property
    def last_taken_at(self) -> datetime | None:
        return (
            self.prescriptions[0].last_taken_at if self.prescriptions else None
        )

    @property
    def today_doses(self) -> list[dict[str, Any]]:
        return self.prescriptions[0].today_doses if self.prescriptions else []

    def for_person(
        self, person_id: str | None
    ) -> PrescriptionState | None:
        """Return the prescription for the given person_id, or None."""
        return next(
            (p for p in self.prescriptions if p.person_id == person_id),
            None,
        )

    @property
    def low_stock(self) -> bool:
        """True if any tracked prescription is below its refill threshold."""
        return any(
            p.track_stock and p.low_stock for p in self.prescriptions
        )


class MedicineCoordinator(DataUpdateCoordinator[dict[str, MedicineState]]):
    """Drives the schedule. data is keyed by medicine id."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        medicines: list[dict[str, Any]],
        sources: list[MedicineSource],
    ) -> None:
        # config_entry is required explicitly by HA 2026.8+ — implicit
        # detection is removed for coordinators.
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self._entry_id = entry.entry_id
        self._medicines_cfg = medicines
        self._sources = sources
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")
        self._history: dict[str, list[DoseRecord]] = {}
        # v0.3.0 stock state, persisted in the same Store. Both keyed
        # [medicine_id][prescription_id]. Config holds the per-prescription
        # track flag, pack size, reminder settings and expiry; events is the
        # ledger current stock is derived from.
        self._stock_config: dict[str, dict[str, dict[str, Any]]] = {}
        self._stock_events: dict[str, dict[str, list[StockEvent]]] = {}
        # enrichment cache: medicine_id -> {source_id -> (timestamp, LookupResult)}
        self._enrichment: dict[str, dict[str, tuple[datetime, LookupResult]]] = {}
        self._fired_due: set[tuple[str, str | None, str]] = set()
        self._fired_missed: set[tuple[str, str | None, str]] = set()
        # Fire-once guards for stock events, keyed (medicine_id, prescription_id).
        self._fired_stock_low: set[tuple[str, str]] = set()
        self._fired_stock_expiring: set[tuple[str, str]] = set()
        self._fired_stock_expired: set[tuple[str, str]] = set()

    # ---- lifecycle --------------------------------------------------

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if not raw:
            return
        for med_id, records in raw.get("history", {}).items():
            self._history[med_id] = [DoseRecord(**r) for r in records]
        for med_id, per_presc in raw.get("stock_config", {}).items():
            self._stock_config[med_id] = {
                pid: dict(cfg) for pid, cfg in per_presc.items()
            }
        for med_id, per_presc in raw.get("stock_events", {}).items():
            self._stock_events[med_id] = {
                pid: [StockEvent(**e) for e in events]
                for pid, events in per_presc.items()
            }
        self._backfill_prescription_ids()

    def _backfill_prescription_ids(self) -> None:
        """Attribute legacy dose records to a prescription.

        A record stored before v0.3.0 carries person_id but no
        prescription_id. Under the old one-prescription-per-person
        assumption a person maps to exactly one prescription on the
        medicine, so fill the id in from that. If a person now has more
        than one prescription on the medicine the record predates the
        split and is left unattributed (it won't decrement the new
        per-prescription stock).
        """
        for med_id, records in self._history.items():
            med = self._find(med_id)
            if not med:
                continue
            prescriptions = med.get(CONF_MED_PRESCRIPTIONS, [])
            for r in records:
                if r.prescription_id is not None:
                    continue
                matches = [
                    p for p in prescriptions
                    if (p.get(CONF_MED_PERSON) or None) == r.person_id
                ]
                if len(matches) == 1:
                    r.prescription_id = matches[0].get(CONF_PRESCRIPTION_ID)

    async def async_setup_sources(self) -> None:
        for src in self._sources:
            try:
                await src.async_setup()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Source %s setup failed: %s", src.id, err)

    async def async_close(self) -> None:
        for src in self._sources:
            try:
                await src.async_close()
            except Exception:  # noqa: BLE001, S110
                pass

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "history": {
                    med_id: [r.__dict__ for r in records]
                    for med_id, records in self._history.items()
                },
                "stock_config": {
                    med_id: {pid: dict(cfg) for pid, cfg in per_presc.items()}
                    for med_id, per_presc in self._stock_config.items()
                },
                "stock_events": {
                    med_id: {
                        pid: [e.__dict__ for e in events]
                        for pid, events in per_presc.items()
                    }
                    for med_id, per_presc in self._stock_events.items()
                },
            }
        )

    def update_medicines(self, medicines: list[dict[str, Any]]) -> None:
        self._medicines_cfg = medicines

    def update_sources(self, sources: list[MedicineSource]) -> None:
        self._sources = sources
        self._enrichment.clear()

    # ---- public actions --------------------------------------------

    def _resolve_prescription(
        self,
        med: dict[str, Any],
        person_id: str | None,
        when: datetime | None = None,
        prescription_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Pick the right prescription for an action.

        v0.3.0:
          0. If ``prescription_id`` is given, match it exactly — the
             unambiguous path used by the stock services and (later) the
             panel, including two prescriptions sharing one person.
        v0.2.24:
          1. If ``person_id`` is given, return that prescription (or
             None if no match).
          2. If the medicine has exactly one prescription, return it.
          3. Otherwise (multi-prescription, no person_id), pick the
             prescription whose closest scheduled time is nearest to
             ``when``. This gives a sensible default for legacy
             callers that haven't been updated to pass person_id —
             they'll usually be acting on the prescription "in
             context" anyway (the one that was just due).
        """
        prescriptions = med.get(CONF_MED_PRESCRIPTIONS, [])
        if not prescriptions:
            return None
        if prescription_id is not None:
            return next(
                (
                    p for p in prescriptions
                    if p.get(CONF_PRESCRIPTION_ID) == prescription_id
                ),
                None,
            )
        if person_id is not None:
            return next(
                (p for p in prescriptions if p.get(CONF_MED_PERSON) == person_id),
                None,
            )
        if len(prescriptions) == 1:
            return prescriptions[0]
        when = when or dt_util.now()
        best = None
        best_dist: float | None = None
        for p in prescriptions:
            sched = self._closest_scheduled(p, when)
            if sched is None:
                continue
            dist = abs((sched - when).total_seconds())
            if best_dist is None or dist < best_dist:
                best = p
                best_dist = dist
        return best or prescriptions[0]

    async def async_mark_taken(
        self,
        medicine_id: str,
        when: datetime | None = None,
        scheduled_for: datetime | None = None,
        person_id: str | None = None,
    ) -> None:
        """Record a dose as taken.

        ``scheduled_for`` lets callers (specifically the panel) pin the
        action to a specific slot — important when a medicine has
        several doses on the same day, otherwise the closest-scheduled
        guess can attribute the action to the wrong slot.

        v0.2.24: ``person_id`` lets callers pin to a specific
        prescription within a multi-prescription medicine. Optional
        for backward compatibility — if omitted the resolver picks
        the single prescription (single-prescription medicine) or
        the closest-by-time prescription (multi-prescription).
        """
        when = when or dt_util.now()
        if self._record_taken(medicine_id, when, scheduled_for, person_id):
            await self._async_save()
            # Immediate (not async_request_refresh) so the panel's pending
            # spinner clears as soon as the new state is computed. The
            # debounced variant can defer the push by up to the request-
            # refresh cooldown when an action lands near the periodic scan,
            # which read as "slow to register". The periodic scan and
            # source refreshes stay debounced — that's their purpose.
            await self.async_refresh()

    def _record_taken(
        self,
        medicine_id: str,
        when: datetime,
        scheduled_for: datetime | None,
        person_id: str | None,
    ) -> bool:
        """Build, append, and announce one taken-dose record.

        Returns True if a record was added. Does not save or refresh —
        callers batch those (single action saves + refreshes once; the
        bulk path saves + refreshes once for the whole set).
        """
        med = self._find(medicine_id)
        if not med:
            _LOGGER.warning("mark_taken: unknown medicine_id %s", medicine_id)
            return False
        prescription = self._resolve_prescription(med, person_id, when)
        if prescription is None:
            _LOGGER.warning(
                "mark_taken: no prescription matched for %s person_id=%s",
                medicine_id, person_id,
            )
            return False
        resolved_pid = prescription.get(CONF_MED_PERSON) or None
        scheduled = scheduled_for or self._closest_scheduled(prescription, when)
        record = DoseRecord(
            medicine_id=medicine_id,
            scheduled_for=scheduled.isoformat() if scheduled else when.isoformat(),
            person_id=resolved_pid,
            taken_at=when.isoformat(),
            prescription_id=prescription.get(CONF_PRESCRIPTION_ID),
            units_consumed=float(prescription.get(CONF_MED_UNIT_COUNT) or 0.0),
        )
        self._history.setdefault(medicine_id, []).append(record)
        self.hass.bus.async_fire(
            EVENT_DOSE_TAKEN,
            {
                "medicine_id": medicine_id,
                "name": med[CONF_MED_NAME],
                "taken_at": record.taken_at,
                "scheduled_for": record.scheduled_for,
                "person_id": resolved_pid,
                "person_name": self._person_name(resolved_pid),
            },
        )
        return True

    async def async_mark_taken_bulk(
        self, items: list[dict[str, Any]]
    ) -> None:
        """Record several doses as taken in one pass.

        ``items`` is a list of dicts with ``medicine_id`` (required),
        ``scheduled_for`` (ISO string or None), and ``person_id``
        (string or None). Records every matching dose, then saves and
        refreshes once for the whole set — one disk write and one
        recompute instead of N. Per-dose events still fire so
        automations behave the same as individual actions.
        """
        when = dt_util.now()
        recorded = False
        for item in items:
            medicine_id = item.get("medicine_id")
            if not medicine_id:
                continue
            raw_sched = item.get("scheduled_for")
            scheduled_for = (
                dt_util.parse_datetime(raw_sched)
                if isinstance(raw_sched, str)
                else raw_sched
            )
            if self._record_taken(
                medicine_id, when, scheduled_for, item.get("person_id")
            ):
                recorded = True
        if recorded:
            await self._async_save()
            await self.async_refresh()

    async def async_skip(
        self,
        medicine_id: str,
        scheduled_for: datetime | None = None,
        person_id: str | None = None,
    ) -> None:
        """Record a dose as skipped.

        ``scheduled_for`` lets callers pin to a specific slot; without
        it we fall back to the closest scheduled time (works for
        once-a-day medicines but ambiguous when there are several).
        v0.2.24: ``person_id`` lets callers pin to a specific
        prescription within a multi-prescription medicine.
        """
        med = self._find(medicine_id)
        if not med:
            return
        now = dt_util.now()
        prescription = self._resolve_prescription(med, person_id, now)
        if prescription is None:
            return
        resolved_pid = prescription.get(CONF_MED_PERSON) or None
        scheduled = scheduled_for or self._closest_scheduled(prescription, now)
        record = DoseRecord(
            medicine_id=medicine_id,
            scheduled_for=scheduled.isoformat() if scheduled else now.isoformat(),
            person_id=resolved_pid,
            skipped_at=now.isoformat(),
            prescription_id=prescription.get(CONF_PRESCRIPTION_ID),
        )
        self._history.setdefault(medicine_id, []).append(record)
        await self._async_save()
        self.hass.bus.async_fire(
            EVENT_DOSE_SKIPPED,
            {
                "medicine_id": medicine_id,
                "name": med[CONF_MED_NAME],
                "skipped_at": record.skipped_at,
                "scheduled_for": record.scheduled_for,
                "person_id": resolved_pid,
                "person_name": self._person_name(resolved_pid),
            },
        )
        await self.async_refresh()

    async def async_snooze(
        self,
        medicine_id: str,
        minutes: int,
        scheduled_for: datetime | None = None,
        person_id: str | None = None,
    ) -> None:
        """Push the next reminder back by N minutes.

        v0.2.7: writes ``snoozed_until`` onto the DoseRecord for the
        original scheduled slot (not a synthetic now+N slot — that
        was a no-op pre-0.2.7 because the synthetic time never
        matched the RRULE-derived schedule). If a record already
        exists for the slot (e.g. an earlier snooze on the same
        slot), update its ``snoozed_until``; else create a fresh
        snooze-only record.

        Clears ``_fired_due`` for the slot so the tick re-fires
        EVENT_DOSE_DUE once ``snoozed_until`` elapses. EVENT_DOSE_MISSED
        is permanently suppressed for any slot that's been snoozed —
        the user has already engaged.

        v0.2.24: ``person_id`` lets callers pin the snooze to a
        specific prescription. Without it we resolve to the closest
        prescription by time, mirroring mark_taken's behavior.
        """
        med = self._find(medicine_id)
        if not med:
            return
        now = dt_util.now()
        if self._record_snooze(medicine_id, minutes, scheduled_for, person_id, now):
            await self._async_save()
            await self.async_refresh()

    def _record_snooze(
        self,
        medicine_id: str,
        minutes: int,
        scheduled_for: datetime | None,
        person_id: str | None,
        now: datetime,
    ) -> bool:
        """Write (or update) a snooze on the slot's DoseRecord and
        announce it. No save / refresh — callers batch those."""
        med = self._find(medicine_id)
        if not med:
            return False
        prescription = self._resolve_prescription(med, person_id, now)
        if prescription is None:
            return False
        resolved_pid = prescription.get(CONF_MED_PERSON) or None
        scheduled = scheduled_for or self._closest_scheduled(prescription, now)
        if scheduled is None:
            return False
        sched_iso = scheduled.isoformat()
        snoozed_until_iso = (now + timedelta(minutes=minutes)).isoformat()

        history = self._history.setdefault(medicine_id, [])
        existing = next(
            (
                r for r in history
                if r.scheduled_for == sched_iso
                and r.person_id == resolved_pid
                and not r.taken_at
                and not r.skipped_at
            ),
            None,
        )
        if existing is not None:
            existing.snoozed_until = snoozed_until_iso
        else:
            history.append(
                DoseRecord(
                    medicine_id=medicine_id,
                    scheduled_for=sched_iso,
                    person_id=resolved_pid,
                    snoozed_until=snoozed_until_iso,
                    prescription_id=prescription.get(CONF_PRESCRIPTION_ID),
                )
            )

        # Clear the fired-due cache so DUE re-fires once the snooze
        # elapses. _fired_missed is intentionally not cleared — see
        # the per-tick gating in _build_prescription_state.
        self._fired_due.discard((medicine_id, resolved_pid, sched_iso))

        self.hass.bus.async_fire(
            EVENT_DOSE_SNOOZED,
            {
                "medicine_id": medicine_id,
                "name": med[CONF_MED_NAME],
                "scheduled_for": sched_iso,
                "snoozed_until": snoozed_until_iso,
                "minutes": minutes,
                "person_id": resolved_pid,
                "person_name": self._person_name(resolved_pid),
            },
        )
        return True

    async def async_snooze_bulk(
        self, items: list[dict[str, Any]], minutes: int
    ) -> None:
        """Snooze several doses by the same number of minutes in one
        pass — one save + one refresh for the whole set."""
        now = dt_util.now()
        recorded = False
        for item in items:
            medicine_id = item.get("medicine_id")
            if not medicine_id:
                continue
            raw_sched = item.get("scheduled_for")
            scheduled_for = (
                dt_util.parse_datetime(raw_sched)
                if isinstance(raw_sched, str)
                else raw_sched
            )
            if self._record_snooze(
                medicine_id, minutes, scheduled_for, item.get("person_id"), now
            ):
                recorded = True
        if recorded:
            await self._async_save()
            await self.async_refresh()

    async def async_unmark_taken(
        self,
        medicine_id: str,
        scheduled_for: datetime | None = None,
        person_id: str | None = None,
    ) -> bool:
        """Remove the most recent ``taken`` record for a medicine.

        Used by the panel's per-dose hover-undo and the bulk "Undo last
        action" menu item.

        Match logic:
          * If ``scheduled_for`` is provided, find the most recent
            ``taken`` record whose ``scheduled_for`` matches. This is
            the panel-driven path — the frontend always knows the slot.
          * If ``scheduled_for`` is ``None``, fall back to the most
            recent ``taken`` record for that medicine regardless of
            slot. This is the safety net for service calls from
            automations that didn't pin a slot.

        v0.2.24: ``person_id``, when given, additionally restricts the
        match to records belonging to that prescription. Without it,
        ANY person's record matches. For multi-prescription medicines
        the panel always passes person_id; legacy callers that don't
        get the v0.2.23 behavior.

        We always remove the LAST matching record (rather than the first)
        so a sequence like *take → undo → take → undo* affects the
        correct entry. Returns ``True`` if a record was removed,
        ``False`` if there was nothing to undo (caller can use this to
        log a no-op or update UI state).

        Fires ``EVENT_DOSE_UNMARKED`` so automations that reacted to
        ``EVENT_DOSE_TAKEN`` can roll back if they want.
        """
        removed = self._remove_taken(medicine_id, scheduled_for, person_id)
        if not removed:
            return False
        await self._async_save()
        await self.async_refresh()
        return True

    def _remove_taken(
        self,
        medicine_id: str,
        scheduled_for: datetime | None,
        person_id: str | None,
    ) -> bool:
        """Remove the most recent matching ``taken`` record and announce
        it. Returns True if one was removed. No save / refresh — callers
        batch those."""
        med = self._find(medicine_id)
        if not med:
            _LOGGER.warning("unmark_taken: unknown medicine_id %s", medicine_id)
            return False
        records = self._history.get(medicine_id, [])
        if not records:
            return False

        scheduled_iso = scheduled_for.isoformat() if scheduled_for else None
        target_idx: int | None = None
        # Iterate from the end so we naturally hit the most recent match.
        for idx in range(len(records) - 1, -1, -1):
            r = records[idx]
            if r.taken_at is None:
                continue
            if scheduled_iso is not None and r.scheduled_for != scheduled_iso:
                continue
            if person_id is not None and r.person_id != person_id:
                continue
            target_idx = idx
            break

        if target_idx is None:
            _LOGGER.debug(
                "unmark_taken: no matching taken record for %s "
                "(slot=%s person_id=%s)",
                medicine_id, scheduled_iso, person_id,
            )
            return False

        removed = records.pop(target_idx)
        # Tidy up: if we just emptied the list, drop the key altogether
        # so _history doesn't accumulate empty buckets over time.
        if not records:
            self._history.pop(medicine_id, None)
        self.hass.bus.async_fire(
            EVENT_DOSE_UNMARKED,
            {
                "medicine_id": medicine_id,
                "name": med[CONF_MED_NAME],
                "taken_at": removed.taken_at,
                "scheduled_for": removed.scheduled_for,
                "person_id": removed.person_id,
                "person_name": self._person_name(removed.person_id),
            },
        )
        return True

    async def async_unmark_taken_bulk(
        self, items: list[dict[str, Any]]
    ) -> None:
        """Undo several taken doses in one pass — one save + one refresh
        for the whole set."""
        removed_any = False
        for item in items:
            medicine_id = item.get("medicine_id")
            if not medicine_id:
                continue
            raw_sched = item.get("scheduled_for")
            scheduled_for = (
                dt_util.parse_datetime(raw_sched)
                if isinstance(raw_sched, str)
                else raw_sched
            )
            if self._remove_taken(
                medicine_id, scheduled_for, item.get("person_id")
            ):
                removed_any = True
        if removed_any:
            await self._async_save()
            await self.async_refresh()

    async def async_refresh_sources(self) -> None:
        for src in self._sources:
            try:
                await src.async_refresh()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Source %s refresh failed: %s", src.id, err)
        self._enrichment.clear()
        await self.async_request_refresh()

    # ---- stock / inventory (v0.3.0) --------------------------------

    @staticmethod
    def _stock_unit_label(med_type: str | None) -> str:
        return {
            MED_TYPE_PILL: "tablets",
            MED_TYPE_INJECTION: "injections",
            MED_TYPE_DROPS: "drops",
        }.get(med_type or "", "units")

    def _stock_cfg(self, med_id: str, prescription_id: str) -> dict[str, Any] | None:
        return self._stock_config.get(med_id, {}).get(prescription_id)

    def _consumed_for(
        self, med_id: str, prescription_id: str
    ) -> list[tuple[str, float]]:
        """(taken_at, units_consumed) for this prescription's taken doses."""
        return [
            (r.taken_at, float(r.units_consumed or 0.0))
            for r in self._history.get(med_id, [])
            if r.taken_at and r.prescription_id == prescription_id
        ]

    def _stock_for(
        self, med_id: str, prescription_id: str
    ) -> float | None:
        cfg = self._stock_cfg(med_id, prescription_id)
        if not cfg or not cfg.get(CONF_STOCK_TRACK):
            return None
        events = self._stock_events.get(med_id, {}).get(prescription_id, [])
        return current_stock(events, self._consumed_for(med_id, prescription_id))

    def _forward_occurrences(
        self,
        prescription: dict[str, Any],
        now: datetime,
        unit_count: float,
        max_units: float,
    ) -> list[datetime]:
        """Future scheduled datetimes from now, enough to exhaust max_units.

        Stops once the accumulated consumption would cover ``max_units`` so
        a long schedule doesn't build a year of occurrences every tick;
        bounded by the lookahead regardless.
        """
        sched = Schedule.from_medicine_dict(prescription)
        occ: list[datetime] = []
        acc = 0.0
        for offset in range(STOCK_RUNOUT_LOOKAHEAD_DAYS):
            d = (now + timedelta(days=offset)).date()
            for o in sched.occurrences_on(d, tz=now.tzinfo):
                if o <= now:
                    continue
                occ.append(o)
                acc += unit_count
                if acc >= max_units:
                    return occ
        return occ

    def _stock_metrics(
        self, med: dict[str, Any], prescription: dict[str, Any], now: datetime
    ) -> dict[str, Any] | None:
        """Per-prescription stock snapshot, or None when not tracked."""
        med_id = med[CONF_MED_ID]
        pid = prescription.get(CONF_PRESCRIPTION_ID)
        cfg = self._stock_cfg(med_id, pid) if pid else None
        if not cfg or not cfg.get(CONF_STOCK_TRACK):
            return None

        stock_val = self._stock_for(med_id, pid)
        unit_count = float(prescription.get(CONF_MED_UNIT_COUNT) or 0.0)
        pack_size = cfg.get(CONF_STOCK_PACK_SIZE)

        doses_left: int | None = None
        run_out: Any = None
        days_left: int | None = None
        if stock_val is not None and unit_count > 0:
            occ = self._forward_occurrences(
                prescription, now, unit_count, stock_val + unit_count
            )
            doses_left, run_out = project_runout(occ, unit_count, stock_val)
            if run_out is not None:
                days_left = (run_out - now.date()).days

        mode = cfg.get(CONF_STOCK_REMINDER_MODE) or DEFAULT_STOCK_REMINDER_MODE
        threshold = float(cfg.get(CONF_STOCK_REMINDER_THRESHOLD) or 0.0)
        low = bool(cfg.get(CONF_STOCK_REMINDER_ENABLED)) and is_low(
            mode,
            threshold,
            stock=stock_val,
            doses_left=doses_left,
            days_left=days_left,
        )
        packs_left = (
            round(stock_val / pack_size, 2)
            if stock_val is not None and pack_size
            else None
        )
        return {
            "track_stock": True,
            "stock": stock_val,
            "stock_unit": self._stock_unit_label(med.get(CONF_MED_TYPE)),
            "pack_size": pack_size,
            "packs_left": packs_left,
            "doses_left": doses_left,
            "days_left": days_left,
            "run_out_date": run_out.isoformat() if run_out else None,
            "expiry_date": cfg.get(CONF_STOCK_EXPIRY),
            "low_stock": low,
            "reminder_enabled": bool(cfg.get(CONF_STOCK_REMINDER_ENABLED)),
            "reminder_mode": mode,
            "reminder_threshold": threshold,
        }

    def _fire_stock_events(
        self, med: dict[str, Any], prescription: dict[str, Any], metrics: dict[str, Any]
    ) -> None:
        """Fire stock_low / stock_expiring / stock_expired, once per crossing."""
        med_id = med[CONF_MED_ID]
        pid = prescription.get(CONF_PRESCRIPTION_ID)
        key = (med_id, pid)
        person_id = prescription.get(CONF_MED_PERSON) or None
        base = {
            "medicine_id": med_id,
            "name": med[CONF_MED_NAME],
            "prescription_id": pid,
            "person_id": person_id,
            "person_name": self._person_name(person_id),
        }

        if metrics["low_stock"]:
            if key not in self._fired_stock_low:
                self.hass.bus.async_fire(
                    EVENT_STOCK_LOW,
                    {
                        **base,
                        "stock": metrics["stock"],
                        "doses_left": metrics["doses_left"],
                        "days_left": metrics["days_left"],
                        "run_out_date": metrics["run_out_date"],
                    },
                )
                self._fired_stock_low.add(key)
        else:
            self._fired_stock_low.discard(key)

        status = expiry_status(
            metrics["expiry_date"], dt_util.now().date(), DEFAULT_STOCK_EXPIRY_LEAD_DAYS
        )
        if status == "expired":
            self._fired_stock_expiring.discard(key)
            if key not in self._fired_stock_expired:
                self.hass.bus.async_fire(
                    EVENT_STOCK_EXPIRED,
                    {**base, "expiry_date": metrics["expiry_date"]},
                )
                self._fired_stock_expired.add(key)
        elif status == "expiring":
            self._fired_stock_expired.discard(key)
            if key not in self._fired_stock_expiring:
                self.hass.bus.async_fire(
                    EVENT_STOCK_EXPIRING,
                    {**base, "expiry_date": metrics["expiry_date"]},
                )
                self._fired_stock_expiring.add(key)
        else:
            self._fired_stock_expiring.discard(key)
            self._fired_stock_expired.discard(key)

    def _append_stock_event(
        self, med_id: str, prescription_id: str, event: StockEvent
    ) -> None:
        self._stock_events.setdefault(med_id, {}).setdefault(
            prescription_id, []
        ).append(event)

    async def async_configure_stock(
        self,
        medicine_id: str,
        prescription_id: str,
        *,
        track_stock: bool | None = None,
        pack_size: float | None = None,
        reminder_enabled: bool | None = None,
        reminder_mode: str | None = None,
        reminder_threshold: float | None = None,
        expiry: str | None = None,
    ) -> bool:
        """Set per-prescription stock config. Only provided fields change."""
        med = self._find(medicine_id)
        if not med:
            return False
        if self._resolve_prescription(med, None, prescription_id=prescription_id) is None:
            _LOGGER.warning(
                "configure_stock: no prescription %s on %s",
                prescription_id, medicine_id,
            )
            return False
        if reminder_mode is not None and reminder_mode not in STOCK_REMINDER_MODES:
            _LOGGER.warning("configure_stock: bad reminder_mode %s", reminder_mode)
            return False
        cfg = self._stock_config.setdefault(medicine_id, {}).setdefault(
            prescription_id, {}
        )
        if track_stock is not None:
            cfg[CONF_STOCK_TRACK] = bool(track_stock)
        if pack_size is not None:
            cfg[CONF_STOCK_PACK_SIZE] = float(pack_size)
        if reminder_enabled is not None:
            cfg[CONF_STOCK_REMINDER_ENABLED] = bool(reminder_enabled)
        if reminder_mode is not None:
            cfg[CONF_STOCK_REMINDER_MODE] = reminder_mode
        if reminder_threshold is not None:
            cfg[CONF_STOCK_REMINDER_THRESHOLD] = float(reminder_threshold)
        if expiry is not None:
            cfg[CONF_STOCK_EXPIRY] = expiry or None
        await self._async_save()
        await self.async_refresh()
        return True

    async def async_set_stock(
        self,
        medicine_id: str,
        prescription_id: str,
        amount: float,
        expiry: str | None = None,
    ) -> bool:
        """Set an absolute stock baseline."""
        med = self._find(medicine_id)
        if not med or self._resolve_prescription(
            med, None, prescription_id=prescription_id
        ) is None:
            return False
        self._append_stock_event(
            medicine_id,
            prescription_id,
            StockEvent(
                kind=STOCK_EVENT_SET,
                ts=dt_util.now().isoformat(),
                amount=float(amount),
                expiry=expiry or None,
            ),
        )
        if expiry is not None:
            self._stock_config.setdefault(medicine_id, {}).setdefault(
                prescription_id, {}
            )[CONF_STOCK_EXPIRY] = expiry or None
        await self._async_save()
        await self.async_refresh()
        return True

    async def async_adjust_stock(
        self, medicine_id: str, prescription_id: str, delta: float
    ) -> bool:
        """Add (positive delta) or remove (negative delta) from stock."""
        med = self._find(medicine_id)
        if not med or self._resolve_prescription(
            med, None, prescription_id=prescription_id
        ) is None:
            return False
        delta = float(delta)
        self._append_stock_event(
            medicine_id,
            prescription_id,
            StockEvent(
                kind=STOCK_EVENT_ADD if delta >= 0 else STOCK_EVENT_REMOVE,
                ts=dt_util.now().isoformat(),
                amount=abs(delta),
            ),
        )
        await self._async_save()
        await self.async_refresh()
        return True

    async def async_refill(
        self,
        medicine_id: str,
        prescription_id: str,
        packs: float = 1,
        expiry: str | None = None,
    ) -> bool:
        """Add ``pack_size * packs`` units. Needs a configured pack size."""
        med = self._find(medicine_id)
        if not med or self._resolve_prescription(
            med, None, prescription_id=prescription_id
        ) is None:
            return False
        cfg = self._stock_cfg(medicine_id, prescription_id)
        pack_size = cfg.get(CONF_STOCK_PACK_SIZE) if cfg else None
        if not pack_size:
            _LOGGER.warning(
                "refill: no pack_size configured for %s/%s",
                medicine_id, prescription_id,
            )
            return False
        self._append_stock_event(
            medicine_id,
            prescription_id,
            StockEvent(
                kind=STOCK_EVENT_REFILL,
                ts=dt_util.now().isoformat(),
                amount=float(pack_size) * float(packs),
                pack_count=int(packs) if float(packs).is_integer() else None,
                expiry=expiry or None,
            ),
        )
        if expiry is not None:
            self._stock_config.setdefault(medicine_id, {}).setdefault(
                prescription_id, {}
            )[CONF_STOCK_EXPIRY] = expiry or None
        await self._async_save()
        await self.async_refresh()
        return True

    # ---- the tick ---------------------------------------------------

    async def _async_update_data(self) -> dict[str, MedicineState]:
        """Tick: build per-medicine state, with one PrescriptionState
        per prescription, then aggregate into MedicineState.

        v0.2.24: prescriptions are first-class. The per-prescription
        loop fires events keyed by (medicine_id, person_id, sched_iso)
        so a Levaxin shared between Sam and Josef fires
        ``pillpilot_dose_due`` twice per scheduled time — once per
        person — instead of once for the medicine. Existing blueprints
        already filter by person_id and handle this correctly.
        """
        now = dt_util.now()
        result: dict[str, MedicineState] = {}

        for med in self._medicines_cfg:
            med_id = med[CONF_MED_ID]
            enrichment = await self._enrich(med, now)
            prescriptions_cfg = med.get(CONF_MED_PRESCRIPTIONS, [])

            prescription_states: list[PrescriptionState] = []

            for prescription in prescriptions_cfg:
                p_state = self._build_prescription_state(
                    med, prescription, now
                )
                prescription_states.append(p_state)

            # Aggregate state across all prescriptions: any due > any
            # missed > all taken > any skipped > upcoming. The sensor's
            # native_value uses this so HA's UI shows the worst-case
            # state.
            agg_state = self._aggregate_state(prescription_states)

            result[med_id] = MedicineState(
                id=med_id,
                name=med[CONF_MED_NAME],
                notes=med.get(CONF_MED_NOTES, ""),
                npl_id=med.get(CONF_MED_NPL_ID),
                varunummer=med.get(CONF_MED_VARUNUMMER),
                atc_code=med.get(CONF_MED_ATC_CODE),
                med_type=med.get(CONF_MED_TYPE),
                enrichment=enrichment,
                prescriptions=prescription_states,
                visibility=med.get("visibility") or "everyone",
                visibility_users=tuple(med.get("visibility_users") or []),
                last_state=agg_state,
            )

        today_iso_prefix = now.date().isoformat()
        self._fired_due = {
            k for k in self._fired_due if k[2].startswith(today_iso_prefix)
        }
        self._fired_missed = {
            k for k in self._fired_missed if k[2].startswith(today_iso_prefix)
        }
        return result

    # ---- per-prescription tick -------------------------------------

    def _build_prescription_state(
        self,
        med: dict[str, Any],
        prescription: dict[str, Any],
        now: datetime,
    ) -> PrescriptionState:
        """Build one PrescriptionState; fire dose_due / dose_missed events.

        ``prescription`` has the schedule fields (frequency, times,
        days, etc.) at its top level — Schedule.from_medicine_dict
        works on it as-is because the field names are the same.
        """
        med_id = med[CONF_MED_ID]
        person_id = prescription.get(CONF_MED_PERSON) or None
        person_name = self._person_name(person_id)
        scheduled_today = self._scheduled_today(prescription, now)
        next_dose = self._next_scheduled(prescription, now)
        last_taken = self._last_taken(med_id, person_id)
        state = self._derive_prescription_state(
            med, prescription, now, scheduled_today
        )

        for sched in scheduled_today:
            key = (med_id, person_id, sched.isoformat())
            # v0.2.7: skip DUE while the slot is actively snoozed —
            # the user asked to be reminded later, the tick refires
            # DUE once snoozed_until elapses (async_snooze cleared
            # this key from _fired_due so refire is unblocked).
            if (
                sched <= now
                and key not in self._fired_due
                and self._active_snooze(med_id, sched, person_id, now) is None
                and not self._already_recorded(med_id, sched, person_id)
            ):
                self.hass.bus.async_fire(
                    EVENT_DOSE_DUE,
                    {
                        "medicine_id": med_id,
                        "name": med[CONF_MED_NAME],
                        "dose": prescription.get(CONF_MED_DOSE, ""),
                        "scheduled_for": sched.isoformat(),
                        "person_id": person_id,
                        "person_name": person_name,
                    },
                )
                self._fired_due.add(key)

            window = prescription.get(
                CONF_MED_REMIND_WINDOW, DEFAULT_REMIND_WINDOW
            )
            # v0.2.7: a slot that's been snoozed at any point is
            # exempt from MISSED — the user already engaged. They'll
            # get the snooze-elapsed DUE ping; missed is redundant.
            if (
                sched + timedelta(minutes=window) <= now
                and key not in self._fired_missed
                and not self._has_snoozed_record(med_id, sched, person_id)
                and not self._already_recorded(med_id, sched, person_id)
            ):
                self.hass.bus.async_fire(
                    EVENT_DOSE_MISSED,
                    {
                        "medicine_id": med_id,
                        "name": med[CONF_MED_NAME],
                        "scheduled_for": sched.isoformat(),
                        "person_id": person_id,
                        "person_name": person_name,
                    },
                )
                self._fired_missed.add(key)

        # v0.2.0+: storage is RRULE-based. PrescriptionState exposes
        # friendly fields (frequency/days/days_of_month) for backward
        # compatibility with the panel JS — derive them from the
        # canonical RRULE here so the WS read path doesn't need its
        # own translation. Schedule modes beyond the legacy three
        # (interval/cycle/custom) fall back to "daily" for the form
        # field; their actual recurrence is fully captured by the
        # RRULE inside the Schedule object the coordinator already
        # uses, so dose timing is unaffected.
        stored_rrule = prescription.get(CONF_MED_RRULE) or "FREQ=DAILY"
        stored_schedule_type = (
            prescription.get(CONF_MED_SCHEDULE_TYPE) or SCHEDULE_TYPE_DAILY
        )
        friendly = rrule_to_friendly(stored_rrule)
        # Daily / weekly / monthly / interval map 1:1 to the friendly
        # frequency the panel expects. Cycle and custom modes fall
        # back to "daily" until beta4/beta5 wire them into the panel
        # UI; their RRULE-based dose timing is unaffected because the
        # coordinator's Schedule object reads the canonical RRULE
        # directly, not through this friendly translation.
        if stored_schedule_type in (
            SCHEDULE_TYPE_DAILY,
            SCHEDULE_TYPE_WEEKLY,
            SCHEDULE_TYPE_MONTHLY,
            SCHEDULE_TYPE_INTERVAL,
        ):
            derived_frequency = stored_schedule_type
        else:
            derived_frequency = SCHEDULE_TYPE_DAILY
        derived_days = friendly["weekdays"] or list(range(7))
        derived_doms = friendly["days_of_month"] or []
        # interval_days is encoded inside the RRULE (as INTERVAL=N)
        # rather than stored as a separate field — extracted here.
        # ends_on is stored separately as ISO string for the panel,
        # mirroring what's also in the RRULE's UNTIL.
        derived_interval = friendly["interval_days"]
        derived_ends_on = prescription.get(CONF_MED_ENDS_ON)
        derived_starts_on = prescription.get(CONF_MED_STARTS_ON)
        # times_per_weekday is stored as list-of-7-lists or None.
        # Pass through verbatim to the WS — panel reads it as JSON.
        derived_tpw = prescription.get(CONF_MED_TIMES_PER_WEEKDAY)

        unit_count = float(prescription.get(CONF_MED_UNIT_COUNT) or 0.0)
        variant_strength = str(
            prescription.get(CONF_MED_VARIANT_STRENGTH) or ""
        )
        variant_form = str(prescription.get(CONF_MED_VARIANT_FORM) or "")
        variant_npl_id_raw = prescription.get(CONF_MED_VARIANT_NPL_ID)
        variant_npl_id = (
            str(variant_npl_id_raw) if variant_npl_id_raw else None
        )
        # v0.2.13: total_dose_mg computed on the fly via the Dose
        # model. None for combo / IU / concentration variants where
        # the math doesn't apply.
        dose_obj = Dose(
            med_type=prescription.get(CONF_MED_TYPE) or "",
            count=unit_count,
            variant_strength=variant_strength,
            variant_form=variant_form,
        )
        total_dose_mg = dose_obj.total_mg

        stock_metrics = self._stock_metrics(med, prescription, now)
        if stock_metrics is not None:
            self._fire_stock_events(med, prescription, stock_metrics)

        return PrescriptionState(
            id=prescription.get(CONF_PRESCRIPTION_ID, ""),
            person_id=person_id,
            person_name=person_name,
            dose=prescription.get(CONF_MED_DOSE, ""),
            unit_count=unit_count,
            variant_strength=variant_strength,
            variant_form=variant_form,
            variant_npl_id=variant_npl_id,
            total_dose_mg=total_dose_mg,
            frequency=derived_frequency,
            times=list(prescription.get(CONF_MED_TIMES, [])),
            days=list(derived_days),
            days_of_month=list(derived_doms),
            remind_window_minutes=int(
                prescription.get(CONF_MED_REMIND_WINDOW) or DEFAULT_REMIND_WINDOW
            ),
            next_dose_at=next_dose,
            last_taken_at=last_taken,
            state=state,
            today_doses=self._today_doses_for(
                med_id, prescription, person_id, now, scheduled_today
            ),
            interval_days=derived_interval,
            ends_on=derived_ends_on,
            starts_on=derived_starts_on,
            times_per_weekday=derived_tpw,
            track_stock=bool(stock_metrics),
            stock=stock_metrics["stock"] if stock_metrics else None,
            stock_unit=stock_metrics["stock_unit"] if stock_metrics else None,
            pack_size=stock_metrics["pack_size"] if stock_metrics else None,
            packs_left=stock_metrics["packs_left"] if stock_metrics else None,
            doses_left=stock_metrics["doses_left"] if stock_metrics else None,
            days_left=stock_metrics["days_left"] if stock_metrics else None,
            run_out_date=stock_metrics["run_out_date"] if stock_metrics else None,
            expiry_date=stock_metrics["expiry_date"] if stock_metrics else None,
            low_stock=stock_metrics["low_stock"] if stock_metrics else False,
            reminder_enabled=(
                stock_metrics["reminder_enabled"] if stock_metrics else False
            ),
            reminder_mode=(
                stock_metrics["reminder_mode"] if stock_metrics else None
            ),
            reminder_threshold=(
                stock_metrics["reminder_threshold"] if stock_metrics else None
            ),
        )

    @staticmethod
    def _aggregate_state(prescriptions: list[PrescriptionState]) -> str:
        """Worst-case state across prescriptions.

        Order: due > missed > snoozed > taken (all) > skipped (any) > upcoming.
        ``due`` wins because it's the call-to-action state — if any
        person has a pending dose, the sensor should reflect that.
        ``missed`` ranks higher than ``snoozed`` because a missed dose
        is a dropped ball; a snoozed one is actively engaged.
        ``snoozed`` ranks above ``taken`` because there's still
        pending work — the user asked for a reminder.
        ``taken`` requires ALL prescriptions to be taken.
        """
        if not prescriptions:
            return STATE_UPCOMING
        states = [p.state for p in prescriptions]
        if STATE_DUE in states:
            return STATE_DUE
        if STATE_MISSED in states:
            return STATE_MISSED
        if STATE_SNOOZED in states:
            return STATE_SNOOZED
        if all(s == STATE_TAKEN for s in states):
            return STATE_TAKEN
        if STATE_SKIPPED in states:
            return STATE_SKIPPED
        return STATE_UPCOMING

    # ---- enrichment -------------------------------------------------

    async def _enrich(
        self, med: dict[str, Any], now: datetime
    ) -> dict[str, dict[str, Any]]:
        med_id = med[CONF_MED_ID]
        per_med = self._enrichment.setdefault(med_id, {})

        # Prefer the user-supplied ATC code; if missing, try to inherit
        # from a previously cached source result so downstream
        # vocabulary lookups still have something to resolve.
        cached_atc = next(
            (
                r.atc_code
                for (_, r) in per_med.values()
                if r and r.atc_code
            ),
            None,
        )
        key = LookupKey(
            npl_id=med.get(CONF_MED_NPL_ID) or None,
            varunummer=med.get(CONF_MED_VARUNUMMER) or None,
            atc_code=med.get(CONF_MED_ATC_CODE) or cached_atc,
            name=med.get(CONF_MED_NAME) or None,
        )

        out: dict[str, dict[str, Any]] = {}
        for src in self._sources:
            cached = per_med.get(src.id)
            if cached and now - cached[0] < SOURCE_LOOKUP_TTL:
                out[src.id] = _serialize(cached[1])
                continue
            try:
                res = await src.lookup(key)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Source %s lookup failed: %s", src.id, err)
                continue
            if res is None:
                continue
            per_med[src.id] = (now, res)
            out[src.id] = _serialize(res)
            # If this source produced an ATC code that the user didn't
            # provide, feed it forward so a downstream vocabulary source
            # can resolve it on the next iteration of the loop.
            if not key.atc_code and res.atc_code:
                key.atc_code = res.atc_code
        return out

    # ---- schedule math (delegated to Schedule model) ---------------

    def _scheduled_today(
        self, med: dict[str, Any], now: datetime
    ) -> list[datetime]:
        return Schedule.from_medicine_dict(med).occurrences_on(
            now.date(), tz=now.tzinfo
        )

    def _next_scheduled(
        self, med: dict[str, Any], now: datetime
    ) -> datetime | None:
        return Schedule.from_medicine_dict(med).next_after(now)

    def _closest_scheduled(
        self, med: dict[str, Any], when: datetime
    ) -> datetime | None:
        return Schedule.from_medicine_dict(med).closest_to(when)

    def _last_taken(
        self, med_id: str, person_id: str | None = None
    ) -> datetime | None:
        """Most recent ``taken`` record for this medicine.

        v0.2.24: when ``person_id`` is given, restrict to records for
        that prescription. Records without a person_id field (legacy
        records that pre-date the field) match a None person_id only.
        """
        records = self._history.get(med_id, [])
        taken = [r for r in records if r.taken_at]
        if person_id is not None:
            taken = [r for r in taken if r.person_id == person_id]
        if not taken:
            return None
        return dt_util.parse_datetime(taken[-1].taken_at)

    def _already_recorded(
        self,
        med_id: str,
        scheduled: datetime,
        person_id: str | None = None,
    ) -> bool:
        """Has this scheduled slot already been taken or skipped?

        v0.2.24: when ``person_id`` is given, only records belonging to
        that prescription count. Without it, ANY person's record on
        that slot matches (used by callers that don't know which
        prescription they're checking).
        """
        for r in self._history.get(med_id, []):
            if r.scheduled_for == scheduled.isoformat() and (
                r.taken_at or r.skipped_at
            ):
                if person_id is not None and r.person_id != person_id:
                    continue
                return True
        return False

    def _slot_records(
        self,
        med_id: str,
        scheduled: datetime,
        person_id: str | None,
    ) -> list[DoseRecord]:
        """All records matching a (slot, person) pair."""
        sched_iso = scheduled.isoformat()
        return [
            r for r in self._history.get(med_id, [])
            if r.scheduled_for == sched_iso
            and (person_id is None or r.person_id == person_id)
        ]

    def _active_snooze(
        self,
        med_id: str,
        scheduled: datetime,
        person_id: str | None,
        now: datetime,
    ) -> datetime | None:
        """Return the snoozed_until datetime if the slot is currently
        snoozed (and not taken/skipped), else None.

        Used by the tick to gate EVENT_DOSE_DUE during a snooze
        window, and by _today_doses_for / _derive_prescription_state
        to surface the ``snoozed`` status.
        """
        matches = self._slot_records(med_id, scheduled, person_id)
        if any(r.taken_at or r.skipped_at for r in matches):
            return None
        for r in matches:
            if not r.snoozed_until:
                continue
            until = dt_util.parse_datetime(r.snoozed_until)
            if until and until > now:
                return until
        return None

    def _has_snoozed_record(
        self,
        med_id: str,
        scheduled: datetime,
        person_id: str | None,
    ) -> bool:
        """Has the slot ever been snoozed (and isn't taken/skipped)?

        Used by the tick to permanently suppress EVENT_DOSE_MISSED for
        a snoozed slot — once the user engaged via snooze, the missed
        notification is redundant. If the slot eventually flips to
        taken_at/skipped_at the gate releases (taken/skipped wins).
        """
        matches = self._slot_records(med_id, scheduled, person_id)
        if any(r.taken_at or r.skipped_at for r in matches):
            return False
        return any(r.snoozed_until for r in matches)

    def _today_doses_for(
        self,
        med_id: str,
        prescription: dict[str, Any],
        person_id: str | None,
        now: datetime,
        scheduled_today: list[datetime],
    ) -> list[dict[str, Any]]:
        """Build today's per-slot status list for one prescription.

        For each scheduled time today, look up any matching DoseRecord
        (filtered by person_id) and classify the slot:
          - taken    — there's a record with taken_at
          - skipped  — there's a record with skipped_at
          - snoozed  — record with active snoozed_until (not elapsed),
                       no taken_at/skipped_at
          - missed   — no record and now is past (sched + remind_window)
          - due      — no record and now is at or past sched
          - upcoming — sched is still in the future

        The panel uses this to show per-row Take/Skip buttons or a
        "✓ Taken at HH:MM" label, depending on status. Without it,
        we'd be guessing based on the single ``last_taken_at`` value
        and getting it wrong as soon as a dose is skipped or taken
        out of order.

        v0.2.7: prefers terminal records (taken/skipped) over snooze
        records on the same slot — a take-after-snooze correctly
        reads as taken, not snoozed. The snoozed_until field is
        passed through to the panel so it can render "Snoozed until
        HH:MM" inline.

        v0.2.24: takes ``prescription`` (not the whole medicine) and
        ``person_id`` so multi-prescription medicines correctly
        attribute today's slots to the right person.
        """
        window = prescription.get(CONF_MED_REMIND_WINDOW, DEFAULT_REMIND_WINDOW)

        out: list[dict[str, Any]] = []
        for sched in scheduled_today:
            sched_iso = sched.isoformat()
            slot_records = self._slot_records(med_id, sched, person_id)
            terminal = next(
                (r for r in slot_records if r.taken_at or r.skipped_at),
                None,
            )
            record = terminal or (slot_records[0] if slot_records else None)

            snoozed_until_iso: str | None = None
            snoozed_active = False
            if record and record.snoozed_until:
                parsed = dt_util.parse_datetime(record.snoozed_until)
                if parsed and parsed > now:
                    snoozed_active = True

            if record and record.taken_at:
                status, action_at = "taken", record.taken_at
            elif record and record.skipped_at:
                status, action_at = "skipped", record.skipped_at
            elif snoozed_active:
                status, action_at = "snoozed", record.snoozed_until
                snoozed_until_iso = record.snoozed_until
            elif now > sched + timedelta(minutes=window):
                status, action_at = "missed", None
            elif now >= sched:
                status, action_at = "due", None
            else:
                status, action_at = "upcoming", None
            out.append(
                {
                    "scheduled_at": sched_iso,
                    "time": sched.strftime("%H:%M"),
                    "status": status,
                    "action_at": action_at,
                    "snoozed_until": snoozed_until_iso,
                }
            )
        return out

    def _derive_prescription_state(
        self,
        med: dict[str, Any],
        prescription: dict[str, Any],
        now: datetime,
        scheduled_today: list[datetime],
    ) -> str:
        """Compute the headline state for one prescription.

        Mirrors the v0.2.23 ``_derive_state`` logic but operates on a
        single prescription instead of the whole medicine. Multiple
        prescriptions on the same medicine each get their own state;
        ``_aggregate_state`` combines them at the medicine level.

        v0.2.7: a slot with an active snooze surfaces STATE_SNOOZED.
        Snoozed past the window also reads as snoozed — the user
        explicitly asked for the deferred reminder, so we don't
        flip back to MISSED until they take/skip or the snooze
        actually elapses.
        """
        med_id = med[CONF_MED_ID]
        person_id = prescription.get(CONF_MED_PERSON) or None
        window = prescription.get(CONF_MED_REMIND_WINDOW, DEFAULT_REMIND_WINDOW)

        for sched in scheduled_today:
            recorded = self._already_recorded(med_id, sched, person_id)
            snoozed = self._active_snooze(med_id, sched, person_id, now) is not None
            if sched <= now <= sched + timedelta(minutes=window):
                if recorded:
                    return STATE_TAKEN
                if snoozed:
                    return STATE_SNOOZED
                return STATE_DUE
            if now > sched + timedelta(minutes=window) and not recorded:
                if snoozed:
                    return STATE_SNOOZED
                if sched == max(s for s in scheduled_today if s <= now):
                    return STATE_MISSED

        # No active slot today — fall back to most recent history for
        # this prescription. Filter records by person_id so multi-
        # prescription medicines don't cross-contaminate.
        records = [
            r for r in self._history.get(med_id, [])
            if person_id is None or r.person_id == person_id
        ]
        if records:
            last = records[-1]
            if last.skipped_at:
                return STATE_SKIPPED
            if last.taken_at:
                return STATE_TAKEN
        return STATE_UPCOMING

    def _find(self, medicine_id: str) -> dict[str, Any] | None:
        return next(
            (m for m in self._medicines_cfg if m[CONF_MED_ID] == medicine_id), None
        )

    def _person_name(self, entity_id: str | None) -> str | None:
        """Resolve a person entity_id to its friendly name."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        return entity_id.split(".", 1)[-1].replace("_", " ").title()


def _serialize(r: LookupResult) -> dict[str, Any]:
    """Turn a LookupResult into a JSON-friendly dict for sensor attributes."""
    out: dict[str, Any] = {
        "source": r.source_id,
    }
    for f in (
        "name",
        "strength",
        "pharmaceutical_form",
        "route_of_administration",
        "atc_code",
        "atc_label",
        "manufacturer",
        "pack_size",
        "narcotic",
    ):
        v = getattr(r, f)
        if v not in (None, "", []):
            out[f] = v
    if r.active_substances:
        out["active_substances"] = list(r.active_substances)
    if r.raw:
        out["raw"] = r.raw
    return out
