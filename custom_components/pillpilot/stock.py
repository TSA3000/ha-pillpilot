"""Stock model — derived inventory from a per-prescription event ledger.

Stock is never stored as a number. It is computed from a ledger of
``StockEvent`` entries (a ``set`` baseline plus ``refill`` / ``add`` /
``remove`` deltas) minus the units consumed by taken doses after that
baseline. Removing a taken record therefore restores stock with no extra
work, and bulk takes net out correctly — the value is a function of which
records exist, not a counter mutated on every action.

Pure model with no Home Assistant imports, so it can be unit-tested in
isolation (same pattern as ``schedule.py`` and ``dose.py``). The coordinator
owns the ledger, parses timestamps, builds the forward occurrence list from a
``Schedule``, and fires events; this module only does the arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from .const import (
    STOCK_EVENT_ADD,
    STOCK_EVENT_REFILL,
    STOCK_EVENT_REMOVE,
    STOCK_EVENT_SET,
    STOCK_REMINDER_DAYS,
    STOCK_REMINDER_DOSES,
    STOCK_REMINDER_UNITS,
)


@dataclass
class StockEvent:
    """One entry in a prescription's stock ledger.

    ``ts`` is an ISO timestamp string. ``amount`` is the value for ``set``
    or the magnitude of the delta for ``refill`` / ``add`` / ``remove``.
    ``pack_count`` and ``expiry`` are optional breadcrumbs carried by
    refills (and ``set`` when entered with an expiry).
    """

    kind: str
    ts: str
    amount: float = 0.0
    pack_count: int | None = None
    expiry: str | None = None


_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)


def _parse(ts: str | None) -> datetime:
    """Parse an ISO timestamp to an aware datetime.

    Naive timestamps are treated as UTC; anything unparseable sorts as the
    epoch so it never wins the ``set``-anchor comparison.
    """
    if not ts:
        return _EPOCH
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return _EPOCH
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def current_stock(
    events: list[StockEvent],
    consumed: Iterable[tuple[str, float]],
) -> float | None:
    """Derive current stock from the ledger and consumption history.

    ``consumed`` is an iterable of ``(taken_at_iso, units_consumed)`` for the
    prescription's taken doses.

    Returns ``None`` when stock is untracked — no ``set`` baseline and no
    positive event has ever been recorded. Once a baseline or a refill/add
    exists, returns a number clamped at zero.

    The most recent ``set`` is the anchor: only events and doses strictly
    after its timestamp count, so a fresh "recount what's in the drawer"
    isn't dragged negative by doses logged before it.
    """
    sets = [e for e in events if e.kind == STOCK_EVENT_SET]
    positives = [
        e for e in events if e.kind in (STOCK_EVENT_REFILL, STOCK_EVENT_ADD)
    ]
    if not sets and not positives:
        return None

    if sets:
        anchor = max(sets, key=lambda e: _parse(e.ts))
        base = float(anchor.amount)
        base_ts = _parse(anchor.ts)
    else:
        base = 0.0
        base_ts = _EPOCH

    total = base
    for e in events:
        if _parse(e.ts) <= base_ts:
            continue
        if e.kind in (STOCK_EVENT_REFILL, STOCK_EVENT_ADD):
            total += float(e.amount)
        elif e.kind == STOCK_EVENT_REMOVE:
            total -= float(e.amount)

    for taken_at, units in consumed:
        if _parse(taken_at) > base_ts:
            total -= float(units or 0.0)

    return max(total, 0.0)


def project_runout(
    occurrences: list[datetime],
    unit_count: float,
    stock: float,
) -> tuple[int, date | None]:
    """Walk future occurrences subtracting ``unit_count`` from ``stock``.

    ``occurrences`` is the forward-ordered list of scheduled datetimes from
    now (the coordinator builds it from the prescription's ``Schedule``).

    Returns ``(doses_left, run_out_date)``: how many whole doses the current
    stock affords, and the date of the first occurrence it can't cover. If
    stock outlasts the supplied window, ``run_out_date`` is ``None``.
    """
    if unit_count <= 0:
        return (0, None)
    remaining = stock
    doses_left = 0
    for occ in occurrences:
        if remaining + 1e-9 < unit_count:
            return (doses_left, occ.date())
        remaining -= unit_count
        doses_left += 1
    return (doses_left, None)


def is_low(
    mode: str,
    threshold: float,
    *,
    stock: float | None,
    doses_left: int | None,
    days_left: int | None,
) -> bool:
    """Evaluate the refill-reminder threshold for the given mode."""
    if stock is None:
        return False
    if mode == STOCK_REMINDER_UNITS:
        return stock <= threshold
    if mode == STOCK_REMINDER_DOSES:
        return doses_left is not None and doses_left <= threshold
    if mode == STOCK_REMINDER_DAYS:
        return days_left is not None and days_left <= threshold
    return False


def expiry_status(
    expiry: str | None, today: date, lead_days: int
) -> str | None:
    """Return ``"expired"``, ``"expiring"``, or ``None`` for a stock expiry.

    ``"expiring"`` means within ``lead_days`` of the date (inclusive) but not
    yet past it.
    """
    if not expiry:
        return None
    try:
        exp = date.fromisoformat(expiry)
    except (TypeError, ValueError):
        return None
    if exp < today:
        return "expired"
    if (exp - today).days <= lead_days:
        return "expiring"
    return None
