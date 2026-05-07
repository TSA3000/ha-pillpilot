"""PillPilot side panel registration.

Adds the **PillPilot** entry to Home Assistant's left sidebar.
Clicking it opens a custom panel — see ``frontend/panel.js`` for the
UI itself. The Python side here:

  1. Reads the panel visibility setting from the config entry
     (``CONF_PANEL_VISIBILITY``: "everyone" / "admins" / "hidden").
  2. If "hidden", skips registration entirely — no sidebar entry,
     no static asset path served.
  3. Otherwise, serves the integration's ``frontend/`` directory as
     static files under ``/pillpilot_static`` and registers a
     sidebar entry whose body is the ``<pillpilot-panel>`` custom
     element defined in panel.js.
  4. "admins" sets ``require_admin=True`` on the panel registration
     so non-admin users don't see it in their sidebar.

Each user can additionally hide the panel from their own sidebar via
HA's built-in **Profile → Edit sidebar** — that's HA-core behavior we
inherit for free, no per-user config needed here.

Registration is idempotent: a sentinel in ``hass.data[DOMAIN]`` keeps
us from registering twice on integration reload. Unregister cleanly
on entry unload, then re-register on the next setup with whatever
options are current.

v0.2.18 cache-bust: the ``module_url`` for panel.js now carries a
``?v=<version>`` query string read from manifest.json. HA already
sets ``cache_headers=False`` on the static path, but browsers still
apply heuristic caching to .js URLs — so on every release the same
URL was being served from cache and users had to hard-refresh to see
new code (which v0.2.17 install caught us on). The query string
changes per release, giving the browser a fresh URL it won't have
cached, while the HTTP server happily serves the same file.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_PANEL_VISIBILITY,
    DEFAULT_PANEL_VISIBILITY,
    DOMAIN,
    PANEL_VIS_ADMINS,
    PANEL_VIS_HIDDEN,
)

_LOGGER = logging.getLogger(__name__)

PANEL_URL = "pillpilot"
PANEL_TITLE = "PillPilot"
PANEL_ICON = "mdi:pill"

#: HTTP path under which we serve the static frontend directory.
#: Chosen to be unlikely to collide with other integrations.
STATIC_URL_PATH = "/pillpilot_static"

#: Sentinel keys in ``hass.data[DOMAIN]`` so we don't re-register on reload.
_PANEL_REGISTERED = "panel_registered"
_STATIC_PATH_REGISTERED = "static_path_registered"


def _read_integration_version() -> str:
    """Read the integration version from manifest.json.

    Module-level call: runs once at import. The file lives next to
    this module so the read is essentially free and shouldn't fail.
    Falls back to ``"unknown"`` on any error so registration still
    works in an unexpected environment — the cache-bust just becomes
    a no-op until the next genuine release.
    """
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            return str(json.load(f).get("version") or "unknown")
    except (OSError, json.JSONDecodeError, ValueError):
        return "unknown"


_PANEL_VERSION = _read_integration_version()


async def async_register_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the static path + sidebar panel based on the entry's
    visibility setting.

    Safe to call repeatedly. The sentinel in ``hass.data[DOMAIN]``
    keeps us from registering twice. The static path is registered
    only once for the integration's lifetime — HA doesn't have a
    public API to deregister static paths, so even if the user
    switches from "everyone" to "hidden" and back, the path stays
    served (which is harmless: only the sidebar entry comes and goes).
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    visibility = entry.data.get(CONF_PANEL_VISIBILITY, DEFAULT_PANEL_VISIBILITY)

    if visibility == PANEL_VIS_HIDDEN:
        _LOGGER.debug("Panel visibility is 'hidden'; skipping registration")
        return

    integration_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(integration_dir, "frontend")

    if not os.path.isdir(static_dir):
        _LOGGER.warning(
            "Frontend directory not found at %s; panel will not load",
            static_dir,
        )
        return

    # Static path: register once per HA lifetime
    if not domain_data.get(_STATIC_PATH_REGISTERED):
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(STATIC_URL_PATH, static_dir, cache_headers=False)]
            )
            domain_data[_STATIC_PATH_REGISTERED] = True
        except Exception as err:  # noqa: BLE001
            # Non-fatal: most likely already registered from a previous setup
            _LOGGER.debug("Static path registration skipped: %s", err)
            domain_data[_STATIC_PATH_REGISTERED] = True

    # Sidebar entry: register every time we have a visible mode and
    # nothing's currently registered. async_unregister_panel pops
    # the sentinel when an entry unloads, so the next setup re-registers
    # with potentially different require_admin.
    if domain_data.get(_PANEL_REGISTERED):
        return

    require_admin = visibility == PANEL_VIS_ADMINS
    try:
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            frontend_url_path=PANEL_URL,
            config={
                "_panel_custom": {
                    "name": "pillpilot-panel",
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": (
                        f"{STATIC_URL_PATH}/panel.js?v={_PANEL_VERSION}"
                    ),
                },
            },
            require_admin=require_admin,
        )
        _LOGGER.info(
            "PillPilot panel registered at /%s (require_admin=%s, panel_version=%s)",
            PANEL_URL,
            require_admin,
            _PANEL_VERSION,
        )
    except ValueError as err:
        # Most likely panel already exists from a previous setup
        _LOGGER.debug("Panel registration skipped: %s", err)

    domain_data[_PANEL_REGISTERED] = True


async def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the panel from HA's sidebar.

    Called when the integration is unloaded — either because the user
    is removing it, or because it's reloading after a visibility
    change. We don't unregister the static path here (HA has no
    public API for that and a stale path is harmless); only the
    sidebar entry needs explicit removal so it disappears immediately.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get(_PANEL_REGISTERED):
        return

    try:
        frontend.async_remove_panel(hass, PANEL_URL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Panel removal failed (already gone?): %s", err)

    domain_data.pop(_PANEL_REGISTERED, None)
