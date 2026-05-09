"""
Coordinator: tick every minute, evaluate medicine schedules, fire bus
events, persist history, and (when sources are registered) enrich each
medicine via every source.

As of v0.2.14 no built-in sources ship — ``self._sources`` is an empty
list and the enrichment loop is a no-op. The plumbing is kept so the
v0.2.16 FASS-web-link source can plug in cleanly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

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
    CONF_MED_TOTAL_DOSE_MG,
    CONF_MED_TYPE,
    CONF_MED_UNIT_COUNT,
    CONF_MED_UNIT_STRENGTH_MG,
    CONF_MED_VARUNUMMER,
    CONF_MEDICINES,
    CONF_PRESCRIPTION_ID,
    DEFAULT_REMIND_WINDOW,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_DOSE_DUE,
    EVENT_DOSE_MISSED,
    EVENT_DOSE_SKIPPED,
    EVENT_DOSE_TAKEN,
    EVENT_DOSE_UNMARKED,
    FREQ_DAILY,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    SCHEDULE_TYPE_DAILY,
    SCHEDULE_TYPE_MONTHLY,
    SCHEDULE_TYPE_WEEKLY,
    SOURCE_LOOKUP_TTL,
    STATE_DUE,
    STATE_MISSED,
    STATE_SKIPPED,
    STATE_TAKEN,
    STATE_UPCOMING,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .sources import LookupKey, LookupResult, MedicineSource
from .schedule import Schedule, rrule_to_friendly

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
    unit_strength_mg: float
    total_dose_mg: float
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
    # times_per_weekday is the WS-friendly shape (list of 7 lists of
    # HH:MM strings) — what panel.js consumes via sensor attributes.
    # None means simple mode (use ``times`` for every firing day).
    times_per_weekday: list[list[str]] | None = None


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
    def unit_strength_mg(self) -> float:
        return (
            self.prescriptions[0].unit_strength_mg if self.prescriptions else 0.0
        )

    @property
    def total_dose_mg(self) -> float:
        return self.prescriptions[0].total_dose_mg if self.prescriptions else 0.0

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


class MedicineCoordinator(DataUpdateCoordinator[dict[str, MedicineState]]):
    """Drives the schedule. data is keyed by medicine id."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        medicines: list[dict[str, Any]],
        sources: list[MedicineSource],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self._entry_id = entry_id
        self._medicines_cfg = medicines
        self._sources = sources
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")
        self._history: dict[str, list[DoseRecord]] = {}
        # enrichment cache: medicine_id -> {source_id -> (timestamp, LookupResult)}
        self._enrichment: dict[str, dict[str, tuple[datetime, LookupResult]]] = {}
        self._fired_due: set[tuple[str, str | None, str]] = set()
        self._fired_missed: set[tuple[str, str | None, str]] = set()

    # ---- lifecycle --------------------------------------------------

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if not raw:
            return
        for med_id, records in raw.get("history", {}).items():
            self._history[med_id] = [DoseRecord(**r) for r in records]

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
                }
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
    ) -> dict[str, Any] | None:
        """Pick the right prescription for an action.

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
        med = self._find(medicine_id)
        if not med:
            _LOGGER.warning("mark_taken: unknown medicine_id %s", medicine_id)
            return
        when = when or dt_util.now()
        prescription = self._resolve_prescription(med, person_id, when)
        if prescription is None:
            _LOGGER.warning(
                "mark_taken: no prescription matched for %s person_id=%s",
                medicine_id, person_id,
            )
            return
        resolved_pid = prescription.get(CONF_MED_PERSON) or None
        scheduled = scheduled_for or self._closest_scheduled(prescription, when)
        record = DoseRecord(
            medicine_id=medicine_id,
            scheduled_for=scheduled.isoformat() if scheduled else when.isoformat(),
            person_id=resolved_pid,
            taken_at=when.isoformat(),
        )
        self._history.setdefault(medicine_id, []).append(record)
        await self._async_save()
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
        await self.async_request_refresh()

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
        await self.async_request_refresh()

    async def async_snooze(
        self,
        medicine_id: str,
        minutes: int,
        person_id: str | None = None,
    ) -> None:
        """Push the next reminder back by N minutes.

        v0.2.24: ``person_id`` lets callers pin the snooze to a
        specific prescription. Without it we resolve to the closest
        prescription by time, mirroring mark_taken's behavior.
        """
        med = self._find(medicine_id)
        if not med:
            return
        now = dt_util.now()
        prescription = self._resolve_prescription(med, person_id, now)
        if prescription is None:
            return
        resolved_pid = prescription.get(CONF_MED_PERSON) or None
        record = DoseRecord(
            medicine_id=medicine_id,
            scheduled_for=(now + timedelta(minutes=minutes)).isoformat(),
            person_id=resolved_pid,
        )
        self._history.setdefault(medicine_id, []).append(record)
        await self._async_save()
        await self.async_request_refresh()

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
        await self._async_save()
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
        await self.async_request_refresh()
        return True

    async def async_refresh_sources(self) -> None:
        for src in self._sources:
            try:
                await src.async_refresh()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Source %s refresh failed: %s", src.id, err)
        self._enrichment.clear()
        await self.async_request_refresh()

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
            if sched <= now and key not in self._fired_due:
                if not self._already_recorded(med_id, sched, person_id):
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
            if (
                sched + timedelta(minutes=window) <= now
                and key not in self._fired_missed
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
        # times_per_weekday is stored as list-of-7-lists or None.
        # Pass through verbatim to the WS — panel reads it as JSON.
        derived_tpw = prescription.get(CONF_MED_TIMES_PER_WEEKDAY)

        return PrescriptionState(
            id=prescription.get(CONF_PRESCRIPTION_ID, ""),
            person_id=person_id,
            person_name=person_name,
            dose=prescription.get(CONF_MED_DOSE, ""),
            unit_count=float(prescription.get(CONF_MED_UNIT_COUNT) or 0.0),
            unit_strength_mg=float(
                prescription.get(CONF_MED_UNIT_STRENGTH_MG) or 0.0
            ),
            total_dose_mg=float(
                prescription.get(CONF_MED_TOTAL_DOSE_MG) or 0.0
            ),
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
            times_per_weekday=derived_tpw,
        )

    @staticmethod
    def _aggregate_state(prescriptions: list[PrescriptionState]) -> str:
        """Worst-case state across prescriptions.

        Order: due > missed > taken (all) > skipped (any) > upcoming.
        ``due`` wins because it's the call-to-action state — if any
        person has a pending dose, the sensor should reflect that.
        ``missed`` ranks higher than ``taken`` because missed is also
        action-relevant (logbook, dashboards, automations may want to
        flag it). ``taken`` requires ALL prescriptions to be taken.
        """
        if not prescriptions:
            return STATE_UPCOMING
        states = [p.state for p in prescriptions]
        if STATE_DUE in states:
            return STATE_DUE
        if STATE_MISSED in states:
            return STATE_MISSED
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
          - missed   — no record and now is past (sched + remind_window)
          - due      — no record and now is at or past sched
          - upcoming — sched is still in the future

        The panel uses this to show per-row Take/Skip buttons or a
        "✓ Taken at HH:MM" label, depending on status. Without it,
        we'd be guessing based on the single ``last_taken_at`` value
        and getting it wrong as soon as a dose is skipped or taken
        out of order.

        v0.2.24: takes ``prescription`` (not the whole medicine) and
        ``person_id`` so multi-prescription medicines correctly
        attribute today's slots to the right person.
        """
        window = prescription.get(CONF_MED_REMIND_WINDOW, DEFAULT_REMIND_WINDOW)
        history = self._history.get(med_id, [])

        out: list[dict[str, Any]] = []
        for sched in scheduled_today:
            sched_iso = sched.isoformat()
            record = next(
                (
                    r for r in history
                    if r.scheduled_for == sched_iso
                    and (person_id is None or r.person_id == person_id)
                ),
                None,
            )
            if record and record.taken_at:
                status, action_at = "taken", record.taken_at
            elif record and record.skipped_at:
                status, action_at = "skipped", record.skipped_at
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
        """
        med_id = med[CONF_MED_ID]
        person_id = prescription.get(CONF_MED_PERSON) or None
        window = prescription.get(CONF_MED_REMIND_WINDOW, DEFAULT_REMIND_WINDOW)

        for sched in scheduled_today:
            recorded = self._already_recorded(med_id, sched, person_id)
            if sched <= now <= sched + timedelta(minutes=window):
                return STATE_TAKEN if recorded else STATE_DUE
            if now > sched + timedelta(minutes=window) and not recorded:
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
