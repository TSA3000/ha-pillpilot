"""Medicine name database — bundled list + optional remote refresh.

This module owns the Swedish medicine name list used by the Add Medicine
form's autocomplete dropdown. Two storage layers:

  1. **Bundled file** at ``custom_components/pillpilot/medicines_se.json``.
     Ships with every release. Always available, even offline / on first
     install before any refresh has happened.

  2. **HA Store** (``pillpilot.medicines_se``). Optional override —
     populated when the user clicks "Refresh medicine list" or calls
     the ``pillpilot.refresh_medicines_database`` service. Lives in
     ``<config>/.storage/`` and persists across HA restarts.

Load priority on startup: stored copy if present, else bundled. The
storage layer means a user who refreshed once gets community-PR'd
additions on the next reload without waiting for a HACS release of the
integration itself.

Each medicine entry has:
    name              str      — display name (usually brand)
    aliases           list[str] — common misspellings / generic names /
                                 alt brands. Searchable in dropdown.
    active_substance  str      — Swedish or Latin name
    atc_code          str      — WHO ATC code, "" if uncertain
    common_forms      list[str] — informational

The module is intentionally I/O-light: the JSON is small (~50 KB at
216 entries) and load happens once at integration setup. No per-keystroke
I/O during dropdown filtering.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

#: Where the bundled list lives, relative to this file.
BUNDLED_PATH = Path(__file__).parent / "medicines_se.json"

#: HA Store namespace + version.
STORE_KEY = f"{DOMAIN}.medicines_se"
STORE_VERSION = 1

#: Default URL the refresh action pulls from. Points at the master list
#: in the public GitHub repo. Users can override via CONF_MEDICINES_DB_URL
#: in the integration's reconfigure flow if they fork the list.
DEFAULT_MEDICINES_DB_URL = (
    "https://raw.githubusercontent.com/TSA3000/ha-pillpilot/main/"
    "custom_components/pillpilot/medicines_se.json"
)


def _normalize_variant(raw: Any) -> dict[str, str] | None:
    """Coerce one variant dict. Drops entries with no usable signal."""
    if not isinstance(raw, dict):
        return None
    npl_id = str(raw.get("npl_id") or "").strip()
    strength = str(raw.get("strength") or "").strip()
    form = str(raw.get("form") or "").strip()
    if not (npl_id or strength or form):
        return None
    return {"npl_id": npl_id, "strength": strength, "form": form}


def _normalize_entry(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Defensive parse of a single medicine entry.

    Returns ``None`` for entries without a usable name. Other fields
    are coerced to safe defaults — never raises on missing or
    wrong-typed fields. The bundled list is well-formed; this
    defensiveness is for user-supplied lists fetched from the
    configured URL.

    v0.2.12: accepts schema v2 entries that carry a ``variants``
    list of ``{npl_id, strength, form}``. ``npl_id`` and
    ``common_forms`` are back-derived from the variants for legacy
    code paths that read those fields directly (top-level
    ``npl_id`` becomes the first variant's NPL; ``common_forms``
    becomes the deduped list of variant forms). Schema v1 entries
    with top-level ``npl_id`` / ``common_forms`` continue to work
    unchanged.
    """
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    aliases_raw = raw.get("aliases") or []
    if not isinstance(aliases_raw, list):
        aliases_raw = []

    variants_raw = raw.get("variants") or []
    if not isinstance(variants_raw, list):
        variants_raw = []
    variants: list[dict[str, str]] = []
    for v in variants_raw:
        norm = _normalize_variant(v)
        if norm:
            variants.append(norm)

    # Top-level npl_id and common_forms (schema v1 shape) take
    # precedence when present, otherwise derive from variants.
    top_npl = str(raw.get("npl_id") or "").strip()
    if not top_npl and variants:
        top_npl = variants[0]["npl_id"]

    forms_raw = raw.get("common_forms") or []
    if not isinstance(forms_raw, list):
        forms_raw = []
    common_forms = [str(f).strip() for f in forms_raw if str(f).strip()]
    if not common_forms and variants:
        seen: set[str] = set()
        for v in variants:
            f = v["form"]
            if f and f not in seen:
                seen.add(f)
                common_forms.append(f)

    return {
        "name": name,
        "aliases": [str(a).strip() for a in aliases_raw if str(a).strip()],
        "active_substance": str(raw.get("active_substance") or "").strip(),
        "atc_code": str(raw.get("atc_code") or "").strip(),
        "npl_id": top_npl,
        "common_forms": common_forms,
        "variants": variants,
    }


def _normalize_list(raw: dict[str, Any]) -> dict[str, Any]:
    """Defensive parse of a full medicines list document."""
    medicines_raw = raw.get("medicines") or []
    if not isinstance(medicines_raw, list):
        medicines_raw = []
    medicines: list[dict[str, Any]] = []
    for entry in medicines_raw:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_entry(entry)
        if normalized:
            medicines.append(normalized)
    return {
        "schema_version": int(raw.get("schema_version") or 1),
        "list_version": str(raw.get("list_version") or "unknown"),
        "updated": str(raw.get("updated") or ""),
        "language": str(raw.get("language") or "sv"),
        "country": str(raw.get("country") or "SE"),
        "medicines": medicines,
    }


def _bundled_has_content_drift(
    bundled_data: dict[str, Any] | None,
    stored: Any,
) -> bool:
    """Detect a schema upgrade that didn't bump ``list_version``.

    v0.2.11: a same-version comparison isn't enough — when the
    integration adds a new field on entries (e.g. ``npl_id`` in
    v0.2.10) without bumping ``list_version``, the bundled-wins
    check on version alone leaves users on the stored copy
    forever. This helper samples up to 500 entries from each
    side and flags drift when bundled has a field populated on
    >25% of entries while stored has it on <5%: a strong signal
    that the stored copy was written by an older normalizer
    that stripped the field.

    v0.2.12: ``variants`` added to the sampled fields so
    schema v2 catalogs (per-medicine variants array) force-load
    over stored v1 caches even when the version stamp matches.
    """
    if not bundled_data or not isinstance(stored, dict):
        return False
    bundled_meds = bundled_data.get("medicines") or []
    stored_meds = stored.get("medicines") or []
    if not bundled_meds or not stored_meds:
        return False
    sample = min(500, len(bundled_meds), len(stored_meds))

    def populated(med: Any, field: str) -> bool:
        v = med.get(field) if isinstance(med, dict) else None
        if field == "variants":
            return isinstance(v, list) and len(v) > 0
        return isinstance(v, str) and bool(v.strip())

    for field in ("variants", "npl_id", "atc_code", "active_substance"):
        b_pop = sum(1 for m in bundled_meds[:sample] if populated(m, field))
        s_pop = sum(1 for m in stored_meds[:sample] if populated(m, field))
        if b_pop > sample * 0.25 and s_pop < sample * 0.05:
            return True
    return False


class MedicineDatabase:
    """Owns the in-memory medicines list + the refresh logic.

    One instance lives in ``hass.data[DOMAIN]["medicine_db"]``,
    initialized once during ``async_setup_entry``. config_flow's
    autocomplete dropdown reads from it; the refresh service writes to
    it.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORE_VERSION, STORE_KEY)
        self._data: dict[str, Any] = _empty_doc()
        self._loaded = False

    @property
    def data(self) -> dict[str, Any]:
        """The currently loaded list document. Always non-None."""
        return self._data

    @property
    def medicines(self) -> list[dict[str, Any]]:
        """Just the list of medicine entries."""
        return self._data.get("medicines", [])

    @property
    def list_version(self) -> str:
        return self._data.get("list_version", "unknown")

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    async def async_load(self) -> None:
        """Load on integration startup. Bundled wins if it's newer
        or if there's content drift.

        v0.2.10: compares ``list_version`` between the integration's
        bundled file and any stored copy. The lexicographically newer
        one wins — the ``YYYY.MM.DD-N`` format sorts correctly that
        way. Pre-v0.2.10 the stored copy always won, so users who'd
        ever clicked **Refresh** stayed pinned to that cached list
        across integration upgrades and never saw new bundled
        medicines (e.g. the v0.2.9 jump from 216 → 7331 entries was
        invisible to anyone with a stored copy). Explicit URL
        refreshes still win when the URL is ahead of the bundle.

        v0.2.11: same-version comparison isn't enough when a release
        adds a field on entries without bumping ``list_version`` —
        v0.2.10 added ``npl_id`` per entry while keeping the
        ``2026.05.10-1`` version, leaving the v0.2.10 fix invisible
        to anyone whose stored cache was written by v0.2.9's
        normalizer. ``_bundled_has_content_drift`` samples entries
        from both sides and forces a bundled reload when the
        bundled has a populated field the stored copy lacks across
        the board.
        """
        stored = await self._store.async_load()
        stored_version = ""
        if stored and isinstance(stored, dict) and stored.get("medicines"):
            stored_version = str(stored.get("list_version") or "")

        bundled_data: dict[str, Any] | None = None
        try:
            bundled_text = await self._hass.async_add_executor_job(
                BUNDLED_PATH.read_text, "utf-8"
            )
            bundled_data = json.loads(bundled_text)
        except (OSError, json.JSONDecodeError) as err:
            _LOGGER.warning(
                "Could not load bundled medicines list at %s: %s",
                BUNDLED_PATH, err,
            )
        bundled_version = str((bundled_data or {}).get("list_version") or "")

        version_wins = (
            bundled_data is not None
            and (not stored_version or bundled_version > stored_version)
        )
        drift_wins = bundled_data is not None and _bundled_has_content_drift(
            bundled_data, stored
        )

        if version_wins or drift_wins:
            self._data = _normalize_list(bundled_data)
            self._loaded = True
            _LOGGER.debug(
                "Loaded bundled medicines list (version=%s, count=%d, "
                "stored=%s, reason=%s)",
                self._data["list_version"], len(self._data["medicines"]),
                stored_version or "none",
                "version" if version_wins else "content_drift",
            )
            return

        if stored and isinstance(stored, dict) and stored.get("medicines"):
            self._data = _normalize_list(stored)
            self._loaded = True
            _LOGGER.debug(
                "Loaded medicines list from storage (version=%s, count=%d, "
                "bundled=%s)",
                self._data["list_version"], len(self._data["medicines"]),
                bundled_version or "none",
            )
            return

        _LOGGER.error(
            "Could not load any medicines list (stored=missing, bundled=missing)"
        )
        self._data = _empty_doc()
        self._loaded = True

    async def async_refresh_from_url(self, url: str) -> tuple[bool, str]:
        """Fetch a fresh medicines list from `url` and persist it.

        Returns ``(ok, message)``. On success ``message`` is the new
        ``list_version`` string; on failure it's a human-readable error
        the caller can surface in a notification.
        """
        session: aiohttp.ClientSession = async_get_clientsession(self._hass)
        try:
            async with asyncio.timeout(20):
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return False, f"HTTP {resp.status} from {url}"
                    payload = await resp.json(content_type=None)
        except asyncio.TimeoutError:
            return False, f"Timeout fetching {url}"
        except aiohttp.ClientError as err:
            return False, f"Network error: {err}"
        except json.JSONDecodeError as err:
            return False, f"Response was not valid JSON: {err}"

        if not isinstance(payload, dict) or "medicines" not in payload:
            return False, "Response did not look like a medicines list"

        normalized = _normalize_list(payload)
        if not normalized["medicines"]:
            return False, "Response contained no usable medicine entries"

        await self._store.async_save(normalized)
        self._data = normalized
        _LOGGER.info(
            "Refreshed medicines list from %s — version=%s, count=%d",
            url, normalized["list_version"], len(normalized["medicines"]),
        )
        return True, normalized["list_version"]

    async def async_reset_to_bundled(self) -> None:
        """Wipe the stored copy and fall back to the bundled file."""
        await self._store.async_remove()
        await self.async_load()


def _empty_doc() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "list_version": "empty",
        "updated": "",
        "language": "sv",
        "country": "SE",
        "medicines": [],
    }


def build_dropdown_options(
    medicines: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build the option list for ``SelectSelector`` in the Add Medicine form.

    The label includes aliases in brackets so HA's frontend substring-match
    on the label finds entries when the user types a misspelling. Format:

        "Alvedon — paracetamol [alvadon, aledon]"

    The em-dash separates the brand from the active substance, the
    bracketed aliases are visually subtle but searchable. Without the
    aliases-in-label trick, someone typing "alvadon" wouldn't
    find Alvedon — which is the whole point of this feature.
    """
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for med in medicines:
        name = med.get("name", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        substance = med.get("active_substance", "").strip()
        aliases = med.get("aliases", [])
        # Keep alias list short in the label — first 4 max
        alias_str = ", ".join(aliases[:4]) if aliases else ""
        if substance and alias_str:
            label = f"{name} — {substance} [{alias_str}]"
        elif substance:
            label = f"{name} — {substance}"
        elif alias_str:
            label = f"{name} [{alias_str}]"
        else:
            label = name
        options.append({"value": name, "label": label})
    # Stable alphabetical so the dropdown isn't surprising to scroll
    options.sort(key=lambda o: o["value"].lower())
    return options


def lookup_by_name(
    medicines: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    """Find a medicine entry by exact name (case-insensitive).

    Used by the Add Medicine submit-handler to auto-fill ATC code and
    active substance when the user picked from the dropdown. Returns
    ``None`` if the name was free-text typed (not in the list).
    """
    if not name:
        return None
    needle = name.strip().lower()
    for med in medicines:
        if med.get("name", "").lower() == needle:
            return med
    return None


def lookup_by_name_or_alias(
    medicines: list[dict[str, Any]], query: str | None
) -> dict[str, Any] | None:
    """Find a medicine entry by exact name OR alias (case-insensitive).

    Used by the panel-side Add/Edit modal to resolve user input that
    might be either a brand name or one of the registered alternate
    spellings / generic names. Brand-name matches always win over alias
    matches — if a typed string is both a brand AND another medicine's
    alias, the brand entry wins. This avoids surprise auto-renames
    (e.g. typing the generic "Paracetamol" must not silently switch to
    "Alvedon" just because Alvedon happens to list "paracetamol" as an
    alias).

    Returns ``None`` when the input is empty or doesn't match anything.
    """
    if not query:
        return None
    needle = query.strip().lower()
    if not needle:
        return None
    # First pass: brand-name exact match wins.
    for med in medicines:
        if med.get("name", "").lower() == needle:
            return med
    # Second pass: alias match.
    for med in medicines:
        for alias in med.get("aliases", []) or []:
            if isinstance(alias, str) and alias.strip().lower() == needle:
                return med
    return None


def sanitize_for_ws(
    medicines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project the medicines list down to the fields the panel needs.

    The panel's autocomplete/auto-fill needs ``name``, ``aliases``,
    ``active_substance``, ``atc_code``, ``npl_id`` (since v0.2.10),
    and ``variants`` (since v0.2.12). The bundled list also carries
    ``common_forms``, vendor metadata, and pre-list comments — all
    irrelevant on the wire and worth not shipping over the websocket
    on every panel load.

    Nameless entries are dropped; missing optional fields are emitted
    as empty strings or empty lists so the panel can rely on the
    shape.
    """
    out: list[dict[str, Any]] = []
    for med in medicines:
        name = (med.get("name") or "").strip()
        if not name:
            continue
        aliases_raw = med.get("aliases") or []
        aliases = [
            a.strip() for a in aliases_raw
            if isinstance(a, str) and a.strip()
        ]
        variants_raw = med.get("variants") or []
        variants: list[dict[str, str]] = []
        if isinstance(variants_raw, list):
            for v in variants_raw:
                if not isinstance(v, dict):
                    continue
                variants.append({
                    "npl_id": (v.get("npl_id") or "").strip(),
                    "strength": (v.get("strength") or "").strip(),
                    "form": (v.get("form") or "").strip(),
                })
        out.append({
            "name": name,
            "aliases": aliases,
            "active_substance": (med.get("active_substance") or "").strip(),
            "atc_code": (med.get("atc_code") or "").strip(),
            "npl_id": (med.get("npl_id") or "").strip(),
            "variants": variants,
        })
    return out
