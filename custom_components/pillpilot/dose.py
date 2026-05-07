"""Dose model — a structured medicine dose.

A dose is parameterised by three things:
  - type   (pill / drops / injection)
  - count  (how many of those units per dose)
  - strength_mg  (mg per unit)

The total dose in mg is ``count * strength_mg``. Formatting the dose for
display is its only behaviour. Pure model with no Home Assistant
dependencies — so it can be unit-tested in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .const import MED_TYPE_UNIT_LABELS


@dataclass(frozen=True)
class Dose:
    """An immutable, validated structured dose."""

    med_type: str
    count: float
    strength_mg: float

    @property
    def total_mg(self) -> float:
        """Total dose in mg = ``count * strength_mg``."""
        return float(self.count) * float(self.strength_mg)

    @property
    def unit_label(self) -> str:
        """Singular or plural unit name, picked by ``count``.

        Examples: 1 pill, 2 pills, 5 drops, 1 injection.
        Falls back to "unit"/"units" if ``med_type`` is unrecognised.
        """
        singular, plural = MED_TYPE_UNIT_LABELS.get(
            self.med_type, ("unit", "units")
        )
        return singular if self.count == 1 else plural

    def formatted(self) -> str:
        """Human-readable summary, e.g. ``2 pills × 500 mg = 1000 mg``.

        The ``g`` formatter strips trailing zeros so 0.5 stays 0.5 and
        500.0 collapses to 500.
        """
        return (
            f"{self.count:g} {self.unit_label}"
            f" × {self.strength_mg:g} mg = {self.total_mg:g} mg"
        )

    @classmethod
    def from_medicine_dict(cls, med: dict) -> "Dose | None":
        """Construct from a config-flow medicine dict, or return None.

        Returns ``None`` if the dict doesn't carry the structured fields
        (e.g. legacy entries from before v0.1.2).
        """
        from .const import (
            CONF_MED_TYPE,
            CONF_MED_UNIT_COUNT,
            CONF_MED_UNIT_STRENGTH_MG,
        )

        med_type = med.get(CONF_MED_TYPE)
        count = med.get(CONF_MED_UNIT_COUNT)
        strength = med.get(CONF_MED_UNIT_STRENGTH_MG)
        if med_type is None or count is None or strength is None:
            return None
        return cls(
            med_type=med_type,
            count=float(count),
            strength_mg=float(strength),
        )
