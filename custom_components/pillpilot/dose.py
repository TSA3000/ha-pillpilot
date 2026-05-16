"""Dose model — a structured medicine dose.

A dose is parameterised by four things:
  - type             (pill / drops / injection)
  - count            (how many of those units per dose)
  - variant_strength (verbatim catalog string, e.g. "5 mg")
  - variant_form     (verbatim catalog form, e.g. "Filmdragerad tablett")

v0.2.13: rewritten around catalog variants. The legacy
``strength_mg: float`` field was replaced by ``variant_strength: str``
because real-world strengths aren't always single-number mg —
combo drugs are "87 mikrogram/5 mikrogram/9 mikrogram", insulins are
"100 E/ml", topicals are "0,1 %". Storing the catalog string
verbatim means every variant round-trips losslessly; the total in
mg is computed on the fly only when ``variant_strength`` matches a
simple ``<number> mg`` pattern.

Pure model with no Home Assistant dependencies — so it can be
unit-tested in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .const import MED_TYPE_UNIT_LABELS


# Matches "5 mg", "0.5 mg", "0,15 mg" — the only shape we can
# safely convert to a numeric total. Anything else (mg/ml,
# E/ml, mikrogram, combo forms with "/") returns None.
_MG_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*mg\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Dose:
    """An immutable, validated structured dose."""

    med_type: str
    count: float
    variant_strength: str
    variant_form: str

    @property
    def total_mg(self) -> float | None:
        """Total dose in mg, only when variant parses as ``<number> mg``.

        Returns ``None`` for combo, concentration, IU, percent and
        any other non-trivially-mg variants. Callers should expose
        the value as ``None``/``unknown`` rather than zero — zero is
        a meaningful dose, missing is not.
        """
        m = _MG_RE.match(self.variant_strength or "")
        if not m:
            return None
        try:
            value = float(m.group(1).replace(",", "."))
        except ValueError:
            return None
        return value * float(self.count)

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
        """Human-readable summary.

        Examples:
          - "2 pills × 500 mg Filmdragerad tablett = 1000 mg"
          - "1 puff × 87 mikrogram/5 mikrogram/9 mikrogram Inhalationsspray"
          - "10 units × 100 E/ml Injektionsvätska"
          - "1 pill"                       (no variant data at all)

        The "= total mg" suffix is appended only when the variant
        strength parses as a simple ``<number> mg`` — otherwise the
        formatter would have to invent an arithmetic that doesn't
        exist (no meaningful total for combos / concentrations / IU).
        """
        head = f"{self.count:g} {self.unit_label}"
        desc_bits: list[str] = []
        if self.variant_strength:
            desc_bits.append(self.variant_strength)
        if self.variant_form:
            desc_bits.append(self.variant_form)
        if not desc_bits:
            return head
        desc = " ".join(desc_bits)
        mg = self.total_mg
        tail = f" = {mg:g} mg" if mg is not None else ""
        return f"{head} × {desc}{tail}"

    @classmethod
    def from_medicine_dict(cls, med: dict) -> "Dose | None":
        """Construct from a config-flow medicine dict, or return None.

        Returns ``None`` if the dict doesn't carry the structured
        fields. Reads the v0.2.13 variant fields; legacy
        ``unit_strength_mg`` entries from older installs are migrated
        at integration setup so this code never sees them.
        """
        from .const import (
            CONF_MED_TYPE,
            CONF_MED_UNIT_COUNT,
            CONF_MED_VARIANT_FORM,
            CONF_MED_VARIANT_STRENGTH,
        )

        med_type = med.get(CONF_MED_TYPE)
        count = med.get(CONF_MED_UNIT_COUNT)
        if med_type is None or count is None:
            return None
        return cls(
            med_type=med_type,
            count=float(count),
            variant_strength=str(med.get(CONF_MED_VARIANT_STRENGTH) or ""),
            variant_form=str(med.get(CONF_MED_VARIANT_FORM) or ""),
        )
