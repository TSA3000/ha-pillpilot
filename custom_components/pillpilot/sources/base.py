"""Common protocol that every data source implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LookupKey:
    """The set of identifiers a medicine can be looked up by."""

    npl_id: str | None = None
    varunummer: str | None = None
    atc_code: str | None = None
    name: str | None = None


@dataclass
class LookupResult:
    """Normalized output from a source. Sources fill what they have."""

    source_id: str
    name: str | None = None
    strength: str | None = None
    pharmaceutical_form: str | None = None     # "tablet", "injection", etc.
    route_of_administration: str | None = None  # "oral", "topical", etc.
    atc_code: str | None = None
    atc_label: str | None = None
    active_substances: list[str] = field(default_factory=list)
    manufacturer: str | None = None
    pack_size: str | None = None
    narcotic: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # source-specific payload


class MedicineSource(Protocol):
    """All medicine data sources implement this minimal interface."""

    id: str
    display_name: str

    async def async_setup(self) -> None:
        """One-time setup (download data, prime caches, etc.)."""
        ...

    async def async_refresh(self) -> None:
        """Periodic refresh (re-pull data if stale)."""
        ...

    async def lookup(self, key: LookupKey) -> LookupResult | None:
        """Look up a single medicine. Return None if not found."""
        ...

    async def test_connection(self) -> bool:
        """Cheap probe used by the config flow."""
        ...

    async def async_close(self) -> None:
        """Tear-down hook (release file handles, etc.)."""
        ...
