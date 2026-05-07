"""Source registry & factory.

In v0.2.13 this package shipped three source clients (VARA, FASS, RMS),
each requiring gated access (E-hälsomyndigheten SFTP, Lif credentials,
EMA SPOR account) that no end-user of a private Home Assistant
integration could realistically obtain. They were removed in v0.2.14.

The package and its base interface remain so future sources (e.g. the
FASS web-link enrichment planned for v0.2.16) can plug in without
re-introducing the package skeleton. ``build_sources`` currently
returns an empty list — no built-in sources ship by default.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .base import LookupKey, LookupResult, MedicineSource

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "LookupKey",
    "LookupResult",
    "MedicineSource",
    "build_sources",
]

#: Source-id -> class. Empty after v0.2.14; future built-in sources
#: register themselves here.
_REGISTRY: dict[str, type[MedicineSource]] = {}


def build_sources(
    enabled: list[str],
    config: dict[str, Any],
    session: aiohttp.ClientSession,
) -> list[MedicineSource]:
    """Instantiate the sources the user enabled.

    With no sources currently in ``_REGISTRY`` this returns an empty
    list regardless of what's in ``enabled``. The arguments are kept
    for forward compatibility — coordinator.py and __init__.py call
    this with the same signature they did pre-v0.2.14.
    """
    result: list[MedicineSource] = []
    for source_id in enabled:
        cls = _REGISTRY.get(source_id)
        if cls is None:
            _LOGGER.debug("Skipping unknown source id %s (no registered class)", source_id)
            continue
        try:
            result.append(cls(session=session, config=config))
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to build source %s: %s", source_id, err)
    return result
