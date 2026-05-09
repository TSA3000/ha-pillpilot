# PillPilot User Manual

Two ways to manage your medicines — the **HA Settings** form and the **sidebar panel** — both write to the same data. This manual covers what each one is for, when to use which, and walks through common tasks in both.

> If you just want to install the integration, see [README.md](README.md). This manual assumes you're already set up.

## TL;DR

| You want to … | Use the … |
|---|---|
| Add a new medicine | HA Settings (it's the only place with the `+ Add medicine` button) |
| Edit a medicine's schedule | Either, but the panel is faster and clearer |
| Mark a dose as taken / skip / snooze | Sidebar panel |
| Check what's due today | Sidebar panel |
| See dose history | Sidebar panel |
| Configure advanced schedule features (per-weekday times, every-N-days, end dates) | Either, but the panel has nicer UI for these |
| Refresh the bundled medicine list | HA Settings → Configure |

## The two views

### Configuration view — HA Settings

**Where:** Settings → Devices & services → PillPilot card.

This is the standard Home Assistant integration page. Each medicine you add appears as a *subentry* on the PillPilot card with its own Edit (✎) and Remove (🗑) buttons. New medicines are added with the **+ Add medicine** button.

The Add and Reconfigure forms are organized into four collapsible sections:

- **Identity** *(expanded)* — Medicine name, type (pill / drops / injection), per-dose count, strength in mg, notes, and an optional person to assign it to.
- **Drug-database identifiers** *(collapsed)* — Varunummer, NPL ID, ATC code. Auto-filled when you pick a medicine from the dropdown; usually you don't need to expand this section.
- **Schedule** *(expanded)* — Frequency (daily / weekly / monthly / every N days), times of day, days of the week, days of the month, interval in days, end date. Field labels include `(Weekly only)` / `(Monthly only)` / `(Every-N-days only)` markers so it's clear which apply for the frequency you picked.
- **Per-weekday time overrides** *(collapsed)* — Seven rows (Mon–Sun) for advanced schedules where you want different times on different weekdays. Leave all blank for the same times every firing day; fill some to switch into per-weekday mode.

Below the sections is a single **Reminder window** field (how long the dose stays in `due` state before being marked `missed`).

**Use this view when:** adding a new medicine, doing a one-off edit, or you prefer the standard HA settings interface to a custom panel.

### Sidebar panel — the daily-use surface

**Where:** click the **PillPilot** entry in the Home Assistant left sidebar.

This is a custom panel for day-to-day medication tracking. The main view is a list of medicines grouped by person, with the next-due dose, current state (`due` / `upcoming` / `taken` / `missed` / `skipped`), and quick-action buttons.

What you can do here:

- **Mark a dose taken / skipped / snoozed** with one click on the dose row.
- **Undo** a recent mark-taken (hover a `taken` dose).
- **Edit a medicine** — click the medicine card to open the Edit modal. Same fields as the HA Settings form, with two UX improvements (see below).
- **Add prescriptions** to an existing medicine. (One medicine can have multiple prescriptions — e.g. morning + evening at different doses.)
- **Reorder, rename, or delete** medicines.

The Edit modal is where the panel diverges from HA Settings — the schedule editing is more interactive:

- **Times mode** is a radio pair instead of a checkbox: pick **Same times every day** to use a single comma-separated times field, or **Different times per weekday** to expose seven Mon–Sun rows. Switching modes is lossless within an edit session — what you typed in the other mode is still there if you switch back.
- **Days of week** uses chip buttons with three quick presets above them: **Every day**, **Weekdays**, **Weekends**. Tap a preset to overwrite the selection in one click; tap individual chips to fine-tune. The active preset highlights when your selection matches.
- **Frequency-conditional fields** (`Days of week` for Weekly, `Days of month` for Monthly, `Interval` for Every-N-days) only appear when relevant — the form stays compact regardless of which frequency you picked.

**Use this view when:** marking doses, checking what's due, or you'd rather edit a medicine in the panel's UI than in the HA Settings form.

## Common tasks, both ways

### Add a medicine that fires every day at 08:00 and 20:00

**HA Settings:** Settings → Devices & services → PillPilot → **+ Add medicine**. In the Identity section, pick the medicine from the dropdown and set the dose. In the Schedule section, set Frequency to `Daily`, Times of day to `08:00, 20:00`. Save.

**Panel:** opens the same Add modal — there's no `+ Add medicine` button in the panel as of this writing; new medicines go through the Settings flow. Once added, edit it from the panel for everything else.

### Switch a medicine to "Mon-Fri 08:00, Sat-Sun 10:00"

**Panel** (recommended): open the medicine → **Times mode** → pick **Different times per weekday** → set Mon-Fri rows to `08:00` and Sat-Sun rows to `10:00`. Save.

**HA Settings:** Reconfigure the medicine → expand the **Per-weekday time overrides** section → fill the same seven rows. The validator detects per-weekday mode automatically when any of the seven rows have content.

Both produce the same on-disk shape — the per-weekday data lives in the same `times_per_weekday` field either way.

### Schedule a 7-day antibiotic course

Either view: set Frequency to `Daily`, Times to whatever applies, then set **End date** to seven days from today. The schedule fires daily until the end date, then stops.

### Take it Mon, Wed, Fri only

**Panel:** Frequency → `Weekly`. In Days of week, tap **Every day** to start (or **Weekdays**), then tap individual chips to leave only Mon, Wed, Fri active. The chips toggle on tap.

**HA Settings:** Reconfigure → Schedule section → Frequency `Weekly` → Days of week → tick Mon, Wed, Fri.

### Every other day, starting tomorrow

Either view: Frequency → `Every N days` → Interval → `2`. The schedule's anchor is the prescription's start date, so it'll fire tomorrow, the day after tomorrow off, then on, etc. Survives month boundaries (May 30 → Jun 1 → Jun 3, not "May 30 then resets to Jun 1").

### Skip the medicine on weekends entirely (no doses Sat-Sun)

**Panel:** Times mode → **Different times per weekday**. Fill Mon-Fri rows with your times, leave Sat-Sun rows blank. Blank rows in per-weekday mode mean "no doses on that weekday."

**HA Settings:** same — fill Mon-Fri rows in the Per-weekday section, leave Sat-Sun blank.

Alternative: use Frequency `Weekly` with only Mon-Fri checked / chipped. Equivalent semantics.

### Mark a dose taken from your phone

Open Home Assistant on your phone → tap the **PillPilot** sidebar entry → tap the **Taken** button on the due dose row.

If you set up the bundled `notify_dose` blueprint (see README), you'll get a push notification with **Taken** / **Snooze 15m** / **Skip** buttons that mark it for you without opening the panel.

## Differences at a glance

| Capability | HA Settings | Panel |
|---|---|---|
| Add a new medicine | ✓ | — |
| Edit a medicine's identity, dose, schedule | ✓ | ✓ |
| Mark a dose taken / skipped / snoozed | — | ✓ |
| Undo a mark-taken | — | ✓ |
| See what's due today | — | ✓ |
| See per-medicine dose history | — | ✓ |
| Multiple prescriptions per medicine | — | ✓ |
| Per-weekday times | ✓ (text rows) | ✓ (text rows + mode picker) |
| Days-of-week selection | Multi-select dropdown | Chip buttons + presets |
| Conditional fields hidden when irrelevant | Section labels mark `(Weekly only)` etc. | Conditional fields only render for the picked frequency |
| Refresh bundled medicine list | ✓ (Configure → Refresh medicine list now) | — |

Both views save to the same backing store, so an edit in one is reflected in the other on next refresh.

## Why two views?

Home Assistant exposes two interfaces an integration can build on:

- The **standard config-flow** (HA Settings) is where every integration is installed and reconfigured. It uses voluptuous schemas — great for forms, limited in interactivity (no chip buttons, no live mode toggles, no per-row dynamic UI).
- A **custom panel** lets the integration build its own UI for domain-specific tasks. PillPilot's panel is where the daily medication-tracking workflow lives — marking doses, viewing history, the rich edit modal.

Neither view is "primary" — they cover different needs. The HA Settings form is the only place to add a medicine and the simplest place to do quick edits. The panel is where you'll spend most of your time once everything is set up.

## Notes & quirks

- **Browser cache after updating.** When PillPilot updates, the panel JavaScript is bundled into the frontend cache. If the panel looks the same after an update or you see raw field keys instead of labels, hard-refresh your browser (Ctrl+Shift+R / Cmd+Shift+R) to clear it.
- **Edit button on a medicine card** in HA Settings goes to the integration page, not directly to the subentry's reconfigure dialog. From there, click the medicine row to open the form.
- **Sections are collapsible, not enforced.** If you put data in a "(Weekly only)" field while frequency is set to Daily, it's silently ignored — the validator only enforces fields relevant to the chosen frequency.
- **Pre-1.0 caveat.** The data shape is stable across 0.x betas (migration helpers handle older shapes), but edge-case features may shift. See `CHANGELOG.md` for the current state.

## See also

- [README.md](README.md) — install, sensors, services, blueprints
- [CHANGELOG.md](CHANGELOG.md) — version history
- [Open an issue](https://github.com/TSA3000/ha-pillpilot/issues) — bugs or feature requests
