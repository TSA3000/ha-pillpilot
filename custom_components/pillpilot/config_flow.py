"""Config flow for PillPilot.

The integration ships two flow handlers:

  * ``PillPilotConfigFlow`` (subclass of ``ConfigFlow``) — runs once
    when the user first adds the integration. As of v0.2.14 the only
    parent-level setting is the sidebar panel visibility (the data
    sources VARA / FASS-API / RMS were removed; future v0.2.16 FASS
    web-link enrichment is configured per-medicine). Users can revisit
    panel visibility later via Reconfigure without removing the entry.

  * ``MedicineSubentryFlow`` (subclass of ``ConfigSubentryFlow``) —
    runs every time the user clicks the "Add medicine" button on the
    integration card. Each medicine becomes its own config subentry,
    which means it appears as its own line item with edit/remove
    controls right on the integration card.

The classmethod ``PillPilotConfigFlow.async_get_supported_subentry_types``
is what tells Home Assistant that this integration supports
"add medicine" subentries — the UI button is generated automatically.
"""
from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_MED_ATC_CODE,
    CONF_MED_CYCLE_ANCHOR,
    CONF_MED_CYCLE_OFF_DAYS,
    CONF_MED_CYCLE_ON_DAYS,
    CONF_MED_DAYS,
    CONF_MED_DAYS_OF_MONTH,
    CONF_MED_DOSE,
    CONF_MED_ENDS_ON,
    CONF_MED_FREQUENCY,
    CONF_MED_INTERVAL_DAYS,
    CONF_MED_NAME,
    CONF_MED_NOTES,
    CONF_MED_NPL_ID,
    CONF_MED_PERSON,
    CONF_MED_PRESCRIPTIONS,
    CONF_PRESCRIPTION_ID,
    CONF_MED_REMIND_WINDOW,
    CONF_MED_RRULE,
    CONF_MED_SCHEDULE_TYPE,
    CONF_MED_TIMES,
    CONF_MED_TIMES_PER_WEEKDAY,
    CONF_MED_TOTAL_DOSE_MG,
    CONF_MED_TYPE,
    CONF_MED_UNIT_COUNT,
    CONF_MED_UNIT_STRENGTH_MG,
    CONF_MED_VARUNUMMER,
    CONF_MEDICINES_DB_REFRESH_NOW,
    CONF_MEDICINES_DB_URL,
    CONF_PANEL_VISIBILITY,
    DEFAULT_PANEL_VISIBILITY,
    DEFAULT_REMIND_WINDOW,
    DOMAIN,
    ALL_FREQUENCIES,
    FREQ_DAILY,
    FREQ_INTERVAL,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    MED_TYPE_DROPS,
    MED_TYPE_INJECTION,
    MED_TYPE_PILL,
    PANEL_VISIBILITY_OPTIONS,
    SCHEDULE_TYPE_DAILY,
    SCHEDULE_TYPE_INTERVAL,
    SCHEDULE_TYPE_MONTHLY,
    SCHEDULE_TYPE_WEEKLY,
)
from .dose import Dose
from .medicines import (
    DEFAULT_MEDICINES_DB_URL,
    MedicineDatabase,
    build_dropdown_options,
    lookup_by_name,
)
from .schedule import rrule_to_friendly, schedule_to_rrule


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------
#
# Pre-v0.2.21 the form validation lived only inside the config flow's
# ``_async_form`` method, called from the HA Settings reconfigure UI. The
# in-panel edit modal added in v0.2.21 needs the SAME validation logic
# from a different code path (a websocket command), so we factor the
# core pure-data transformation out into this module-level function.
# Both call sites end up with identical (medicine_dict, errors) shape.

# HH:MM with optional single-digit hour. Hours 0-23, minutes 0-59. We
# normalize "9:00" → "09:00" so downstream code (cron equivalent,
# display, sorting) can rely on a single canonical format.
_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _normalize_times(times_iter) -> tuple[list[str], str | None]:
    """Validate and zero-pad a sequence of HH:MM strings.

    Returns (normalized_list, None) on success, ([], error_key) on the
    first malformed entry. Empty / whitespace-only entries are skipped
    silently — that matches the existing comma-string parser's
    behavior. Caller decides whether an empty list is itself an error.
    """
    out: list[str] = []
    for t in times_iter:
        s = str(t).strip()
        if not s:
            continue
        if not _HHMM_RE.match(s):
            return [], "times_invalid"
        h, m = s.split(":")
        out.append(f"{int(h):02d}:{m}")
    return out, None


def _strip_or_none(value) -> str | None:
    """Trim whitespace; return None if the result is empty.

    Used for optional drug-identity fields (atc_code, npl_id,
    varunummer) so leading/trailing whitespace doesn't cause
    "Levaxin " and "Levaxin" to be treated as different drugs.
    """
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_interval_days(raw) -> tuple[int | None, str | None]:
    """Parse and range-check an interval_days value.

    Returns (n, None) on success, (None, error_key) on failure.
    Empty/None is rejected because interval mode requires an
    explicit interval — the form-level dispatch only calls this
    helper when ``frequency == "interval"``. Range 2..365 keeps
    sensible bounds (2 = every other day, 365 = annual).
    """
    if raw is None or raw == "":
        return None, "interval_days_required"
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None, "interval_days_invalid"
    if n < 2 or n > 365:
        return None, "interval_days_range"
    return n, None


def _parse_times_per_weekday(raw) -> tuple[list[list[str]] | None, str | None]:
    """Parse and validate the per-weekday times override.

    Input shape (from form): a list of 7 entries, each a list or
    comma-separated string of HH:MM times. Mon=0..Sun=6.
    Output shape (for storage): a list of 7 lists of zero-padded
    "HH:MM" strings. None means "no override — fall back to flat
    times" (legacy / simple mode).

    Empty inner lists are allowed — they mean "no doses on that
    weekday" (skip-day semantics). Bad formats and wrong lengths
    surface error keys for the UI to render.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, "times_per_weekday_invalid"
    if len(raw) != 7:
        return None, "times_per_weekday_length"

    out: list[list[str]] = []
    for entry in raw:
        if isinstance(entry, str):
            iter_strs = entry.split(",")
        elif isinstance(entry, list):
            iter_strs = entry
        elif entry is None:
            iter_strs = []
        else:
            return None, "times_per_weekday_invalid"
        normalized, err = _normalize_times(iter_strs)
        if err is not None:
            # _normalize_times returns "times_invalid" on bad HH:MM.
            # Surface a per-weekday-specific key so the UI can pin
            # the error to the right row.
            return None, "times_per_weekday_time_invalid"
        out.append(normalized)
    return out, None


def _parse_ends_on(raw) -> tuple[date | None, str | None]:
    """Parse an optional ISO-format end date.

    Universal across all frequency modes — empty/None means "no end
    date, run forever". Returns (None, None) for the empty case so
    the caller can pass the date through to ``schedule_to_rrule``
    unconditionally (it accepts ``ends_on=None`` as "no UNTIL").
    """
    if raw is None or raw == "":
        return None, None
    try:
        return date.fromisoformat(str(raw)), None
    except (TypeError, ValueError):
        return None, "ends_on_invalid"


def validate_medicine_input(
    hass,
    user_input: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Validate a raw medicine form submission.

    Takes the same ``user_input`` shape produced by HA's voluptuous
    schema (the dict that comes out of ``async_show_form`` submissions)
    and returns either:

      * ``(medicine_dict, {})`` — fully validated, ready to persist as
        the subentry's ``data`` payload.
      * ``(None, errors)`` — validation failed; ``errors`` maps field
        names to translation keys consumed by the form UI's
        ``errors=...`` rendering.

    Mirrors what ``_async_form`` did in v0.2.20 — extracted here so the
    in-panel edit websocket command can reuse it without duplicating
    the parsing/normalization code.
    """
    errors: dict[str, str] = {}

    person_id = user_input.get(CONF_MED_PERSON) or None

    # Parse days_of_month
    freq = user_input.get(CONF_MED_FREQUENCY) or FREQ_WEEKLY
    if freq not in ALL_FREQUENCIES:
        errors[CONF_MED_FREQUENCY] = "frequency_invalid"
    doms_raw = (user_input.get(CONF_MED_DAYS_OF_MONTH) or "").strip()
    doms: list[int] = []
    if doms_raw:
        try:
            doms = sorted(
                {int(p.strip()) for p in doms_raw.split(",") if p.strip()}
            )
            if any(d < 1 or d > 31 for d in doms):
                errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_range"
        except ValueError:
            errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_invalid"
    if (
        freq == FREQ_MONTHLY
        and not doms
        and CONF_MED_DAYS_OF_MONTH not in errors
    ):
        errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_required"

    if errors:
        return None, errors

    # Dose is a derived value — type × count × strength. Always
    # computed here, never read from user input. v0.2.6 removed the
    # editable dose text field because HA forms aren't reactive: the
    # field could appear stale on Reconfigure (count changed but dose
    # hadn't been recomputed yet). Computing here keeps it in sync.
    try:
        dose = Dose(
            med_type=user_input[CONF_MED_TYPE],
            count=float(user_input[CONF_MED_UNIT_COUNT]),
            strength_mg=float(user_input[CONF_MED_UNIT_STRENGTH_MG]),
        )
    except (KeyError, TypeError, ValueError):
        return None, {CONF_MED_UNIT_COUNT: "invalid_number"}
    dose_text = dose.formatted()

    # autocomplete auto-fill. If the user picked a name from
    # the dropdown (vs typed a custom value), look it up in the
    # medicines DB and pre-populate ATC + notes if those fields are
    # empty. Free-text typed values that aren't in the list just pass
    # through unchanged.
    med_name = user_input[CONF_MED_NAME]
    med_db: MedicineDatabase | None = (
        hass.data.get(DOMAIN, {}).get("medicine_db") if hass else None
    )
    lookup = (
        lookup_by_name(med_db.medicines, med_name)
        if med_db is not None else None
    )
    user_atc = (user_input.get(CONF_MED_ATC_CODE) or "").strip()
    catalog_atc = (lookup or {}).get("atc_code", "")
    atc_final = user_atc or catalog_atc or None
    user_notes = user_input.get(CONF_MED_NOTES, "")
    if not user_notes and lookup and lookup.get("active_substance"):
        notes_final = f"Aktiv substans: {lookup['active_substance']}"
    else:
        notes_final = user_notes
    notes_final = notes_final.strip() if notes_final else notes_final

    # build a v2-shaped medicine — drug identity at top level,
    # the form's single set of dose+schedule fields wrapped in a
    # one-element prescriptions list. Caller (the WS command and the
    # config flow finalize step) merges this into the existing subentry
    # data, preserving any additional prescriptions that may exist on
    # the medicine. The flow form is single-prescription in v0.2.24;
    # v0.2.25 adds a multi-step flow that can produce multi-element
    # prescriptions lists.
    # Build the prescription dict. The id is generated fresh — caller's
    # merge logic decides whether to overlay this onto an existing
    # prescription (preserving its id) or treat it as a new one.
    # Parse days — the SelectSelector pre-validates against WEEKDAYS so
    # in normal HA Settings usage the values are always valid integer
    # strings. But the validator runs against arbitrary dicts (also called
    # from the WS create path's reconfigure handler), so harden against
    # non-numeric / None input the same way validate_medicine_input_multi
    # does. Surfaces days_invalid on failure instead of crashing.
    try:
        days_parsed = [int(d) for d in user_input.get(CONF_MED_DAYS, [])]
    except (TypeError, ValueError):
        return None, {CONF_MED_DAYS: "days_invalid"}
    # Range-check: weekdays must be 0–6 (Monday=0 through Sunday=6).
    if any(d < 0 or d > 6 for d in days_parsed):
        return None, {CONF_MED_DAYS: "days_range"}
    # Weekly mode must specify at least one weekday. Pre-v0.2.0 this
    # was silently accepted and stored as weekly with empty days; the
    # Schedule class then fell back to all-7-days at read time, which
    # surprised users (it looked weekly in the form but fired daily).
    # v0.2.0+ requires explicit days for weekly so the canonical RRULE
    # is unambiguous.
    if freq == FREQ_WEEKLY and not days_parsed:
        return None, {CONF_MED_DAYS: "days_required"}

    # Parse interval_days — only used when frequency=interval. Bounded
    # 2..365 in _parse_interval_days. Empty or missing triggers
    # "interval_days_required" only when the form picked interval mode
    # (other modes don't read this field at all).
    interval_days_parsed: int | None = None
    if freq == FREQ_INTERVAL:
        interval_days_parsed, ival_err = _parse_interval_days(
            user_input.get(CONF_MED_INTERVAL_DAYS)
        )
        if ival_err is not None:
            return None, {CONF_MED_INTERVAL_DAYS: ival_err}

    # Parse optional end date — universal, applies to any frequency.
    # Empty/None is the common case (no end date). ISO format expected
    # ("YYYY-MM-DD"), which is what HA's date selectors emit.
    ends_on_parsed, ends_err = _parse_ends_on(user_input.get(CONF_MED_ENDS_ON))
    if ends_err is not None:
        return None, {CONF_MED_ENDS_ON: ends_err}

    # Parse optional per-weekday times override — universal across
    # every frequency mode. None = flat ``times`` applies every
    # firing day (simple mode). Set = list of 7 lists of HH:MM
    # strings indexed Mon=0..Sun=6.
    #
    # Two input shapes converge here:
    #   * Panel form sends ``CONF_MED_TIMES_PER_WEEKDAY`` directly as
    #     a list of 7 entries (or omits it for simple mode).
    #   * HA Settings form sends 7 separate string fields (one per
    #     weekday). We consolidate them into the list shape if the
    #     canonical key isn't present and any per-weekday field is.
    tpw_raw = user_input.get(CONF_MED_TIMES_PER_WEEKDAY)
    if tpw_raw is None and any(user_input.get(k) for k in WEEKDAY_FORM_KEYS):
        tpw_raw = [user_input.get(k, "") for k in WEEKDAY_FORM_KEYS]
    tpw_parsed, tpw_err = _parse_times_per_weekday(tpw_raw)
    if tpw_err is not None:
        return None, {CONF_MED_TIMES_PER_WEEKDAY: tpw_err}

    # Parse times — accept comma-string form, validate HH:MM format,
    # zero-pad single-digit hours so downstream code sees canonical form.
    times_normalized, times_err = _normalize_times(
        user_input[CONF_MED_TIMES].split(",")
    )
    if times_err is not None:
        return None, {CONF_MED_TIMES: times_err}

    # v0.2.0+: storage is RRULE-based. The form sends friendly
    # frequency/days/days_of_month/interval_days, validated above; we
    # translate to canonical RRULE here. Legacy keys are dropped from
    # the output dict — the rest of the codebase only handles new shape.
    if freq == FREQ_WEEKLY:
        rrule_str = schedule_to_rrule(
            SCHEDULE_TYPE_WEEKLY, weekdays=days_parsed, ends_on=ends_on_parsed
        )
        schedule_type = SCHEDULE_TYPE_WEEKLY
    elif freq == FREQ_MONTHLY:
        rrule_str = schedule_to_rrule(
            SCHEDULE_TYPE_MONTHLY, days_of_month=doms, ends_on=ends_on_parsed
        )
        schedule_type = SCHEDULE_TYPE_MONTHLY
    elif freq == FREQ_INTERVAL:
        rrule_str = schedule_to_rrule(
            SCHEDULE_TYPE_INTERVAL,
            interval_days=interval_days_parsed,
            ends_on=ends_on_parsed,
        )
        schedule_type = SCHEDULE_TYPE_INTERVAL
    else:
        rrule_str = schedule_to_rrule(SCHEDULE_TYPE_DAILY, ends_on=ends_on_parsed)
        schedule_type = SCHEDULE_TYPE_DAILY

    prescription = {
        CONF_PRESCRIPTION_ID: uuid.uuid4().hex,
        CONF_MED_PERSON: person_id,
        CONF_MED_UNIT_COUNT: dose.count,
        CONF_MED_UNIT_STRENGTH_MG: dose.strength_mg,
        CONF_MED_TOTAL_DOSE_MG: dose.total_mg,
        CONF_MED_DOSE: dose_text,
        CONF_MED_RRULE: rrule_str,
        CONF_MED_SCHEDULE_TYPE: schedule_type,
        CONF_MED_TIMES: times_normalized,
        CONF_MED_REMIND_WINDOW: int(user_input[CONF_MED_REMIND_WINDOW]),
        # ends_on stored as ISO string; UNTIL is also encoded in
        # rrule so the engine sees it directly. Storing the string
        # here keeps the friendly value available for the panel
        # without re-parsing UNTIL on every read.
        CONF_MED_ENDS_ON: ends_on_parsed.isoformat() if ends_on_parsed else None,
        CONF_MED_TIMES_PER_WEEKDAY: tpw_parsed,
        # Cycle fields stay None until beta4 wires the cycle UI.
        CONF_MED_CYCLE_ANCHOR: None,
        CONF_MED_CYCLE_ON_DAYS: None,
        CONF_MED_CYCLE_OFF_DAYS: None,
    }
    med = {
        # drug identity (shared across prescriptions)
        CONF_MED_NAME: med_name,
        CONF_MED_TYPE: dose.med_type,
        CONF_MED_NOTES: notes_final,
        CONF_MED_NPL_ID: _strip_or_none(user_input.get(CONF_MED_NPL_ID)),
        CONF_MED_VARUNUMMER: _strip_or_none(user_input.get(CONF_MED_VARUNUMMER)),
        CONF_MED_ATC_CODE: atc_final,
        # prescriptions
        CONF_MED_PRESCRIPTIONS: [prescription],
    }
    return med, {}


def merge_v2_form_into_existing(
    form_med: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    """Splice a single-prescription form output into existing v2 data.

    The HA Settings reconfigure form is single-prescription. When the user
    edits a multi-prescription medicine through it, naive replacement
    (``data=form_med``) would erase prescriptions[1:].

    This helper splices the form's prescriptions[0] in as the medicine's
    first prescription and carries forward any remaining prescriptions
    from the existing record. The existing prescription[0]'s ``id`` is
    preserved (the form generates a fresh id but we keep the stored one
    so dose history stays linked). Drug-identity fields come from the
    form. Anything in ``existing`` that the form doesn't speak to (like
    medicine-level ``id``) is preserved.
    """
    existing_prescriptions = existing.get(CONF_MED_PRESCRIPTIONS) or []
    form_prescriptions = form_med.get(CONF_MED_PRESCRIPTIONS) or []

    if form_prescriptions and existing_prescriptions:
        # Editing existing — preserve the stored prescription id so dose
        # history stays linked. Form fields override everything else.
        merged_first = {
            **form_prescriptions[0],
            CONF_PRESCRIPTION_ID: existing_prescriptions[0].get(
                CONF_PRESCRIPTION_ID,
                form_prescriptions[0].get(CONF_PRESCRIPTION_ID),
            ),
        }
        merged_prescriptions = [merged_first, *existing_prescriptions[1:]]
    elif form_prescriptions:
        # Creating new (no existing prescriptions yet) — use form's id.
        merged_prescriptions = [form_prescriptions[0]]
    else:
        # Form produced no prescription — defensive, shouldn't happen.
        merged_prescriptions = existing_prescriptions

    drug_identity_overrides = {
        k: v for k, v in form_med.items() if k != CONF_MED_PRESCRIPTIONS
    }
    return {
        **existing,
        **drug_identity_overrides,
        CONF_MED_PRESCRIPTIONS: merged_prescriptions,
    }


def merge_v2_prescriptions_into_existing(
    drug_identity: dict[str, Any],
    form_prescriptions: list[dict[str, Any]],
    existing: dict[str, Any],
) -> dict[str, Any]:
    """Merge a multi-prescription panel form output into existing v2 data.

    Used by the panel-side Edit Medicine modal which sends back the full
    list of prescriptions. Match-by-id semantics:

    * form prescription with id present in existing → update (overwrite
      with form data, keep the id)
    * form prescription with id NOT in existing (or no id at all) → add
      as a new prescription, generating a fresh id if missing
    * existing prescription whose id is NOT in form → DELETE

    ``drug_identity`` is the top-level medicine fields (name, type,
    notes, atc_code, npl_id, varunummer) from the form. ``form_prescriptions``
    is the list of prescription dicts. ``existing`` is the stored
    medicine subentry data dict.
    """
    # Every stored prescription has CONF_PRESCRIPTION_ID under the
    # canonical 0.1.0+ schema (stamped by validate_medicine_input_multi
    # on save). If somehow one doesn't, we'd rather KeyError loud than
    # silently drop it from the lookup map.
    existing_by_id = {
        p[CONF_PRESCRIPTION_ID]: p
        for p in (existing.get(CONF_MED_PRESCRIPTIONS) or [])
    }
    merged_prescriptions: list[dict[str, Any]] = []

    for form_p in form_prescriptions:
        pid = form_p.get(CONF_PRESCRIPTION_ID)
        if pid and pid in existing_by_id:
            # Update path: keep the id, overwrite all other fields with
            # the form's values. Spread order: existing first (carries id),
            # form last (overrides). Then re-affirm the id explicitly.
            merged = {
                **existing_by_id[pid],
                **form_p,
                CONF_PRESCRIPTION_ID: pid,
            }
        else:
            # Add path: form sent a prescription not in existing. Stamp a
            # fresh id if the form didn't provide one.
            new_pid = pid or uuid.uuid4().hex
            merged = {
                **form_p,
                CONF_PRESCRIPTION_ID: new_pid,
            }
        merged_prescriptions.append(merged)

    # Anything in existing whose id wasn't in the form is implicitly
    # deleted by virtue of not being added to merged_prescriptions.

    return {
        **existing,
        **drug_identity,
        CONF_MED_PRESCRIPTIONS: merged_prescriptions,
    }


def validate_medicine_input_multi(
    hass,
    drug: dict[str, Any],
    prescriptions: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Validate a multi-prescription panel form submission.

    Returns either:

      * ``(medicine_dict, {})`` — fully validated, ready to persist as a
        new subentry's ``data`` payload (caller stamps the medicine_id).
      * ``(None, errors)`` — validation failed; ``errors`` is the nested
        shape:

            {
              "drug": {field: errKey, ...},
              "prescriptions": [{field: errKey, ...}, ...],   # one entry per prescription
              "base": errKey | "",
            }

        ``errors["prescriptions"][i]`` is the error dict for prescription
        index ``i`` (empty if that prescription is valid). The list is
        always the same length as the input prescriptions list so the
        panel can match errors back to UI rows by index.

    Drug identity is shared across prescriptions. The auto-fill from the
    medicine database (ATC code, active substance → notes) follows the
    same logic as ``validate_medicine_input``.

    Each prescription gets a stable id stamped if it doesn't already
    have one (the panel will keep ids on existing prescriptions and
    omit them on new ones it's just added in the modal).
    """
    drug_errors: dict[str, str] = {}
    prescription_errors: list[dict[str, str]] = []
    base_error = ""

    # ---- drug-identity validation ----
    name = (drug.get(CONF_MED_NAME) or "").strip()
    if not name:
        drug_errors[CONF_MED_NAME] = "name_required"

    med_type = drug.get(CONF_MED_TYPE) or MED_TYPE_PILL
    if med_type not in (MED_TYPE_PILL, MED_TYPE_DROPS, MED_TYPE_INJECTION):
        drug_errors[CONF_MED_TYPE] = "invalid_type"

    # ---- at-least-one-prescription rule ----
    if not prescriptions:
        base_error = "at_least_one_prescription"

    # ---- per-prescription validation ----
    # Pre-pass: detect duplicate prescription ids. If the form sends two
    # rows with the same id, the merge would silently update one and
    # then update it again — second one wins, first one's data lost
    # without warning. Flag every occurrence so the user sees both
    # offending rows in the modal.
    #
    # Empty / missing ids are not duplicates of each other — those rows
    # are new prescriptions that will each be assigned a fresh uuid by
    # the merge, so multiple null ids are fine.
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for p in prescriptions:
        pid = p.get(CONF_PRESCRIPTION_ID)
        if pid:
            if pid in seen_ids:
                duplicate_ids.add(pid)
            seen_ids.add(pid)

    validated_prescriptions: list[dict[str, Any]] = []
    for p in prescriptions:
        p_errors: dict[str, str] = {}

        # Flag if this row's id collides with another row's id. Other
        # field validation continues so the user sees all problems at
        # once rather than discovering the duplicate, fixing it, then
        # discovering more errors on resave.
        pid = p.get(CONF_PRESCRIPTION_ID)
        if pid and pid in duplicate_ids:
            p_errors[CONF_PRESCRIPTION_ID] = "duplicate_prescription_id"

        # Parse days_of_month — accept either comma-string or list.
        freq = p.get(CONF_MED_FREQUENCY) or FREQ_DAILY
        if freq not in ALL_FREQUENCIES:
            p_errors[CONF_MED_FREQUENCY] = "frequency_invalid"
        doms_raw = p.get(CONF_MED_DAYS_OF_MONTH) or []
        doms: list[int] = []
        if isinstance(doms_raw, str):
            doms_str = doms_raw.strip()
            if doms_str:
                try:
                    doms = sorted({
                        int(x.strip()) for x in doms_str.split(",") if x.strip()
                    })
                    if any(d < 1 or d > 31 for d in doms):
                        p_errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_range"
                except ValueError:
                    p_errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_invalid"
        else:
            # List branch (panel sends an array). Same crash surface as
            # the string branch above — non-numeric entries explode.
            try:
                doms = sorted({int(d) for d in doms_raw})
                if any(d < 1 or d > 31 for d in doms):
                    p_errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_range"
            except (TypeError, ValueError):
                p_errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_invalid"

        if (
            freq == FREQ_MONTHLY
            and not doms
            and CONF_MED_DAYS_OF_MONTH not in p_errors
        ):
            p_errors[CONF_MED_DAYS_OF_MONTH] = "days_of_month_required"

        # Compute Dose. Catches missing or non-numeric count/strength.
        dose: Dose | None = None
        if not p_errors:
            try:
                dose = Dose(
                    med_type=med_type,
                    count=float(p.get(CONF_MED_UNIT_COUNT, 0)),
                    strength_mg=float(p.get(CONF_MED_UNIT_STRENGTH_MG, 0)),
                )
            except (KeyError, TypeError, ValueError):
                p_errors[CONF_MED_UNIT_COUNT] = "invalid_number"

        if p_errors or dose is None:
            prescription_errors.append(p_errors)
            continue

        # Parse times — accept comma-string or list. Validate HH:MM
        # format and zero-pad single-digit hours.
        times_raw = p.get(CONF_MED_TIMES) or []
        if isinstance(times_raw, str):
            times_iter = times_raw.split(",")
        else:
            times_iter = times_raw
        times, times_err = _normalize_times(times_iter)
        if times_err is not None:
            p_errors[CONF_MED_TIMES] = times_err
            prescription_errors.append(p_errors)
            continue

        # Parse days — accept list of ints or list of strings. Non-numeric
        # entries (e.g. WS client sends ["Mon"] instead of [1]) would
        # crash int() — surface as days_invalid instead. Range-check 0-6
        # so out-of-range values like [99] don't sneak through.
        days_raw = p.get(CONF_MED_DAYS) or []
        try:
            days = [int(d) for d in days_raw]
        except (TypeError, ValueError):
            p_errors[CONF_MED_DAYS] = "days_invalid"
            prescription_errors.append(p_errors)
            continue
        if any(d < 0 or d > 6 for d in days):
            p_errors[CONF_MED_DAYS] = "days_range"
            prescription_errors.append(p_errors)
            continue
        # Weekly without explicit days is rejected — see single
        # validator for rationale.
        if freq == FREQ_WEEKLY and not days:
            p_errors[CONF_MED_DAYS] = "days_required"
            prescription_errors.append(p_errors)
            continue

        # Parse interval_days — only used when frequency=interval.
        interval_days_parsed: int | None = None
        if freq == FREQ_INTERVAL:
            interval_days_parsed, ival_err = _parse_interval_days(
                p.get(CONF_MED_INTERVAL_DAYS)
            )
            if ival_err is not None:
                p_errors[CONF_MED_INTERVAL_DAYS] = ival_err
                prescription_errors.append(p_errors)
                continue

        # Parse optional end date — universal across all frequencies.
        ends_on_parsed, ends_err = _parse_ends_on(p.get(CONF_MED_ENDS_ON))
        if ends_err is not None:
            p_errors[CONF_MED_ENDS_ON] = ends_err
            prescription_errors.append(p_errors)
            continue

        # Parse optional per-weekday times override — universal.
        # See single validator for the two-input-shape rationale.
        tpw_raw = p.get(CONF_MED_TIMES_PER_WEEKDAY)
        if tpw_raw is None and any(p.get(k) for k in WEEKDAY_FORM_KEYS):
            tpw_raw = [p.get(k, "") for k in WEEKDAY_FORM_KEYS]
        tpw_parsed, tpw_err = _parse_times_per_weekday(tpw_raw)
        if tpw_err is not None:
            p_errors[CONF_MED_TIMES_PER_WEEKDAY] = tpw_err
            prescription_errors.append(p_errors)
            continue

        # Build canonical RRULE from validated friendly fields.
        if freq == FREQ_WEEKLY:
            rrule_str = schedule_to_rrule(
                SCHEDULE_TYPE_WEEKLY, weekdays=days, ends_on=ends_on_parsed
            )
            schedule_type = SCHEDULE_TYPE_WEEKLY
        elif freq == FREQ_MONTHLY:
            rrule_str = schedule_to_rrule(
                SCHEDULE_TYPE_MONTHLY, days_of_month=doms, ends_on=ends_on_parsed
            )
            schedule_type = SCHEDULE_TYPE_MONTHLY
        elif freq == FREQ_INTERVAL:
            rrule_str = schedule_to_rrule(
                SCHEDULE_TYPE_INTERVAL,
                interval_days=interval_days_parsed,
                ends_on=ends_on_parsed,
            )
            schedule_type = SCHEDULE_TYPE_INTERVAL
        else:
            rrule_str = schedule_to_rrule(
                SCHEDULE_TYPE_DAILY, ends_on=ends_on_parsed
            )
            schedule_type = SCHEDULE_TYPE_DAILY

        validated_prescriptions.append({
            CONF_PRESCRIPTION_ID: p.get(CONF_PRESCRIPTION_ID) or uuid.uuid4().hex,
            CONF_MED_PERSON: p.get(CONF_MED_PERSON) or None,
            CONF_MED_UNIT_COUNT: dose.count,
            CONF_MED_UNIT_STRENGTH_MG: dose.strength_mg,
            CONF_MED_TOTAL_DOSE_MG: dose.total_mg,
            CONF_MED_DOSE: dose.formatted(),
            CONF_MED_RRULE: rrule_str,
            CONF_MED_SCHEDULE_TYPE: schedule_type,
            CONF_MED_TIMES: times,
            CONF_MED_REMIND_WINDOW: int(
                p.get(CONF_MED_REMIND_WINDOW) or DEFAULT_REMIND_WINDOW
            ),
            CONF_MED_ENDS_ON: ends_on_parsed.isoformat() if ends_on_parsed else None,
            CONF_MED_TIMES_PER_WEEKDAY: tpw_parsed,
            CONF_MED_CYCLE_ANCHOR: None,
            CONF_MED_CYCLE_ON_DAYS: None,
            CONF_MED_CYCLE_OFF_DAYS: None,
        })
        prescription_errors.append({})

    has_errors = (
        bool(drug_errors)
        or bool(base_error)
        or any(pe for pe in prescription_errors)
    )
    if has_errors:
        return None, {
            "drug": drug_errors,
            "prescriptions": prescription_errors,
            "base": base_error,
        }

    # ---- medicine database autofill (same logic as single-prescription) ----
    med_db: MedicineDatabase | None = (
        hass.data.get(DOMAIN, {}).get("medicine_db") if hass else None
    )
    lookup = (
        lookup_by_name(med_db.medicines, name)
        if med_db is not None else None
    )
    user_atc = (drug.get(CONF_MED_ATC_CODE) or "").strip()
    atc_final = user_atc or (lookup.get("atc_code") if lookup else "") or None
    user_notes = (drug.get(CONF_MED_NOTES) or "").strip()
    if not user_notes and lookup and lookup.get("active_substance"):
        notes_final = lookup["active_substance"]
    else:
        notes_final = user_notes

    return {
        CONF_MED_NAME: name,
        CONF_MED_TYPE: med_type,
        CONF_MED_NOTES: notes_final,
        CONF_MED_NPL_ID: _strip_or_none(drug.get(CONF_MED_NPL_ID)),
        CONF_MED_VARUNUMMER: _strip_or_none(drug.get(CONF_MED_VARUNUMMER)),
        CONF_MED_ATC_CODE: atc_final,
        CONF_MED_PRESCRIPTIONS: validated_prescriptions,
    }, {}


# ---------------------------------------------------------------------------
# Constants for selectors
# ---------------------------------------------------------------------------

WEEKDAYS = [
    {"value": "0", "label": "Mon"},
    {"value": "1", "label": "Tue"},
    {"value": "2", "label": "Wed"},
    {"value": "3", "label": "Thu"},
    {"value": "4", "label": "Fri"},
    {"value": "5", "label": "Sat"},
    {"value": "6", "label": "Sun"},
]

FREQUENCY_OPTIONS = [
    {"value": FREQ_DAILY, "label": "Daily — every day"},
    {"value": FREQ_WEEKLY, "label": "Weekly — on selected weekdays"},
    {"value": FREQ_MONTHLY, "label": "Monthly — on selected days of the month"},
    {"value": FREQ_INTERVAL, "label": "Every N days — every other day, every 3 days, etc."},
]

# HA Settings form renders per-weekday times as 7 separate string
# fields (one per weekday). The panel form sends the canonical list
# shape directly. Both paths converge in the validator: if the
# canonical list is missing but any of these 7 keys is set, we
# consolidate them into the list shape before parsing. Order matches
# Mon=0..Sun=6 used everywhere else in this codebase.
WEEKDAY_FORM_KEYS = (
    "times_mon", "times_tue", "times_wed", "times_thu",
    "times_fri", "times_sat", "times_sun",
)
WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Section keys for the collapsible-section form layout (v0.2.0-beta3.4).
# These are the top-level keys in the user_input dict when the form
# uses HA's `section()` schema construct: every field declared inside
# the section's inner Schema arrives nested under one of these keys.
# `_flatten_section_input` unpacks them back to flat shape before
# the validator runs, so the validator API and storage format stay
# section-unaware. A future migration to a multi-step config flow
# would keep the same flat shape — only this flow handler needs to
# know about sections.
SECTION_IDENTITY = "identity_section"
SECTION_IDENTIFIERS = "identifiers_section"
SECTION_SCHEDULE = "schedule_section"
SECTION_PER_WEEKDAY = "per_weekday_section"
SECTION_KEYS = (
    SECTION_IDENTITY,
    SECTION_IDENTIFIERS,
    SECTION_SCHEDULE,
    SECTION_PER_WEEKDAY,
)

MED_TYPE_OPTIONS = [
    {"value": MED_TYPE_PILL, "label": "Pill / tablet"},
    {"value": MED_TYPE_DROPS, "label": "Drops"},
    {"value": MED_TYPE_INJECTION, "label": "Injection"},
]


def _person_label(hass, entity_id: str | None) -> str | None:
    """Friendly name of a person entity, or None for household."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state and state.attributes.get("friendly_name"):
        return state.attributes["friendly_name"]
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


def build_subentry_title(hass, med: dict[str, Any]) -> str:
    """Build the title shown for a medicine subentry on the integration card.

    Two members of a household commonly take the same medicine at
    different doses (e.g. Levaxin 50 µg: 3 pills for Sam, 1 pill for
    Josef). Without person disambiguation, both subentries show as
    "Levaxin" and the integration card becomes useless for telling
    them apart.

    v0.2.24 introduced multi-prescription medicines (one drug record
    can hold prescriptions for several people). Title format follows
    a tiered approach by prescription count:

      "Levaxin"                       household, no person
      "Levaxin — Sam Mahdi"           single prescription with person
      "Levaxin — Sam, Josef"          2-3 prescriptions with persons
      "Levaxin (4 persons)"           4+ prescriptions

    Public (no leading underscore) so __init__.py's migration can
    re-title existing subentries without importing private state.
    """
    name = med.get(CONF_MED_NAME) or "Medicine"
    prescriptions = med.get(CONF_MED_PRESCRIPTIONS) or []

    # Pre-v0.2.24 medicines (before async_migrate_entry runs) have the
    # legacy top-level person field instead of a prescriptions list.
    # Fall back to that during the brief migration window — the title
    # then gets recomputed when the migration finishes.
    if not prescriptions and "person" in med:
        person_label = _person_label(hass, med.get("person"))
        return f"{name} — {person_label}" if person_label else name

    person_labels = [
        _person_label(hass, p.get(CONF_MED_PERSON))
        for p in prescriptions
    ]
    person_labels = [lbl for lbl in person_labels if lbl]

    if not person_labels:
        return name
    if len(person_labels) == 1:
        return f"{name} — {person_labels[0]}"
    if len(person_labels) <= 3:
        return f"{name} — {', '.join(person_labels)}"
    return f"{name} ({len(person_labels)} persons)"


# ---------------------------------------------------------------------------
# Parent config flow — runs once at install + reconfigure
# ---------------------------------------------------------------------------


class PillPilotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup wizard. One form covers initial install and reconfigure."""

    VERSION = 1

    def __init__(self) -> None:
        self._draft: dict[str, Any] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Tell HA we support 'medicine' subentries.

        The presence of this method makes HA render an "Add medicine"
        button on the integration card.
        """
        return {"medicine": MedicineSubentryFlow}

    # ------- initial install ----------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            self._draft[CONF_PANEL_VISIBILITY] = user_input.get(
                CONF_PANEL_VISIBILITY, DEFAULT_PANEL_VISIBILITY
            )
            self._draft[CONF_MEDICINES_DB_URL] = (
                user_input.get(CONF_MEDICINES_DB_URL) or DEFAULT_MEDICINES_DB_URL
            )
            return self._finish()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PANEL_VISIBILITY,
                        default=DEFAULT_PANEL_VISIBILITY,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=PANEL_VISIBILITY_OPTIONS,
                            translation_key="panel_visibility",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDICINES_DB_URL,
                        default=DEFAULT_MEDICINES_DB_URL,
                    ): str,
                }
            ),
        )

    def _finish(self) -> ConfigFlowResult:
        """Finish either the install flow or the reconfigure flow.

        For install we call ``async_create_entry`` to make a new entry.
        For reconfigure we update the existing entry's data and trigger
        a reload — which is what picks up the panel visibility change
        and (if requested) refreshes the medicines list.
        """
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=self._draft,
            )
        return self.async_create_entry(title="PillPilot", data=self._draft)

    # ------- reconfigure (re-edit panel visibility, list URL,
    #         and trigger a one-shot refresh) -----------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user re-edit settings without removing the entry.

        Three things to set:
          - Panel visibility (sidebar visibility).
          - Medicines DB URL (where ``Refresh medicine list now`` pulls from).
          - "Refresh medicine list now" — a one-shot toggle. When checked
            on submit, the integration setup hook fetches a fresh list
            from the URL above and persists it. The toggle is then
            stripped from the entry so it doesn't re-fire on each reload.
        """
        existing = self._get_reconfigure_entry()
        self._draft = dict(existing.data)
        if user_input is not None:
            self._draft[CONF_PANEL_VISIBILITY] = user_input.get(
                CONF_PANEL_VISIBILITY, DEFAULT_PANEL_VISIBILITY
            )
            self._draft[CONF_MEDICINES_DB_URL] = (
                user_input.get(CONF_MEDICINES_DB_URL) or DEFAULT_MEDICINES_DB_URL
            )
            if user_input.get(CONF_MEDICINES_DB_REFRESH_NOW):
                # Transient — async_setup_entry honors and clears it.
                self._draft[CONF_MEDICINES_DB_REFRESH_NOW] = True
            return self._finish()

        # Show current list version & count if we can — purely
        # informational, helps the user know whether refresh is worth it.
        med_db: MedicineDatabase | None = (
            self.hass.data.get(DOMAIN, {}).get("medicine_db")
        )
        return self.async_show_form(
            step_id="reconfigure",
            description_placeholders={
                "list_version": (
                    med_db.list_version if med_db is not None else "unknown"
                ),
                "list_count": (
                    str(len(med_db.medicines)) if med_db is not None else "0"
                ),
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PANEL_VISIBILITY,
                        default=existing.data.get(
                            CONF_PANEL_VISIBILITY, DEFAULT_PANEL_VISIBILITY
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=PANEL_VISIBILITY_OPTIONS,
                            translation_key="panel_visibility",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDICINES_DB_URL,
                        default=existing.data.get(
                            CONF_MEDICINES_DB_URL, DEFAULT_MEDICINES_DB_URL
                        ),
                    ): str,
                    vol.Optional(
                        CONF_MEDICINES_DB_REFRESH_NOW, default=False
                    ): bool,
                }
            ),
        )


# ---------------------------------------------------------------------------
# Subentry flow — one per medicine
# ---------------------------------------------------------------------------


class MedicineSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one medicine.

    Both the "Add medicine" button and the per-medicine "Reconfigure"
    button on the integration card route to this flow. ``async_step_user``
    handles new additions, ``async_step_reconfigure`` handles edits.
    """

    def __init__(self) -> None:
        self._draft: dict[str, Any] = {}

    # ------- add ----------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_form(user_input, existing=None, finalize=self._create)

    async def _create(self, med: dict[str, Any]) -> SubentryFlowResult:
        return self.async_create_entry(
            title=build_subentry_title(self.hass, med),
            data=med,
        )

    # ------- reconfigure --------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        existing_sub = self._get_reconfigure_subentry()
        return await self._async_form(
            user_input,
            existing=dict(existing_sub.data),
            finalize=self._update,
        )

    async def _update(self, med: dict[str, Any]) -> SubentryFlowResult:
        """Persist an edit from the reconfigure form.

        v0.2.24: form is single-prescription; existing subentry may
        have additional prescriptions (after v0.2.25 lands) that this
        form never sees. ``merge_v2_form_into_existing`` splices the
        form's prescriptions[0] in as the first prescription and
        preserves the rest. Drug-identity fields come from the form
        (the user may have edited them). Single-prescription medicines
        — every existing record in v0.2.24 — round-trip identically.
        """
        existing_sub = self._get_reconfigure_subentry()
        merged = merge_v2_form_into_existing(med, dict(existing_sub.data))
        return self.async_update_and_abort(
            self._get_entry(),
            existing_sub,
            data=merged,
            title=build_subentry_title(self.hass, merged),
        )

    # ------- shared form --------------------------------------------------

    async def _async_form(
        self,
        user_input: dict[str, Any] | None,
        existing: dict[str, Any] | None,
        finalize,
    ) -> SubentryFlowResult:
        """Render the medicine form; validate; call ``finalize(med_dict)``.

        Used by both the user step (add) and the reconfigure step (edit)
        — the form is identical, only the finalize callback differs.

        v0.2.21: validation moved to module-level ``validate_medicine_input``
        so the in-panel edit modal can reuse it.

        v0.2.0-beta3.4: form fields are grouped into collapsible
        sections via HA's ``section()`` schema construct. User input
        arrives nested under section keys; we flatten before passing
        to the validator so the validator API and the on-disk storage
        format both stay section-unaware. A future migration to a
        multi-step config flow keeps the same flat-shape contract —
        only this handler knows about sections.
        """
        existing = existing or {}
        errors: dict[str, str] = {}

        if user_input is not None:
            flat_input = self._flatten_section_input(user_input)
            med, errors = validate_medicine_input(self.hass, flat_input)
            if med is not None:
                return await finalize(med)

        defaults = self._defaults_from(existing)
        return self.async_show_form(
            step_id="user" if existing == {} else "reconfigure",
            errors=errors,
            data_schema=self._schema(defaults),
        )

    @staticmethod
    def _flatten_section_input(user_input: dict[str, Any]) -> dict[str, Any]:
        """Unwrap section nesting into a flat field-name → value map.

        HA's ``section()`` schema construct returns user input nested
        one level deep under each section key
        (``user_input["identity_section"]["name"]``); the validator
        and every other consumer of this dict expects flat keys
        (``user_input["name"]``). Top-level non-dict values pass
        through unchanged so the bare ``remind_window_minutes`` field
        (declared outside any section) still arrives correctly.

        No field in the schema has a dict value, so the
        "is value a dict" test is sufficient to distinguish a section
        wrapper from a real value.
        """
        flat: dict[str, Any] = {}
        for key, value in user_input.items():
            if isinstance(value, dict):
                flat.update(value)
            else:
                flat[key] = value
        return flat

    @staticmethod
    def _defaults_from(existing: dict[str, Any]) -> dict[str, Any]:
        """Build form defaults from an existing medicine record.

        v0.2.24: ``existing`` is a v2-shaped subentry data dict — drug
        identity at top level, prescriptions inside ``prescriptions[]``.
        For the form (still single-prescription in v0.2.24) we read the
        drug fields from ``existing`` and the prescription fields from
        the first element of ``existing.prescriptions[]``. Empty
        existing (creating a new medicine) gives form defaults.

        Note on the ``or ""`` pattern: optional identifier fields
        (varunummer, NPL, ATC) are saved as ``None`` when blank so the
        integration can distinguish "no value" from "empty string". On
        reconfigure we must coerce that ``None`` back to ``""`` before
        handing it to voluptuous as a default — otherwise the ``str``
        validator rejects it with "expected str" on every submit,
        regardless of which field the user actually changed.
        """
        prescriptions = existing.get(CONF_MED_PRESCRIPTIONS) or []
        first = prescriptions[0] if prescriptions else {}

        # v0.2.0+: storage is RRULE-based, but the HA Settings form
        # still uses friendly frequency/days/days_of_month inputs.
        # Derive friendly fields from the stored RRULE for the form
        # defaults. New medicine creation (empty `first`) falls
        # through to the historical defaults below.
        stored_rrule = first.get(CONF_MED_RRULE)
        stored_schedule_type = first.get(CONF_MED_SCHEDULE_TYPE)
        if stored_rrule:
            friendly = rrule_to_friendly(stored_rrule)
            # Daily / weekly / monthly / interval map 1:1 to the form
            # frequency value. Cycle and custom modes don't have UI
            # in HA Settings yet — they fall back to daily so the form
            # opens cleanly; users edit those modes through the panel
            # sub-modal once beta4/beta5 wire the UI.
            if stored_schedule_type in (
                SCHEDULE_TYPE_DAILY,
                SCHEDULE_TYPE_WEEKLY,
                SCHEDULE_TYPE_MONTHLY,
                SCHEDULE_TYPE_INTERVAL,
            ):
                form_frequency = stored_schedule_type
            else:
                form_frequency = SCHEDULE_TYPE_DAILY
            form_days = friendly["weekdays"] or list(range(7))
            form_doms = friendly["days_of_month"] or []
            form_interval = friendly["interval_days"] or 2
        else:
            # New medicine — historical defaults.
            form_frequency = FREQ_DAILY
            form_days = list(range(7))
            form_doms = []
            form_interval = 2

        # ends_on: stored as ISO string ("YYYY-MM-DD") or None. Form
        # field is also string so just pass through. None becomes ""
        # so voluptuous's str validator doesn't reject it.
        form_ends_on = first.get(CONF_MED_ENDS_ON) or ""

        # Per-weekday defaults: 7 string fields, one per weekday. If
        # stored as None (simple mode), all 7 default to "" — meaning
        # "use the flat 'Times of day' for all weekdays." If stored
        # as the per-weekday list, each form field gets its weekday's
        # comma-joined times. Empty entries stay empty (= skip that
        # weekday, panel-only feature; HA Settings users with empty
        # entries don't accidentally trigger skip-day on first save
        # because the validator falls back to simple mode when ALL 7
        # are empty).
        stored_tpw = first.get(CONF_MED_TIMES_PER_WEEKDAY)
        weekday_defaults: dict[str, str] = {}
        if isinstance(stored_tpw, list) and len(stored_tpw) == 7:
            for key, row in zip(WEEKDAY_FORM_KEYS, stored_tpw):
                weekday_defaults[key] = ",".join(row or [])
        else:
            for key in WEEKDAY_FORM_KEYS:
                weekday_defaults[key] = ""

        return {
            CONF_MED_NAME: existing.get(CONF_MED_NAME) or "",
            CONF_MED_TYPE: existing.get(CONF_MED_TYPE) or MED_TYPE_PILL,
            CONF_MED_UNIT_COUNT: first.get(CONF_MED_UNIT_COUNT) or 1,
            CONF_MED_UNIT_STRENGTH_MG: first.get(CONF_MED_UNIT_STRENGTH_MG) or 10.0,
            CONF_MED_NOTES: existing.get(CONF_MED_NOTES) or "",
            CONF_MED_NPL_ID: existing.get(CONF_MED_NPL_ID) or "",
            CONF_MED_VARUNUMMER: existing.get(CONF_MED_VARUNUMMER) or "",
            CONF_MED_ATC_CODE: existing.get(CONF_MED_ATC_CODE) or "",
            CONF_MED_PERSON: first.get(CONF_MED_PERSON) or None,
            CONF_MED_FREQUENCY: form_frequency,
            CONF_MED_TIMES: ",".join(first.get(CONF_MED_TIMES) or ["07:00"]),
            CONF_MED_DAYS: [str(d) for d in form_days],
            CONF_MED_DAYS_OF_MONTH: ",".join(str(d) for d in form_doms),
            CONF_MED_INTERVAL_DAYS: form_interval,
            CONF_MED_ENDS_ON: form_ends_on,
            **weekday_defaults,
            CONF_MED_REMIND_WINDOW: first.get(CONF_MED_REMIND_WINDOW)
            or DEFAULT_REMIND_WINDOW,
        }

    def _schema(self, defaults: dict[str, Any]) -> vol.Schema:
        # name is a searchable dropdown sourced from
        # medicines_se.json. ``custom_value=True`` means the user can
        # still type a free-text name not in the list. Aliases are
        # baked into each option's label so HA's frontend substring
        # match finds entries via common misspellings.
        med_db: MedicineDatabase | None = (
            self.hass.data.get(DOMAIN, {}).get("medicine_db")
        )
        name_options = (
            build_dropdown_options(med_db.medicines)
            if med_db is not None and med_db.is_loaded
            else []
        )
        # v0.2.18 force-pick-person bug fix: ``vol.Optional(KEY,
        # default="")`` against an EntitySelector validates the empty
        # string against the entity-id schema and rejects it, which
        # surfaces in the form as "Required" — exactly the bug it caused
        # ("the med force u to choose a person"). Fix is to only set
        # the default when there's an actual person to pre-fill,
        # otherwise omit the default and let HA render the field
        # blank with no validator-rejected sentinel value.
        person_default = defaults.get(CONF_MED_PERSON)
        person_key = (
            vol.Optional(CONF_MED_PERSON, default=person_default)
            if person_default
            else vol.Optional(CONF_MED_PERSON)
        )
        return vol.Schema(
            {
                vol.Required(SECTION_IDENTITY): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_MED_NAME, default=defaults[CONF_MED_NAME]
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=name_options,
                                    custom_value=True,
                                    mode=SelectSelectorMode.DROPDOWN,
                                    sort=True,
                                )
                            ),
                            vol.Required(
                                CONF_MED_TYPE, default=defaults[CONF_MED_TYPE]
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=MED_TYPE_OPTIONS,
                                    mode=SelectSelectorMode.LIST,
                                )
                            ),
                            vol.Required(
                                CONF_MED_UNIT_COUNT,
                                default=defaults[CONF_MED_UNIT_COUNT],
                            ): NumberSelector(
                                NumberSelectorConfig(
                                    min=0.1, max=100, step=0.1,
                                    mode=NumberSelectorMode.BOX,
                                )
                            ),
                            vol.Required(
                                CONF_MED_UNIT_STRENGTH_MG,
                                default=defaults[CONF_MED_UNIT_STRENGTH_MG],
                            ): NumberSelector(
                                NumberSelectorConfig(
                                    min=0.001,
                                    max=100000,
                                    step=0.001,
                                    mode=NumberSelectorMode.BOX,
                                    unit_of_measurement="mg",
                                )
                            ),
                            vol.Optional(
                                CONF_MED_NOTES, default=defaults[CONF_MED_NOTES]
                            ): str,
                            person_key: EntitySelector(
                                EntitySelectorConfig(domain="person")
                            ),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_IDENTIFIERS): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                CONF_MED_VARUNUMMER,
                                default=defaults[CONF_MED_VARUNUMMER],
                            ): str,
                            vol.Optional(
                                CONF_MED_NPL_ID,
                                default=defaults[CONF_MED_NPL_ID],
                            ): str,
                            vol.Optional(
                                CONF_MED_ATC_CODE,
                                default=defaults[CONF_MED_ATC_CODE],
                            ): str,
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(SECTION_SCHEDULE): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_MED_FREQUENCY,
                                default=defaults[CONF_MED_FREQUENCY],
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=FREQUENCY_OPTIONS,
                                    mode=SelectSelectorMode.LIST,
                                )
                            ),
                            vol.Required(
                                CONF_MED_TIMES, default=defaults[CONF_MED_TIMES]
                            ): str,
                            vol.Optional(
                                CONF_MED_DAYS, default=defaults[CONF_MED_DAYS]
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=WEEKDAYS,
                                    multiple=True,
                                    mode=SelectSelectorMode.LIST,
                                )
                            ),
                            vol.Optional(
                                CONF_MED_DAYS_OF_MONTH,
                                default=defaults[CONF_MED_DAYS_OF_MONTH],
                            ): str,
                            vol.Optional(
                                CONF_MED_INTERVAL_DAYS,
                                default=defaults[CONF_MED_INTERVAL_DAYS],
                            ): NumberSelector(
                                NumberSelectorConfig(
                                    min=2, max=365, step=1,
                                    mode=NumberSelectorMode.BOX,
                                )
                            ),
                            # ends_on is a free-text str rather than a
                            # DateSelector — DateSelector rejects empty
                            # string, but the universal-but-optional
                            # design needs an explicit "no end date"
                            # representation, and "" is the cleanest
                            # one. Validator parses ISO YYYY-MM-DD and
                            # surfaces ends_on_invalid on bad input.
                            vol.Optional(
                                CONF_MED_ENDS_ON,
                                default=defaults[CONF_MED_ENDS_ON],
                            ): str,
                        }
                    ),
                    {"collapsed": False},
                ),
                # Per-weekday times: 7 separate fields. Leave all blank
                # to use the simple "Times of day" field above for every
                # firing weekday. Filling any switches the prescription
                # to per-weekday mode; blanks then mean skip-day.
                # Collapsed by default — power-user feature.
                vol.Required(SECTION_PER_WEEKDAY): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                "times_mon", default=defaults.get("times_mon", "")
                            ): str,
                            vol.Optional(
                                "times_tue", default=defaults.get("times_tue", "")
                            ): str,
                            vol.Optional(
                                "times_wed", default=defaults.get("times_wed", "")
                            ): str,
                            vol.Optional(
                                "times_thu", default=defaults.get("times_thu", "")
                            ): str,
                            vol.Optional(
                                "times_fri", default=defaults.get("times_fri", "")
                            ): str,
                            vol.Optional(
                                "times_sat", default=defaults.get("times_sat", "")
                            ): str,
                            vol.Optional(
                                "times_sun", default=defaults.get("times_sun", "")
                            ): str,
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(
                    CONF_MED_REMIND_WINDOW,
                    default=defaults[CONF_MED_REMIND_WINDOW],
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5,
                        max=240,
                        step=5,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="min",
                    )
                ),
            }
        )
