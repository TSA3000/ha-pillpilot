"""Schedule model — daily/weekly/monthly recurrence rule.

A schedule answers four questions about when a medicine is due:

  * ``matches_date(d)``   does this date fall on a scheduled day?
  * ``occurrences_on(d)`` what datetimes apply on this date?
  * ``next_after(now)``   what's the next scheduled occurrence after now?
  * ``closest_to(when)``  given a moment, which scheduled occurrence is
                          it most likely referring to (±1 day window)?

Pure model — no Home Assistant imports. The coordinator delegates all
schedule math to instances of this class, which makes the rules
unit-testable and keeps the orchestration layer thin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from .const import (
    CONF_MED_DAYS,
    CONF_MED_DAYS_OF_MONTH,
    CONF_MED_FREQUENCY,
    CONF_MED_TIMES,
    FREQ_DAILY,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
)


@dataclass(frozen=True)
class Schedule:
    """Recurrence rule for a single medicine."""

    frequency: str
    times: tuple[time, ...] = field(default_factory=tuple)
    days_of_week: tuple[int, ...] = field(default_factory=tuple)   # 0=Mon..6=Sun
    days_of_month: tuple[int, ...] = field(default_factory=tuple)  # 1..31

    # ----- queries -------------------------------------------------------

    def matches_date(self, d: date) -> bool:
        """Does this date match the frequency rule?

        Daily   → always.
        Weekly  → only if ``d.weekday()`` is in ``days_of_week``.
        Monthly → only if ``d.day`` is in ``days_of_month``.
        """
        if self.frequency == FREQ_DAILY:
            return True
        if self.frequency == FREQ_WEEKLY:
            return d.weekday() in self.days_of_week
        if self.frequency == FREQ_MONTHLY:
            return d.day in self.days_of_month
        return False

    def occurrences_on(
        self, d: date, tz: tzinfo | None = None
    ) -> list[datetime]:
        """All scheduled datetimes on the given date, sorted ascending."""
        if not self.matches_date(d):
            return []
        return sorted(
            datetime.combine(d, t).replace(tzinfo=tz) for t in self.times
        )

    def next_after(
        self, now: datetime, lookahead_days: int = 92
    ) -> datetime | None:
        """The first scheduled occurrence strictly after ``now``.

        ``lookahead_days`` defaults to 92 (about three months) so monthly
        rules with a day that doesn't exist in every month still surface.
        Worst case is "day 31, starting Jan 31" — the next valid date is
        Mar 31, 59 days away. 92 days gives comfortable margin even for
        chained month skips.
        """
        if not self.times:
            return None
        for offset in range(lookahead_days):
            d = (now + timedelta(days=offset)).date()
            for occurrence in self.occurrences_on(d, tz=now.tzinfo):
                if occurrence > now:
                    return occurrence
        return None

    def closest_to(self, when: datetime) -> datetime | None:
        """The scheduled occurrence closest to ``when`` within ±1 day.

        Used when recording a 'taken' action — pick which scheduled
        slot the user is acknowledging.
        """
        candidates: list[datetime] = []
        for offset in (-1, 0):
            d = (when + timedelta(days=offset)).date()
            candidates.extend(self.occurrences_on(d, tz=when.tzinfo))
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs((c - when).total_seconds()))

    # ----- construction --------------------------------------------------

    @classmethod
    def from_medicine_dict(cls, med: dict[str, Any]) -> "Schedule":
        """Build a Schedule from a config-flow medicine dict.

        Backwards-compatible with v0.1.0-style entries that lack
        ``frequency`` — those default to weekly with all weekdays
        selected, preserving the original behaviour.
        """
        times: list[time] = []
        for t_str in med.get(CONF_MED_TIMES, []):
            hh, mm = t_str.split(":")
            times.append(time(int(hh), int(mm)))
        return cls(
            frequency=med.get(CONF_MED_FREQUENCY) or FREQ_WEEKLY,
            times=tuple(times),
            days_of_week=tuple(med.get(CONF_MED_DAYS) or list(range(7))),
            days_of_month=tuple(med.get(CONF_MED_DAYS_OF_MONTH) or []),
        )
