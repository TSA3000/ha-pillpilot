"""Schedule model — RRULE-backed recurrence rule with cycle overlay.

A schedule answers four questions about when a medicine is due:

  * ``matches_date(d)``   does this date fall on a scheduled day?
  * ``occurrences_on(d)`` what datetimes apply on this date?
  * ``next_after(now)``   what's the next scheduled occurrence after now?
  * ``closest_to(when)``  given a moment, which scheduled occurrence is
                          it most likely referring to (±1 day window)?

The coordinator delegates all schedule math to instances of this
class, which makes the rules unit-testable and keeps the orchestration
layer thin.

**v0.2.0 engine swap:** previously the implementation branched on
``frequency`` (daily/weekly/monthly). Now it stores an RFC 5545 RRULE
string (using ``python-dateutil``) plus a ``schedule_type`` UI hint.
This unlocks every-N-days, antibiotics-style courses with end dates,
and cyclical on/off (birth-control style) — none of which the old
schema could express cleanly. The query methods above keep their
exact signatures so the coordinator code is untouched.

**Storage shape** (per prescription, see ``const.py``):

    {
        "rrule":         "FREQ=DAILY;INTERVAL=2",
        "schedule_type": "interval",      # one of ALL_SCHEDULE_TYPES
        "times":         ["08:00", "20:00"],
        "anchor_date":   "2026-05-08",   # DTSTART for the RRULE
        # cycle mode only:
        "cycle_anchor":   "2026-05-08",
        "cycle_on_days":  21,
        "cycle_off_days": 7,
        # any mode (course end overlay):
        "ends_on": "2026-05-15",
    }

Legacy fields ``frequency``, ``days``, ``days_of_month`` are
translated by ``migrate_v1_to_v2_schedule`` once and discarded. Pure
model — no Home Assistant imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from dateutil import rrule

from .const import (
    ALL_SCHEDULE_TYPES,
    CONF_MED_CYCLE_ANCHOR,
    CONF_MED_CYCLE_OFF_DAYS,
    CONF_MED_CYCLE_ON_DAYS,
    CONF_MED_DAYS,
    CONF_MED_DAYS_OF_MONTH,
    CONF_MED_ENDS_ON,
    CONF_MED_FREQUENCY,
    CONF_MED_RRULE,
    CONF_MED_SCHEDULE_TYPE,
    CONF_MED_STARTS_ON,
    CONF_MED_TIMES,
    CONF_MED_TIMES_PER_WEEKDAY,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    RRULE_TO_WEEKDAY,
    SCHEDULE_TYPE_CUSTOM,
    SCHEDULE_TYPE_CYCLE,
    SCHEDULE_TYPE_DAILY,
    SCHEDULE_TYPE_INTERVAL,
    SCHEDULE_TYPE_MONTHLY,
    SCHEDULE_TYPE_WEEKLY,
    WEEKDAY_TO_RRULE,
)


# Lookahead used by ``next_after`` for safety even when the RRULE
# would technically be infinite. Covers the worst legitimate case
# (monthly on day 31 starting Jan 31 → next valid date is Mar 31, 59
# days). 92 days gives comfortable margin.
_LOOKAHEAD_DAYS = 92


# ---------------------------------------------------------------------------
# Module-level helpers — used by validators (write path) and the WS
# handler (read path). The Schedule dataclass is the runtime model;
# these helpers are the (de)serialization layer between it and the
# wire / storage formats.
# ---------------------------------------------------------------------------


def schedule_to_rrule(
    schedule_type: str,
    *,
    weekdays: list[int] | None = None,
    days_of_month: list[int] | None = None,
    interval_days: int | None = None,
    ends_on: date | None = None,
    count: int | None = None,
    custom_rrule: str | None = None,
) -> str:
    """Build a canonical RRULE string from friendly form fields.

    DTSTART is intentionally NOT included — it's stored as a separate
    ``anchor_date`` on the prescription and supplied as a kwarg at
    query time. Keeping it out of the RRULE string keeps the string
    focused on the recurrence pattern itself, which makes it more
    readable in storage and easier to compare for equality.

    Raises ``ValueError`` for unknown ``schedule_type`` or missing
    required fields for that type.
    """
    if schedule_type not in ALL_SCHEDULE_TYPES:
        raise ValueError(f"unknown schedule_type: {schedule_type!r}")

    if schedule_type == SCHEDULE_TYPE_CUSTOM:
        if not custom_rrule:
            raise ValueError("custom schedule_type requires custom_rrule")
        # Validate by parsing — caller catches if invalid.
        rrule.rrulestr(custom_rrule, dtstart=datetime(2000, 1, 1))
        return custom_rrule.strip()

    parts: list[str] = []
    if schedule_type == SCHEDULE_TYPE_DAILY:
        parts.append("FREQ=DAILY")
    elif schedule_type == SCHEDULE_TYPE_INTERVAL:
        if not interval_days or interval_days < 2:
            raise ValueError("interval schedule_type requires interval_days >= 2")
        parts.append("FREQ=DAILY")
        parts.append(f"INTERVAL={interval_days}")
    elif schedule_type == SCHEDULE_TYPE_WEEKLY:
        if not weekdays:
            raise ValueError("weekly schedule_type requires non-empty weekdays")
        codes = ",".join(WEEKDAY_TO_RRULE[d] for d in sorted(set(weekdays)))
        parts.append("FREQ=WEEKLY")
        parts.append(f"BYDAY={codes}")
    elif schedule_type == SCHEDULE_TYPE_MONTHLY:
        if not days_of_month:
            raise ValueError("monthly schedule_type requires non-empty days_of_month")
        doms = ",".join(str(d) for d in sorted(set(days_of_month)))
        parts.append("FREQ=MONTHLY")
        parts.append(f"BYMONTHDAY={doms}")
    elif schedule_type == SCHEDULE_TYPE_CYCLE:
        # Cycle mode: RRULE underpins a daily tick. The on/off overlay
        # is handled by Schedule.matches_date, not the RRULE itself.
        parts.append("FREQ=DAILY")

    # Course end — UNTIL takes precedence over COUNT. RFC 5545
    # requires UNTIL to match DTSTART's type; we use naive DTSTART so
    # UNTIL is in date-only form (YYYYMMDD), which makes the entire
    # ending date inclusive without needing a timezone.
    if ends_on is not None:
        parts.append(f"UNTIL={ends_on.strftime('%Y%m%d')}")
    elif count is not None and count > 0:
        parts.append(f"COUNT={count}")

    return ";".join(parts)


def rrule_to_friendly(rrule_str: str) -> dict[str, Any]:
    """Extract friendly form fields from an RRULE string.

    Used by the WS read path to enrich storage data before it's sent
    to the panel. Returns weekdays / days_of_month / interval_days /
    count / until_date — missing keys mean "not used by this rule".

    Parses NAME=VALUE pairs directly rather than constructing a
    dateutil rrule object, because the resulting rrule object doesn't
    expose its parsed fields in a stable public API.
    """
    out: dict[str, Any] = {
        "weekdays": [],
        "days_of_month": [],
        "interval_days": None,
        "count": None,
        "until_date": None,
    }
    for part in rrule_str.strip().split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip().upper()
        value = value.strip()
        if name == "BYDAY":
            out["weekdays"] = sorted(
                RRULE_TO_WEEKDAY[code.strip().upper()]
                for code in value.split(",")
                if code.strip().upper() in RRULE_TO_WEEKDAY
            )
        elif name == "BYMONTHDAY":
            try:
                out["days_of_month"] = sorted(
                    int(d) for d in value.split(",") if d.strip()
                )
            except ValueError:
                pass
        elif name == "INTERVAL":
            try:
                out["interval_days"] = int(value)
            except ValueError:
                pass
        elif name == "COUNT":
            try:
                out["count"] = int(value)
            except ValueError:
                pass
        elif name == "UNTIL":
            v = value.rstrip("Z")
            try:
                if "T" in v:
                    out["until_date"] = (
                        datetime.strptime(v, "%Y%m%dT%H%M%S").date().isoformat()
                    )
                else:
                    out["until_date"] = (
                        datetime.strptime(v, "%Y%m%d").date().isoformat()
                    )
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------
# Migration: legacy v0.1.x prescription → v0.2.0 shape
# ---------------------------------------------------------------------------
#
# REMOVE AT v1.0.0 — by then any user upgrading to v1.0 has passed
# through a 0.x.x version that ran this migration. Pre-1.0 data is
# intentionally not supported in 1.0+.


def migrate_v1_to_v2_schedule(prescription: dict[str, Any]) -> dict[str, Any]:
    """Convert a pre-v0.2.0 prescription dict to the new shape, in-place.

    Idempotent: if ``rrule`` is already present, returns unchanged so
    the caller can run this on every load without worrying about
    double-conversion.
    """
    if CONF_MED_RRULE in prescription:
        return prescription

    legacy_freq = prescription.get(CONF_MED_FREQUENCY)
    legacy_days = prescription.get(CONF_MED_DAYS) or []
    legacy_doms = prescription.get(CONF_MED_DAYS_OF_MONTH) or []

    if legacy_freq == FREQ_WEEKLY and legacy_days:
        valid_days = [d for d in legacy_days if isinstance(d, int) and 0 <= d <= 6]
        if valid_days:
            prescription[CONF_MED_RRULE] = schedule_to_rrule(
                SCHEDULE_TYPE_WEEKLY, weekdays=valid_days
            )
            prescription[CONF_MED_SCHEDULE_TYPE] = SCHEDULE_TYPE_WEEKLY
        else:
            # Weekly with no valid weekdays — degrade to daily so the
            # prescription doesn't go silent.
            prescription[CONF_MED_RRULE] = "FREQ=DAILY"
            prescription[CONF_MED_SCHEDULE_TYPE] = SCHEDULE_TYPE_DAILY
    elif legacy_freq == FREQ_MONTHLY and legacy_doms:
        valid_doms = [d for d in legacy_doms if isinstance(d, int) and 1 <= d <= 31]
        if valid_doms:
            prescription[CONF_MED_RRULE] = schedule_to_rrule(
                SCHEDULE_TYPE_MONTHLY, days_of_month=valid_doms
            )
            prescription[CONF_MED_SCHEDULE_TYPE] = SCHEDULE_TYPE_MONTHLY
        else:
            prescription[CONF_MED_RRULE] = "FREQ=DAILY"
            prescription[CONF_MED_SCHEDULE_TYPE] = SCHEDULE_TYPE_DAILY
    else:
        # Daily, or unrecognized, becomes plain daily.
        prescription[CONF_MED_RRULE] = "FREQ=DAILY"
        prescription[CONF_MED_SCHEDULE_TYPE] = SCHEDULE_TYPE_DAILY

    # New fields default to absent / null. Cycle and ends_on didn't
    # exist in v0.1.x so they're always None for migrated data.
    # times_per_weekday (added in v0.2.0-beta3) similarly defaults to
    # None — legacy prescriptions use the flat ``times`` field.
    prescription.setdefault(CONF_MED_ENDS_ON, None)
    prescription.setdefault(CONF_MED_CYCLE_ANCHOR, None)
    prescription.setdefault(CONF_MED_CYCLE_ON_DAYS, None)
    prescription.setdefault(CONF_MED_CYCLE_OFF_DAYS, None)
    prescription.setdefault(CONF_MED_TIMES_PER_WEEKDAY, None)

    # Drop legacy keys so the rest of the codebase only ever sees
    # canonical v0.2.0 shape — no defensive ``if frequency in ...``
    # checks anywhere (see ROADMAP "Migration policy across 0.x").
    prescription.pop(CONF_MED_FREQUENCY, None)
    prescription.pop(CONF_MED_DAYS, None)
    prescription.pop(CONF_MED_DAYS_OF_MONTH, None)

    return prescription


# ---------------------------------------------------------------------------
# Schedule dataclass — the runtime model the coordinator queries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    """Recurrence rule for a single prescription.

    Public method signatures match the pre-v0.2.0 Schedule class so
    the coordinator code is unchanged. Internally backed by an RRULE
    string evaluated through ``python-dateutil``.
    """

    rrule_str: str
    schedule_type: str
    times: tuple[time, ...] = field(default_factory=tuple)
    anchor: date | None = None  # DTSTART for the rrule
    starts_on: date | None = None  # user-set anchor for interval mode
    cycle_anchor: date | None = None
    cycle_on_days: int | None = None
    cycle_off_days: int | None = None
    ends_on: date | None = None  # informational; UNTIL is in the rrule too
    # Per-weekday time overrides. None = "simple mode" — every firing
    # day uses the flat ``times`` field above. When set, it's a tuple
    # of 7 inner tuples indexed Mon=0..Sun=6, each holding the times
    # for that weekday. Empty inner tuple means "no doses on that
    # weekday even if the frequency would otherwise fire" (skip-day
    # semantics, useful for things like daily-except-Sunday).
    times_per_weekday: tuple[tuple[time, ...], ...] | None = None

    # ----- internal -----------------------------------------------------

    def _build_rrule(self) -> rrule.rrulebase:
        """Parse the stored RRULE with the prescription's anchor as DTSTART."""
        anchor = self.anchor or date.today()
        return rrule.rrulestr(
            self.rrule_str,
            dtstart=datetime.combine(anchor, time.min),
        )

    def _is_cycle_on_day(self, d: date) -> bool:
        """For SCHEDULE_TYPE_CYCLE: is ``d`` an on-day?

        Misconfigured cycle (missing fields) fails closed — we'd rather
        miss a dose than spuriously fire one in an off period.
        """
        if (
            self.cycle_anchor is None
            or not self.cycle_on_days
            or not self.cycle_off_days
        ):
            return False
        cycle_len = self.cycle_on_days + self.cycle_off_days
        position = (d - self.cycle_anchor).days % cycle_len
        return 0 <= position < self.cycle_on_days

    # ----- queries (same surface as pre-v0.2.0) -----------------------

    def matches_date(self, d: date) -> bool:
        """Does this date match the recurrence rule?"""
        rule = self._build_rrule()
        target_start = datetime.combine(d, time.min)
        nxt = rule.after(target_start, inc=True)
        if nxt is None or nxt.date() != d:
            return False
        # Cycle overlay applies only when in cycle mode.
        if self.schedule_type == SCHEDULE_TYPE_CYCLE:
            return self._is_cycle_on_day(d)
        return True

    def occurrences_on(
        self, d: date, tz: tzinfo | None = None
    ) -> list[datetime]:
        """All scheduled datetimes on the given date, sorted ascending.

        When ``times_per_weekday`` is set, the times for ``d`` come from
        ``times_per_weekday[d.weekday()]`` — that's the override channel
        for cases like "8:00 weekdays, 10:00 weekends" or "skip Sunday."
        An empty inner tuple means no doses fire on that weekday, even
        though ``matches_date(d)`` may have returned True. This is
        intentional: ``matches_date`` controls firing dates per the rrule;
        ``times_per_weekday`` carves out times-of-day on those dates.

        When ``times_per_weekday`` is None (the default), every firing
        date uses the flat ``times`` list — the original v0.2.0
        behavior, unchanged.
        """
        if not self.matches_date(d):
            return []
        if self.times_per_weekday is not None:
            applicable_times = self.times_per_weekday[d.weekday()]
        else:
            applicable_times = self.times
        return sorted(
            datetime.combine(d, t).replace(tzinfo=tz)
            for t in applicable_times
        )

    def next_after(
        self, now: datetime, lookahead_days: int = _LOOKAHEAD_DAYS
    ) -> datetime | None:
        """First scheduled occurrence strictly after ``now``.

        Walks dates by integer offset from ``now.date()`` and asks
        ``matches_date`` for each candidate. This keeps timezone
        handling clean: ``now`` is the only datetime we touch (always
        aware in HA), ``matches_date`` does its rrule check on a
        plain ``date`` (no tz at all), and ``occurrences_on`` grafts
        ``now.tzinfo`` onto the constructed datetimes so the
        comparison ``occurrence > now`` is always aware-vs-aware.
        Stops at ``lookahead_days`` to bound work even on
        misconfigured rules.
        """
        if not self.times:
            return None
        for offset in range(lookahead_days):
            d = (now + timedelta(days=offset)).date()
            if not self.matches_date(d):
                continue
            for occurrence in self.occurrences_on(d, tz=now.tzinfo):
                if occurrence > now:
                    return occurrence
        return None

    def closest_to(self, when: datetime) -> datetime | None:
        """Scheduled occurrence closest to ``when`` within ±1 day."""
        candidates: list[datetime] = []
        for offset in (-1, 0):
            d = (when + timedelta(days=offset)).date()
            candidates.extend(self.occurrences_on(d, tz=when.tzinfo))
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs((c - when).total_seconds()))

    # ----- construction ------------------------------------------------

    @classmethod
    def from_medicine_dict(cls, med: dict[str, Any]) -> "Schedule":
        """Build a Schedule from a prescription/medicine dict.

        Migrates legacy v0.1.x shape on the fly via
        ``migrate_v1_to_v2_schedule`` so callers don't have to know
        about the storage version.
        """
        # Migrate in-place if needed — idempotent on already-migrated.
        migrate_v1_to_v2_schedule(med)

        times: list[time] = []
        for t_str in med.get(CONF_MED_TIMES, []):
            hh, mm = t_str.split(":")
            times.append(time(int(hh), int(mm)))

        # Parse the per-weekday override if present. Storage shape is
        # a list of 7 lists of HH:MM strings (Mon=0..Sun=6); empty
        # inner list = no doses on that weekday. None at the top level
        # = simple mode (use flat ``times`` instead). Bad shapes
        # (wrong length, malformed times) silently fall back to None
        # rather than crashing — defensive against hand-edited storage.
        tpw_raw = med.get(CONF_MED_TIMES_PER_WEEKDAY)
        times_per_weekday: tuple[tuple[time, ...], ...] | None = None
        if isinstance(tpw_raw, list) and len(tpw_raw) == 7:
            try:
                parsed_rows: list[tuple[time, ...]] = []
                for row in tpw_raw:
                    row_times: list[time] = []
                    for t_str in row or []:
                        hh, mm = str(t_str).split(":")
                        row_times.append(time(int(hh), int(mm)))
                    parsed_rows.append(tuple(row_times))
                times_per_weekday = tuple(parsed_rows)
            except (ValueError, TypeError, AttributeError):
                times_per_weekday = None

        cycle_anchor = _parse_iso_date(med.get(CONF_MED_CYCLE_ANCHOR))
        ends_on = _parse_iso_date(med.get(CONF_MED_ENDS_ON))
        starts_on = _parse_iso_date(med.get(CONF_MED_STARTS_ON))

        # Anchor (DTSTART for the rrule) priority:
        #   1. starts_on — user-set start date for interval mode. Critical
        #      for interval schedules so the every-N-day cycle phase is
        #      stable across HA restarts and reproducible from form input.
        #   2. cycle_anchor — for SCHEDULE_TYPE_CYCLE.
        #   3. ends_on — fallback for back-compat with legacy data.
        #   4. date.today() — last-resort default. Only happens for fresh
        #      pre-v0.2.4 interval prescriptions before migration runs.
        anchor = starts_on or cycle_anchor or ends_on or date.today()

        return cls(
            rrule_str=med.get(CONF_MED_RRULE) or "FREQ=DAILY",
            schedule_type=med.get(CONF_MED_SCHEDULE_TYPE) or SCHEDULE_TYPE_DAILY,
            times=tuple(times),
            anchor=anchor,
            starts_on=starts_on,
            cycle_anchor=cycle_anchor,
            cycle_on_days=med.get(CONF_MED_CYCLE_ON_DAYS),
            cycle_off_days=med.get(CONF_MED_CYCLE_OFF_DAYS),
            ends_on=ends_on,
            times_per_weekday=times_per_weekday,
        )


def _parse_iso_date(value) -> date | None:
    """Tolerant ISO-date parser for stored strings; None on anything bad."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
