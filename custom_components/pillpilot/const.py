"""Constants for the PillPilot integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "pillpilot"
PLATFORMS = ["sensor"]

# Subentry type identifier shared between __init__.py and config_flow.py.
SUBENTRY_TYPE_MEDICINE = "medicine"

# ---- per-medicine keys ----------------------------------------------
CONF_MEDICINES = "medicines"
CONF_MED_ID = "id"
CONF_MED_NAME = "name"
CONF_MED_DOSE = "dose"
CONF_MED_NOTES = "notes"
CONF_MED_NPL_ID = "npl_id"
CONF_MED_VARUNUMMER = "varunummer"
CONF_MED_ATC_CODE = "atc_code"
CONF_MED_PERSON = "person_id"          # entity_id like "person.alice", or None for household. v0.2.24: lives INSIDE each prescription dict, not at the top of the medicine.

# Medicine type and structured dosage
CONF_MED_TYPE = "med_type"                       # "pill" | "drops" | "injection"
CONF_MED_UNIT_COUNT = "unit_count"               # number of pills/drops/injections per dose
CONF_MED_UNIT_STRENGTH_MG = "unit_strength_mg"   # legacy mg-only strength, REMOVE AT v1.0.0
CONF_MED_TOTAL_DOSE_MG = "total_dose_mg"         # legacy sensor attr name, kept as derived

# v0.2.13: variant-aware strength. The user picks a variant from
# medicines_se.json (or types free-text strength + form when off
# catalog). Strength is stored as the verbatim catalog string
# ("5 mg", "100 E/ml", "87 mikrogram/5 mikrogram/9 mikrogram") —
# never reparsed into a number+unit, so combo / IU / concentration
# variants all round-trip cleanly. ``total_dose_mg`` is computed on
# the fly when ``variant_strength`` matches ``<number> mg``; None
# otherwise.
CONF_MED_VARIANT_STRENGTH = "variant_strength"   # e.g. "5 mg"
CONF_MED_VARIANT_FORM = "variant_form"           # e.g. "Filmdragerad tablett"
CONF_MED_VARIANT_NPL_ID = "variant_npl_id"       # pointer back to the catalog variant

MED_TYPE_PILL = "pill"
MED_TYPE_DROPS = "drops"
MED_TYPE_INJECTION = "injection"
ALL_MED_TYPES = (MED_TYPE_PILL, MED_TYPE_DROPS, MED_TYPE_INJECTION)

# Singular/plural unit names used when auto-formatting the dose string
MED_TYPE_UNIT_LABELS = {
    MED_TYPE_PILL: ("pill", "pills"),
    MED_TYPE_DROPS: ("drop", "drops"),
    MED_TYPE_INJECTION: ("injection", "injections"),
}

CONF_MED_TIMES = "times"
CONF_MED_DAYS = "days"                      # weekday ints 0-6, used by weekly
CONF_MED_DAYS_OF_MONTH = "days_of_month"    # ints 1-31, used by monthly
CONF_MED_INTERVAL_DAYS = "interval_days"    # int >= 2, used by interval
CONF_MED_FREQUENCY = "frequency"            # "daily" | "weekly" | "monthly"
CONF_MED_REMIND_WINDOW = "remind_window_minutes"

# Per-medicine list of prescriptions. A prescription is one
# (person × dose × schedule) triple; a medicine can have many.
CONF_MED_PRESCRIPTIONS = "prescriptions"

# Stable per-prescription id. Same string value as CONF_MED_ID since the
# two live in different dict scopes (medicine dict vs prescription dict).
# Generated as uuid4 hex when a prescription is created; used as the
# merge key when the panel sends back an updated prescriptions list.
CONF_PRESCRIPTION_ID = "id"

# Frequency values — LEGACY pre-v0.2.0 schema. Kept only for the
# migration helper (`migrate_v1_to_v2_schedule` in schedule.py) which
# converts existing prescriptions to the new RRULE-based shape, AND
# as the form-input vocabulary the panel sends to the validator
# (panel UI still uses these strings; validator translates to the
# canonical `schedule_type` + `rrule` shape on save). Both layers
# disappear at v1.0.0 when the form switches to schedule_type
# directly.
# REMOVE AT v1.0.0 along with the migration helper.
FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_MONTHLY = "monthly"
FREQ_INTERVAL = "interval"
ALL_FREQUENCIES = (FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY, FREQ_INTERVAL)

# v0.2.0 schedule schema — RRULE is the source of truth at rest;
# schedule_type tells the panel UI which mode to render. RRULE handles
# every calendar-based scenario (daily, weekly, monthly, every-N-days,
# course-with-end-date, plus arbitrary RFC 5545 patterns); cycle mode
# overlays a stateful on/off pattern that RRULE can't express natively.
CONF_MED_RRULE = "rrule"
CONF_MED_SCHEDULE_TYPE = "schedule_type"
CONF_MED_STARTS_ON = "starts_on"  # ISO date "YYYY-MM-DD" or None — anchor for interval mode
CONF_MED_ENDS_ON = "ends_on"  # ISO date "YYYY-MM-DD" or None — course end
CONF_MED_CYCLE_ANCHOR = "cycle_anchor"        # ISO date or None
CONF_MED_CYCLE_ON_DAYS = "cycle_on_days"      # int or None
CONF_MED_CYCLE_OFF_DAYS = "cycle_off_days"    # int or None
# times_per_weekday: list of 7 lists (Mon=0..Sun=6), each holding HH:MM
# strings. None means "simple mode" — fall through to the flat `times`
# field, which applies every firing day. Empty inner list means "no
# doses on that weekday even if the frequency would fire."
CONF_MED_TIMES_PER_WEEKDAY = "times_per_weekday"

SCHEDULE_TYPE_DAILY = "daily"            # FREQ=DAILY
SCHEDULE_TYPE_WEEKLY = "weekly"          # FREQ=WEEKLY;BYDAY=...
SCHEDULE_TYPE_MONTHLY = "monthly"        # FREQ=MONTHLY;BYMONTHDAY=...
SCHEDULE_TYPE_INTERVAL = "interval"      # FREQ=DAILY;INTERVAL=N (with DTSTART anchor)
SCHEDULE_TYPE_CYCLE = "cycle"            # FREQ=DAILY tick + cycle_on/off overlay
SCHEDULE_TYPE_CUSTOM = "custom"          # raw user-provided RRULE
ALL_SCHEDULE_TYPES = (
    SCHEDULE_TYPE_DAILY,
    SCHEDULE_TYPE_WEEKLY,
    SCHEDULE_TYPE_MONTHLY,
    SCHEDULE_TYPE_INTERVAL,
    SCHEDULE_TYPE_CYCLE,
    SCHEDULE_TYPE_CUSTOM,
)

# Weekday encoding bridge: panel/Python uses 0–6 (Mon–Sun, ISO weekday
# minus one). RRULE BYDAY uses two-letter codes. These maps keep the
# conversion in one place so the validator and migration helper agree.
WEEKDAY_TO_RRULE = {0: "MO", 1: "TU", 2: "WE", 3: "TH", 4: "FR", 5: "SA", 6: "SU"}
RRULE_TO_WEEKDAY = {v: k for k, v in WEEKDAY_TO_RRULE.items()}

DEFAULT_REMIND_WINDOW = 60
DEFAULT_SCAN_INTERVAL = timedelta(minutes=1)
SOURCE_LOOKUP_TTL = timedelta(days=7)

# ---- storage --------------------------------------------------------
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.history"

# ---- bus events -----------------------------------------------------
EVENT_DOSE_DUE = f"{DOMAIN}_dose_due"
EVENT_DOSE_MISSED = f"{DOMAIN}_dose_missed"
EVENT_DOSE_TAKEN = f"{DOMAIN}_dose_taken"
EVENT_DOSE_SKIPPED = f"{DOMAIN}_dose_skipped"
EVENT_DOSE_SNOOZED = f"{DOMAIN}_dose_snoozed"
EVENT_DOSE_UNMARKED = f"{DOMAIN}_dose_unmarked"

# ---- services -------------------------------------------------------
SERVICE_MARK_TAKEN = "mark_taken"
SERVICE_SKIP = "skip"
SERVICE_SNOOZE = "snooze"
SERVICE_UNMARK_TAKEN = "unmark_taken"
SERVICE_REFRESH_MEDICINES_DATABASE = "refresh_medicines_database"
SERVICE_BACKFILL_FROM_CATALOG = "backfill_from_catalog"

# ---- medicines database (added v0.2.15) -----------------------------
# The bundled Swedish medicine list (medicines_se.json) shipped with
# the integration powers the autocomplete dropdown in the Add Medicine
# form. CONF_MEDICINES_DB_URL lets users point the refresh action at
# a fork of the master list — useful if they're maintaining their own
# additions and don't want to wait for upstream PRs to merge.
CONF_MEDICINES_DB_URL = "medicines_db_url"
CONF_MEDICINES_DB_REFRESH_NOW = "refresh_medicines_now"  # transient toggle in Reconfigure

# ---- sensor states --------------------------------------------------
STATE_DUE = "due"
STATE_UPCOMING = "upcoming"
STATE_TAKEN = "taken"
STATE_MISSED = "missed"
STATE_SKIPPED = "skipped"
STATE_SNOOZED = "snoozed"

# ---------------------------------------------------------------------------
# Sidebar panel visibility (added in v0.2.3)
#
# Stored in entry.data[CONF_PANEL_VISIBILITY]. Defaults to "everyone" for
# entries that pre-date this feature, so existing v0.2.1/v0.2.2 installs
# keep the same behavior they had before.
# ---------------------------------------------------------------------------
CONF_PANEL_VISIBILITY = "panel_visibility"
PANEL_VIS_EVERYONE = "everyone"   # registered, require_admin=False
PANEL_VIS_ADMINS = "admins"       # registered, require_admin=True
PANEL_VIS_HIDDEN = "hidden"       # not registered at all
DEFAULT_PANEL_VISIBILITY = PANEL_VIS_EVERYONE
PANEL_VISIBILITY_OPTIONS = [
    PANEL_VIS_EVERYONE,
    PANEL_VIS_ADMINS,
    PANEL_VIS_HIDDEN,
]

# ---------------------------------------------------------------------------
# Manager allowlist (added in v0.2.18)
#
# Stored in entry.data[CONF_MANAGERS] as a list of HA user_ids.
# Mutating WS commands (create / update / delete medicine) check membership.
#
# Empty list = backward-compat: every admin can manage (matches the old
# @websocket_api.require_admin behavior). Non-empty list = only owner +
# listed users can manage. Owner is always implicitly a manager regardless
# of the list contents (HA's permission system bypasses every check for
# owner anyway, so an explicit user.is_owner check is the source of truth).
# ---------------------------------------------------------------------------
CONF_MANAGERS = "managers"

# ---------------------------------------------------------------------------
# Per-medicine visibility (added in v0.2.19)
#
# Stored on each medicine subentry's data dict. Controls who can see the
# medicine in the panel and who can mutate it via the WS commands.
# Sensors stay global — HA's entity-registry permissions are admin/non-admin
# only, so a non-allowed user can still read sensor state via Developer
# Tools. Tier 2 stops at panel-level visibility; sensor gating is Tier 3.
#
# Modes:
#   * everyone        — default. Backward-compat for pre-v0.2.19 entries
#                       that don't carry the field at all.
#   * linked_person   — only HA users whose person entity is the
#                       person_id of any prescription on this medicine,
#                       plus owner and managers.
#   * admins_only     — only owner, managers, and admins.
#   * specific_users  — explicit allowlist in CONF_MED_VISIBILITY_USERS.
#                       Owner and managers always pass; stored list is
#                       additional users only (owner stripped on save).
# ---------------------------------------------------------------------------
CONF_MED_VISIBILITY = "visibility"
CONF_MED_VISIBILITY_USERS = "visibility_users"
VIS_EVERYONE = "everyone"
VIS_LINKED_PERSON = "linked_person"
VIS_ADMINS_ONLY = "admins_only"
VIS_SPECIFIC_USERS = "specific_users"
DEFAULT_MED_VISIBILITY = VIS_EVERYONE
MED_VISIBILITY_OPTIONS = [
    VIS_EVERYONE,
    VIS_LINKED_PERSON,
    VIS_ADMINS_ONLY,
    VIS_SPECIFIC_USERS,
]
