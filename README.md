# PillPilot for Home Assistant

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://github.com/TSA3000/ha-pillpilot/blob/main/LICENSE)
[![Release](https://img.shields.io/github/v/release/TSA3000/ha-pillpilot?include_prereleases&label=release)](https://github.com/TSA3000/ha-pillpilot/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-41bdf5.svg?logo=home-assistant&logoColor=white)](https://www.home-assistant.io)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee-support-FFDD00?style=flat-square&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/tsa3000)

Home Assistant integration for medication reminders with a custom side panel for tracking what's due, what's been taken, and per-person dose history.

> Take an HA backup before installing. See the [Disclaimer](#disclaimer) at the bottom.

## Install

**Manual:** copy `custom_components/pillpilot/` into `<config>/custom_components/pillpilot/`, restart HA, then **Settings → Devices & services → + Add Integration → PillPilot**.

**HACS (custom repository):** HACS → ⋮ → Custom repositories → add the repo with category *Integration* → install → restart → add the integration.

## Setup

After install, go to **Settings → Devices & services → PillPilot** card and click **+ Add medicine** for each medicine. Pick from the bundled Swedish medicine list (autocomplete with fuzzy matching on common misspellings and alternate names) or type a name not in the list. Set per-dose count, strength, frequency (daily / weekly / monthly / every N days), times, and optionally assign to a person.

Open the side panel from the HA sidebar to see what's due, mark doses taken, undo, snooze, or skip. Medicines can also be added and edited directly in the panel.

The integration's **Configure** dialog (on the PillPilot card) holds the household-level settings: sidebar panel visibility, the Managers list, per-panel language, and the medicine list URL.

## Sensor output

One `sensor.<medicine_name>` per medicine. State is `due` / `upcoming` / `taken` / `missed` / `skipped`. Attributes:

```yaml
medicine_id: a1b2c3d4e5f6
medicine_name: Levaxin
dose: "3 pills × 50 mg = 150 mg"
notes: ""
scheduled_times: ["07:30", "19:30"]
scheduled_days: [0, 1, 2, 3, 4, 5, 6]
next_dose_at: "2026-05-04T19:30:00+02:00"
last_taken_at: "2026-05-04T07:32:18+02:00"
varunummer: "165432"
npl_id: "19710716000023"
atc_code: "H03AA01"
visibility: "everyone"
visibility_users: []
today_doses:
  - scheduled_for: "2026-05-04T07:30:00+02:00"
    state: "taken"
    taken_at: "2026-05-04T07:32:18+02:00"
  - scheduled_for: "2026-05-04T19:30:00+02:00"
    state: "upcoming"
```

## Reminders & automations

The integration only fires events. Build whatever notification flow you want from there — bundled blueprints below, or write your own.

### Events fired

| Event | Data |
| --- | --- |
| `pillpilot_dose_due` | `medicine_id`, `medicine_name`, `dose`, `scheduled_for`, `person_id` |
| `pillpilot_dose_missed` | same shape |
| `pillpilot_dose_taken` | adds `taken_at` |
| `pillpilot_dose_skipped` | adds `skipped_at` |
| `pillpilot_dose_unmarked` | inverse of `dose_taken` (for undo flows) |

### Bundled blueprints

Two automation blueprints ship in `blueprints/automation/pillpilot/`. Together they cover the complete notification loop: send actionable notifications, handle the button taps. Import both.

**notify_dose** — sends actionable notifications with `[Take]`, `[Snooze]`, `[Skip]` buttons when a dose is due (and optionally re-pings on `dose_missed`).

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FTSA3000%2Fha-pillpilot%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpillpilot%2Fnotify_dose.yaml)

**handle_actions** — listens for `mobile_app_notification_action` events and calls the matching `pillpilot.*` service when the user taps a button.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FTSA3000%2Fha-pillpilot%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpillpilot%2Fhandle_actions.yaml)

Manual import: copy the YAML files into `<config>/blueprints/automation/pillpilot/`, then **Settings → Automations & Scenes → Blueprints**.

### Reminder example

Single-user setup — get a notification on your phone when any dose is due:

1. Import both blueprints (badges above).
2. **Settings → Automations & Scenes → + Create Automation → Use a blueprint → PillPilot — mobile notification**.
3. Fill in:
   - **Notification target:** `notify.mobile_app_<your_phone>` (find yours under Developer Tools → Services → search `notify.`)
   - **Limit to person:** leave blank (single user)
   - **Repeat when missed:** on (recommended)
4. Save. Create another automation from **PillPilot — handle notification actions** with no inputs — this one wires the button taps back to the integration.

That's it. When a dose comes due you get a push notification with `Taken / Snooze 15m / Skip`. Tapping a button calls the service automatically.

Multi-user household: create one **notify_dose** automation per person. Set **Limit to person** to that person's `person.<name>` entity and **Notification target** to that person's phone. Use one shared **handle_actions** automation for everyone.

### Custom automation example

For when you want something the blueprint doesn't cover — e.g. flash a smart light when a dose is due, then turn it off when taken:

```yaml
automation:
  - alias: "Pill light on when dose due"
    trigger:
      - platform: event
        event_type: pillpilot_dose_due
    action:
      - service: light.turn_on
        target:
          entity_id: light.kitchen_pill_reminder
        data:
          color_name: red
          brightness: 255

  - alias: "Pill light off when taken or skipped"
    trigger:
      - platform: event
        event_type: pillpilot_dose_taken
      - platform: event
        event_type: pillpilot_dose_skipped
    action:
      - service: light.turn_off
        target:
          entity_id: light.kitchen_pill_reminder
```

Filter by person, medicine, or time of day with a `condition:` block on `trigger.event.data.person_id`, `trigger.event.data.medicine_id`, or any other field from the events table above.

## Access control

Three layers, all optional — a fresh install behaves like a single-household tracker where every HA user sees everything and every admin can manage.

**Managers** — the Configure dialog has a Managers list: the HA users allowed to create, edit, and delete medicines (from the panel or via the websocket commands). The owner is always a manager. An empty list means every HA admin can manage, which is the default and matches the behavior of older versions. Dose actions (Take / Skip / Snooze / Undo) are not gated — everyone can record their own doses, and mobile notification actions keep working for all users.

**Per-medicine visibility** — each medicine has a Visibility setting in the panel's Add / Edit dialog:

| Mode | Who sees the medicine in the panel |
| --- | --- |
| Everyone | Anyone with panel access (default) |
| Linked person only | HA users whose person entity is on one of the medicine's prescriptions |
| Admins only | HA admins |
| Specific users | An explicit list you pick |

Owner and managers always see every medicine. The same check is enforced on the backend for edit and delete, so it isn't just cosmetic filtering.

**Sidebar panel visibility** — who gets the PillPilot sidebar entry: Admins only, Selected users, Everyone, or Hidden. In Selected users mode, Home Assistant's panel API can't hide the sidebar entry per-user, so the entry is visible to everyone — users not on the list get an access-denied screen when they open it, and the management commands stay gated on the backend.

Note: sensor entities remain readable by any logged-in HA user regardless of these settings (for example via Developer Tools). Home Assistant's entity permissions don't support per-user filtering. See [PRIVACY.md](PRIVACY.md).

## Panel language

The panel UI follows each user's Home Assistant language by default (English and Swedish are available). The Configure dialog can pin it to one language for everyone. The HA settings dialogs use Home Assistant's own translation system and follow the HA language as usual.

## Services

| Service | Purpose |
| --- | --- |
| `pillpilot.mark_taken` | Record a taken dose |
| `pillpilot.skip` | Skip a scheduled dose |
| `pillpilot.snooze` | Reschedule a dose for later |
| `pillpilot.unmark_taken` | Undo a `mark_taken` (hover-undo) |
| `pillpilot.mark_taken_bulk` | Record several doses as taken in one call — one save and one refresh for the whole set |
| `pillpilot.snooze_bulk` | Snooze several doses by the same number of minutes in one call |
| `pillpilot.unmark_taken_bulk` | Undo several taken doses in one call |
| `pillpilot.refresh_medicines_database` | Fetch a new copy of the medicines list |

Single-dose services take a `medicine_id` (and optional `when` for retroactive marking); bulk services take an `items` list. The panel's Take all / Take due / Take missed buttons and bulk undo use the bulk services. See `services.yaml` for full schemas.

## Architecture

```
custom_components/pillpilot/
├── __init__.py          entry setup, services, hot-reload listener
├── const.py             keys, defaults, event names
├── config_flow.py       parent flow + medicine subentry flow
├── coordinator.py       1-min tick: schedule + dose history
├── dose.py              Dose model — count × strength formatting
├── schedule.py          Schedule model — RRULE-based recurrence (daily / weekly / monthly / every-N-days)
├── sensor.py            CoordinatorEntity per medicine
├── panel.py             custom side-panel registration
├── medicines.py         MedicineDatabase: load list, dropdown builder
├── medicines_se.json    bundled Swedish medicine list
├── frontend/
│   └── panel.js         the panel UI (vanilla custom element + shadow DOM)
├── brand/               icon.png + [email protected]
├── services.yaml        UI service definitions
├── strings.json         + translations/{en,sv}.json
└── sources/
    ├── __init__.py      factory: build_sources() — returns [] currently
    └── base.py          MedicineSource protocol

tools/                   not shipped in the integration zip
└── build_medicines_se.py  rebuild medicines_se.json from Läkemedelsverket's open-data export
```

## Medicine list

The bundled `medicines_se.json` is compiled from [Läkemedelsverket's open-data register](https://www.dataportal.se/datasets/140_5467) — every human medicine in Sök läkemedelsfakta with status *Godkänd* or *Registrerad*. Veterinary, deregistered, and temporarily withdrawn products are filtered out. The dataset is updated nightly upstream and is free to use under Sweden's open-data law (öppna data-lagen, 2022:818).

Each entry carries:

- `name` — display name (brand or generic)
- `active_substance` — `Verksamt ämne (förenklat)`
- `atc_code` — WHO ATC code from the export
- `variants` — one entry per distinct (strength, form) the medicine is sold in. Each variant carries `npl_id`, `strength` (e.g. `"5 mg"`, `"0,15 mg"`, `"100 E/ml"`, `"87 mikrogram/5 mikrogram/9 mikrogram"`), and `form` (e.g. `"Filmdragerad tablett"`, `"Depottablett"`, `"Injektionsvätska, lösning"`). Parallel imports of the same strength/form combo are deduped — first NPL-id wins.
- `aliases` — former product names from `Tidigare läkemedelsnamn`, plus any curated misspellings/generics added in PRs

### Rebuilding the list

`tools/build_medicines_se.py` regenerates the JSON from a fresh export. Not shipped in the integration zip — it's a maintainer tool.

1. Download the latest `Lakemedelsprodukter.xlsx` distribution from [dataset 140_5467](https://www.dataportal.se/datasets/140_5467).
2. Run:
   ```
   pip install openpyxl
   python tools/build_medicines_se.py \
       --input ~/Downloads/Lakemedelsprodukter.xlsx \
       --output custom_components/pillpilot/medicines_se.json
   ```
3. The script groups the per-strength export rows by `Namn`, applies the human + active-status filters, preserves any curated aliases already on existing entries (curated wins on conflict), and bumps `list_version` to today's date with an `-N` suffix. Use `--dry-run` to print stats without writing.

The script also accepts `.csv`, `.tsv`, `.xml`, and `.json` inputs — the column-detection logic uses a lookup table of common Swedish/English header names, so a renamed column in a future export usually doesn't break the build.

### Contributing curated aliases

The export covers names but doesn't carry common misspellings or alternate generic terms users might search for. PRs adding `aliases` for any entry are welcome — they're preserved across rebuilds. Open a PR editing `medicines_se.json` directly; once merged, existing users can pull the new aliases via **Reconfigure → Refresh medicine list now** without waiting for a HACS release.

## Known limitations

- Edit button on medicine cards goes to the integration page, not the subentry's reconfigure dialog directly.
- No PRN ("as needed") medicines — schedule-based only.
- Snooze is "schedule a future re-fire," not "suppress the original."
- In Selected users sidebar mode, the sidebar entry is visible to all users (Home Assistant's panel API has no per-user registration). Non-allowed users get an access-denied screen instead of the panel.
- Per-medicine visibility filters the panel and gates edits, but sensor entities stay readable by any logged-in HA user — Home Assistant has no per-user entity permissions.
- Per-medicine visibility can currently only be set from the panel's Add / Edit dialog, not from the medicine's reconfigure dialog in HA Settings.

## Privacy

PillPilot stores everything locally on your Home Assistant instance — nothing is sent to a remote server. That's a real privacy advantage over cloud-based medication trackers, but the data is plaintext on disk, and Home Assistant's recorder logs medicine names, dose schedules, and dose history to its database by default. Anyone with an HA login (not just admins) can see medicine entities, attributes, and history graphs. The per-medicine visibility setting hides medicines in the PillPilot panel, but it can't hide the underlying sensors.

The single biggest thing you can do: turn on backup encryption if you back up your HA config to anywhere except a trusted local disk. Optional second step — exclude PillPilot sensors from the recorder if you don't need the in-HA history graph:

```yaml
recorder:
  exclude:
    entities:
      - sensor.<your_medicine>
```

See [PRIVACY.md](PRIVACY.md) for the full picture: what's stored where, who can read it, what's exposed to other HA users, what mitigations are practical, and why integration-level encryption isn't offered.

## Credits

Icon by [Anggara](https://www.flaticon.com/authors/anggara) from [Flaticon](https://www.flaticon.com/free-icon/medicine-box_6582060).

## Disclaimer

This is a convenience tool. **Not** a medical device. Don't make it the only thing standing between you and a missed dose.

## License

GPLv3 — see [LICENSE](LICENSE).
