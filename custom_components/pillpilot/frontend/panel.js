// PillPilot side panel.
//
// Defines the <pillpilot-panel> custom element that Home Assistant
// renders when the user clicks "PillPilot" in the sidebar.
//
// HA gives us three properties when the panel mounts:
//   - hass:    the websocket-backed state object (hass.states, hass.callService, ...)
//   - narrow:  boolean, true on mobile-narrow viewports
//   - panel:   metadata about this panel registration
//
// Layout (mockup we agreed in v0.2.0 conversation):
//
//   header                          [+ Add medicine]
//
//   ┌─ Today's doses ──────  [✓✓ Mark all due]  ─┐
//   │ HH:MM  Name + dose     Person  [Take][Skip]│
//   │ HH:MM  Name + dose     Person  ✓ Taken at  │
//   ┘
//
//   <Person>'s medicines · N
//   ┌── card grid ──┐
//
// Per-slot logic:
//   The sensor exposes `today_doses` — an array of per-slot dicts with
//   {scheduled_at, time, status, action_at}. Each row reads from this
//   instead of guessing based on `last_taken_at`. status drives whether
//   we render action buttons (due/missed/upcoming) or a status label
//   (taken/skipped). "Mark all due" iterates only over due+missed.
//
// Implemented as a vanilla web component with Shadow DOM — no lit,
// no external imports, no build step.

const STATE_DUE = "due";
const STATE_UPCOMING = "upcoming";
const STATE_TAKEN = "taken";
const STATE_MISSED = "missed";
const STATE_SKIPPED = "skipped";
const STATE_SNOOZED = "snoozed";

// Medicine type IDs. Wire format — these strings ARE the identifiers
// stored in subentry data and exposed on sensor attributes. Mirrors
// MED_TYPE_PILL / MED_TYPE_DROPS / MED_TYPE_INJECTION in const.py.
// If you change a value here, change const.py to match.
const MED_TYPE_PILL = "pill";
const MED_TYPE_DROPS = "drops";
const MED_TYPE_INJECTION = "injection";

const STATE_LABELS = {
  [STATE_DUE]: { text: "due now", kind: "warning" },
  [STATE_UPCOMING]: { text: "upcoming", kind: "info" },
  [STATE_TAKEN]: { text: "taken", kind: "success" },
  [STATE_MISSED]: { text: "missed", kind: "error" },
  [STATE_SKIPPED]: { text: "skipped", kind: "neutral" },
  [STATE_SNOOZED]: { text: "snoozed", kind: "info" },
};

// Per-slot statuses that should show action buttons. Snoozed has its
// own renderer in _renderRowActions (label + Take/Skip), so it's
// intentionally NOT in this set — the snoozed branch handles it.
const ACTIONABLE = new Set([STATE_DUE, STATE_MISSED, STATE_UPCOMING]);
// Per-slot statuses that "Mark all due" should target. Excludes upcoming
// — marking a 21:00 dose at 09:00 would be misleading.
const PENDING = new Set([STATE_DUE, STATE_MISSED]);

const STYLES = `
  :host {
    display: block;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    min-height: 100vh;
    box-sizing: border-box;
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
  }
  .container {
    max-width: 960px;
    margin: 0 auto;
    padding: 24px 16px 48px;
  }
  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }
  h1 { margin: 0; font-size: 24px; font-weight: 500; line-height: 1.2; }
  .subtitle {
    margin: 4px 0 0;
    font-size: 14px;
    color: var(--secondary-text-color, #727272);
  }
  .add-btn {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    border: none;
    border-radius: 8px;
    padding: 10px 16px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    font-family: inherit;
  }
  .add-btn:hover { opacity: 0.9; }
  .header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .config-btn {
    background: transparent;
    color: var(--secondary-text-color, #727272);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    border-radius: 8px;
    /* Match .add-btn's vertical footprint so they line up. The width is
       intentionally compact — this is a secondary action, accessed by
       icon. On mobile the gear glyph is unambiguous and saves room. */
    width: 40px;
    height: 40px;
    cursor: pointer;
    font-size: 18px;
    font-family: inherit;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    line-height: 1;
  }
  .config-btn:hover {
    background: var(--secondary-background-color, #f5f5f5);
    color: var(--primary-text-color, #212121);
  }
  .today-section {
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 32px;
  }
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.08));
    background: var(--secondary-background-color, #f5f5f5);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .mark-all-btn {
    font-size: 12px;
    text-transform: none;
    letter-spacing: 0;
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid var(--primary-color, #03a9f4);
    background: transparent;
    color: var(--primary-color, #03a9f4);
    cursor: pointer;
    font-family: inherit;
    font-weight: 500;
  }
  .mark-all-btn:hover {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }
  .dose-row {
    display: grid;
    grid-template-columns: 70px 1fr auto auto;
    gap: 16px;
    padding: 14px 16px;
    align-items: center;
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.06));
  }
  .dose-row:last-child { border-bottom: none; }
  .dose-time { font-size: 18px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .dose-name { font-weight: 500; font-size: 15px; }
  .dose-detail {
    font-size: 13px;
    color: var(--secondary-text-color, #727272);
    margin-top: 2px;
  }
  .dose-person {
    font-size: 13px;
    color: var(--secondary-text-color, #727272);
    white-space: nowrap;
  }
  .dose-actions {
    display: flex;
    gap: 6px;
    white-space: nowrap;
  }
  .dose-action-btn {
    font-size: 13px;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    background: transparent;
    color: var(--primary-text-color, #212121);
    cursor: pointer;
    font-family: inherit;
  }
  .dose-action-btn:hover {
    background: var(--secondary-background-color, #f5f5f5);
  }
  .dose-action-btn.take {
    border-color: var(--success-color, #4caf50);
    color: var(--success-color, #4caf50);
  }
  .dose-action-btn.take:hover {
    background: var(--success-color, #4caf50);
    color: #fff;
  }
  .dose-action-btn.skip {
    border-color: var(--secondary-text-color, #727272);
    color: var(--secondary-text-color, #727272);
  }
  .dose-action-btn.skip:hover {
    background: var(--secondary-text-color, #727272);
    color: #fff;
  }
  .dose-action-btn.snooze {
    border-color: var(--info-color, #03a9f4);
    color: var(--info-color, #03a9f4);
  }
  .dose-action-btn.snooze:hover {
    background: var(--info-color, #03a9f4);
    color: #fff;
  }
  .dose-status-label {
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
    white-space: nowrap;
  }
  .dose-status-label.taken { color: var(--success-color, #4caf50); }
  .dose-status-label.skipped { color: var(--secondary-text-color, #727272); }
  .dose-status-label.snoozed { color: var(--info-color, #03a9f4); }
  .dose-snoozed-wrapper {
    display: inline-flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
  }

  /* v0.2.17: per-dose hover-to-undo on taken doses.
     Hover the green "✓ Taken at HH:MM" badge → it's hidden and the
     red Undo button takes over the same slot, in-place. The wrapper
     keeps a min-width so the row doesn't reflow on hover. */
  .dose-taken-wrapper {
    position: relative;
    display: inline-flex;
    align-items: center;
    min-width: 130px;
    justify-content: flex-end;
  }
  .dose-taken-wrapper .dose-status-label {
    pointer-events: none;
  }
  .dose-undo-btn {
    display: none;
    font-size: 13px;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid var(--error-color, #db4437);
    background: transparent;
    color: var(--error-color, #db4437);
    cursor: pointer;
    font-family: inherit;
    white-space: nowrap;
  }
  .dose-undo-btn:hover {
    background: var(--error-color, #db4437);
    color: #fff;
  }
  .dose-taken-wrapper:hover .dose-status-label { display: none; }
  .dose-taken-wrapper:hover .dose-undo-btn { display: inline-block; }

  /* v0.2.17: per-person collapsible sections inside Today's doses. */
  .person-doses-section {
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.12));
  }
  .person-doses-section:last-child { border-bottom: none; }
  .person-doses-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    background: var(--secondary-background-color, #fafafa);
    gap: 12px;
    flex-wrap: wrap;
  }
  .person-toggle {
    flex: 1 1 auto;
    min-width: 0;
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    color: inherit;
    font-family: inherit;
    text-align: left;
  }
  .person-toggle:hover .person-name {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .collapse-arrow {
    font-size: 11px;
    color: var(--secondary-text-color, #727272);
    width: 14px;
    flex-shrink: 0;
  }
  .person-name { font-weight: 600; font-size: 14px; }
  .person-summary {
    font-size: 13px;
    color: var(--secondary-text-color, #727272);
  }
  .person-actions {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  .bulk-action-btn {
    font-size: 12px;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    background: transparent;
    color: var(--primary-text-color, #212121);
    cursor: pointer;
    font-family: inherit;
    font-weight: 500;
    white-space: nowrap;
  }
  .bulk-action-btn:hover:not([disabled]) {
    background: var(--secondary-background-color, #f5f5f5);
  }
  .bulk-action-btn[disabled] {
    color: var(--disabled-text-color, #bdbdbd);
    border-color: var(--divider-color, rgba(0,0,0,0.08));
    cursor: not-allowed;
  }
  .kebab-wrapper { position: relative; }
  .kebab-btn {
    font-size: 18px;
    line-height: 1;
    padding: 4px 10px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    border-radius: 6px;
    background: transparent;
    color: var(--primary-text-color, #212121);
    cursor: pointer;
    font-family: inherit;
  }
  .kebab-btn:hover {
    background: var(--secondary-background-color, #f5f5f5);
  }
  .kebab-menu {
    display: none;
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.18);
    min-width: 200px;
    z-index: 10;
    overflow: hidden;
  }
  .kebab-menu.open { display: block; }
  .kebab-menu button {
    display: block;
    width: 100%;
    text-align: left;
    padding: 10px 14px;
    border: none;
    background: transparent;
    font-size: 13px;
    cursor: pointer;
    font-family: inherit;
    color: var(--primary-text-color, #212121);
  }
  .kebab-menu button:hover:not([disabled]) {
    background: var(--secondary-background-color, #f5f5f5);
  }
  .kebab-menu button[disabled] {
    color: var(--disabled-text-color, #bdbdbd);
    cursor: not-allowed;
  }
  .person-doses-body {
    background: var(--card-background-color, #fff);
  }
  /* No doses today for any person → keep section header out of the
     today-section so we don't show an empty card. Handled in JS. */
  .person-section { margin-bottom: 24px; }
  /* v0.2.18: per-person section header now holds both the title and
     the cards/list view toggle. v0.2.20 adds the sort dropdown to the
     same row. Title and controls stay on one line on desktop;
     controls wrap under the title on narrow viewports. */
  .person-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }
  .person-section-header h3 { margin: 0; }
  /* v0.2.20: container so the sort dropdown sits next to the
     view toggle and they wrap together on narrow viewports. */
  .header-controls {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .sort-select {
    font-size: 12px;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color, #212121);
    font-family: inherit;
    font-weight: 500;
    cursor: pointer;
  }
  .sort-select:hover {
    background: var(--secondary-background-color, #f5f5f5);
  }
  .view-toggle {
    display: inline-flex;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    border-radius: 6px;
    overflow: hidden;
  }
  .view-toggle-btn {
    font-size: 12px;
    padding: 5px 12px;
    border: none;
    background: transparent;
    color: var(--secondary-text-color, #727272);
    cursor: pointer;
    font-family: inherit;
    font-weight: 500;
  }
  .view-toggle-btn + .view-toggle-btn {
    border-left: 1px solid var(--divider-color, rgba(0,0,0,0.2));
  }
  .view-toggle-btn:hover {
    background: var(--secondary-background-color, #f5f5f5);
  }
  .view-toggle-btn.active {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }
  h3 {
    font-size: 16px;
    font-weight: 500;
    margin: 0 0 12px;
    color: var(--primary-text-color, #212121);
  }
  .med-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 12px;
  }
  /* v0.2.18: compact list view alternative to .med-grid. One medicine
     per row, just the essentials — name, status pill, dose math, schedule
     summary, last-taken, edit button. localStorage key
     pillpilot:medsView remembers the user's choice between cards and
     list. */
  /* v0.2.21: subgrid layout. The whole .med-list is the grid container
     and defines the canonical column widths once; each .med-list-row
     (header AND data rows) inherits those columns via
     'grid-template-columns: subgrid'. Pre-v0.2.21 every row was its
     own independent grid with 'auto' columns whose widths varied by
     content — STATUS/DOSE/SCHEDULE columns drifted between header and
     data, looking crowded and misaligned. With subgrid, headers sit
     directly above their data. */
  .med-list {
    display: grid;
    grid-template-columns:
      minmax(120px, 1.5fr)   /* name      */
      minmax(80px, auto)     /* status    */
      minmax(140px, 1.4fr)   /* dose      */
      minmax(110px, 1fr)     /* schedule  */
      minmax(80px, 0.6fr)    /* last_taken*/
      auto;                  /* edit btn  */
    gap: 0;
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    border-radius: 12px;
    overflow: hidden;
  }
  .med-list-row {
    display: grid;
    grid-template-columns: subgrid;
    grid-column: 1 / -1;
    column-gap: 12px;
    padding: 12px 16px;
    align-items: center;
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.06));
  }
  .med-list-row:last-child { border-bottom: none; }
  /* v0.2.20: column header row. Sticks to the same 6-column grid as
     the data rows so columns align. Sortable cells render as buttons
     with the matching column key in data-sort; non-sortable cells
     render as styled spans. Active column shows a ▲/▼ direction arrow. */
  .med-list-header {
    background: var(--secondary-background-color, #fafafa);
    padding: 8px 16px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 2px solid var(--divider-color, rgba(0,0,0,0.12));
  }
  .sort-header {
    font-size: 11px;
    font-weight: 600;
    color: var(--secondary-text-color, #727272);
    background: transparent;
    border: none;
    padding: 4px 0;
    text-align: left;
    cursor: pointer;
    font-family: inherit;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sort-header:hover:not(.sort-header-static) {
    color: var(--primary-text-color, #212121);
  }
  .sort-header.active {
    color: var(--primary-color, #03a9f4);
  }
  .sort-header-static {
    cursor: default;
  }
  .sort-header-static:hover {
    color: var(--secondary-text-color, #727272);
  }
  /* v0.2.21: per-column text alignment so headers and data line up
     visually within each cell. Status header + pill centered, last
     taken right-aligned (timestamp-style alignment helps scanning),
     others left. Targeted by nth-child since the cells are mixed
     buttons/spans/divs. */
  .med-list-row > *:nth-child(2) { justify-self: center; text-align: center; }
  .med-list-row > *:nth-child(5) { justify-self: end; text-align: right; }
  .med-list-name {
    font-weight: 500;
    font-size: 14px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .med-list-meta {
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .med-list-row .pill {
    font-size: 11px;
    padding: 2px 8px;
  }
  /* v0.2.21: in-panel edit modal. Fixed-position backdrop + centered
     card. The backdrop dims everything else and absorbs clicks
     (closes the modal); the card's data-action="modal-stop" stops
     bubbling so clicks inside don't dismiss. */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    padding: 16px;
  }
  .modal-card {
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color, #212121);
    border-radius: 12px;
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
    width: 100%;
    max-width: 640px;
    max-height: calc(100vh - 32px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.12));
  }
  .modal-header h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 500;
  }
  .modal-close-btn {
    background: transparent;
    border: none;
    font-size: 24px;
    line-height: 1;
    cursor: pointer;
    color: var(--secondary-text-color, #727272);
    padding: 0 8px;
    font-family: inherit;
  }
  .modal-close-btn:hover {
    color: var(--primary-text-color, #212121);
  }
  .modal-body {
    padding: 16px 20px;
    overflow-y: auto;
    flex: 1;
  }
  .modal-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    padding: 12px 20px;
    border-top: 1px solid var(--divider-color, rgba(0,0,0,0.12));
  }
  .modal-footer-right {
    display: flex;
    gap: 8px;
    margin-left: auto;
  }
  .modal-btn {
    font-family: inherit;
    font-size: 14px;
    padding: 8px 16px;
    border-radius: 6px;
    cursor: pointer;
    border: 1px solid transparent;
  }
  .modal-btn:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .modal-btn-secondary {
    background: transparent;
    border-color: var(--divider-color, rgba(0,0,0,0.2));
    color: var(--primary-text-color, #212121);
  }
  .modal-btn-secondary:hover:not(:disabled) {
    background: var(--secondary-background-color, #f5f5f5);
  }
  .modal-btn-primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }
  .modal-btn-primary:hover:not(:disabled) {
    filter: brightness(0.92);
  }
  .modal-btn-danger {
    background: transparent;
    border-color: var(--error-color, #f44336);
    color: var(--error-color, #f44336);
  }
  .modal-btn-danger:hover:not(:disabled) {
    background: var(--error-color, #f44336);
    color: var(--text-primary-color, #fff);
  }
  .modal-error-banner {
    margin: 12px 20px 0;
    padding: 10px 12px;
    border-radius: 6px;
    background: rgba(244, 67, 54, 0.12);
    color: var(--error-color, #f44336);
    font-size: 13px;
  }
  .modal-error-detail {
    margin-top: 6px;
    font-family: var(--code-font-family, ui-monospace, monospace);
    font-size: 11px;
    opacity: 0.85;
    word-break: break-word;
  }
  .form-section {
    margin-bottom: 18px;
  }
  .form-section-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--secondary-text-color, #727272);
    margin: 0 0 8px;
  }
  .form-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 10px;
  }
  .form-row {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }
  .form-row > .form-field {
    flex: 1 1 140px;
  }
  /* Phase 4B: prescription rows in the Add/Edit main modal. */
  .prescription-empty {
    padding: 12px;
    background: var(--secondary-background-color, rgba(0,0,0,0.04));
    border-radius: 6px;
    font-size: 13px;
    color: var(--secondary-text-color, #727272);
    margin-bottom: 8px;
  }
  .prescription-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 12px;
  }
  .prescription-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px;
    background: var(--secondary-background-color, rgba(0,0,0,0.03));
    border: 1px solid var(--divider-color, rgba(0,0,0,0.08));
    border-radius: 8px;
  }
  .prescription-row-error {
    border-color: var(--error-color, #f44336);
    background: rgba(244, 67, 54, 0.08);
  }
  .prescription-summary {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1 1 auto;
    min-width: 0;
  }
  .prescription-person {
    font-weight: 500;
    font-size: 14px;
  }
  .prescription-detail {
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
  }
  .prescription-errors {
    font-size: 12px;
    color: var(--error-color, #f44336);
    margin-top: 4px;
  }
  .prescription-row-actions {
    display: flex;
    gap: 6px;
    flex-shrink: 0;
  }
  .add-prescription-btn {
    width: 100%;
    margin-top: 4px;
  }
  /* Sub-modal: stacks above the parent main modal. Same look, slightly
     darker backdrop, narrower card to feel like a focused dialog. */
  .sub-modal-overlay {
    z-index: 10001;
    background: rgba(0, 0, 0, 0.6);
  }
  .sub-modal-card {
    max-width: 540px;
  }
  .form-label {
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
  }
  .form-hint {
    font-size: 11px;
    color: var(--secondary-text-color, #727272);
    margin-top: 2px;
  }
  .form-input {
    font: inherit;
    font-size: 14px;
    padding: 8px 10px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    border-radius: 6px;
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color, #212121);
  }
  .form-input:focus {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: -1px;
  }
  .slider-with-input {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .slider-with-input .form-slider {
    /* Take all the leftover horizontal space; mobile-friendly drag
       target. The native range input picks up HA's accent color from
       --primary-color via accent-color. */
    flex: 1;
    min-width: 0;
    accent-color: var(--primary-color, #03a9f4);
    cursor: pointer;
  }
  .slider-with-input .slider-number {
    /* Compact number input on the right — wide enough for 3 digits
       plus the spinner controls. Tap target stays comfortable on
       mobile because of inherent input height (~36px). */
    flex: 0 0 70px;
    text-align: right;
  }
  .slider-with-input .slider-unit {
    flex: 0 0 auto;
    color: var(--secondary-text-color, #727272);
    font-size: 13px;
  }
  .field-error {
    font-size: 12px;
    color: var(--error-color, #f44336);
  }
  /* v0.2.12: catalog variants hint inside the Add/Edit medicine
     modal. Read-only — shows the strength/form combos
     Läkemedelsverket has for the picked medicine so the user can
     pick a real value when typing the free-text Strength field. */
  .catalog-variants-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
  }
  .catalog-variants-list li {
    font-size: 13px;
    padding: 3px 8px;
    border-radius: 10px;
    background: var(--secondary-background-color, rgba(127,127,127,0.12));
    color: var(--primary-text-color, inherit);
  }
  /* v0.2.0-beta3.6 weekday chip selector + presets. Replaces the
     beta3 .day-checkboxes UI — same data model (draft.daysOfWeek
     Set of "0".."6"), better UX (one-tap presets for the common
     cases, chip buttons in place of 7 checkbox rectangles). */
  .weekday-presets {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }
  .weekday-preset-btn {
    padding: 4px 10px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    border-radius: 12px;
    background: transparent;
    color: var(--secondary-text-color, #666);
    font-size: 12px;
    cursor: pointer;
    font-family: inherit;
  }
  .weekday-preset-btn.active {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, white);
    border-color: var(--primary-color, #03a9f4);
  }
  .weekday-preset-btn:hover:not(.active) {
    background: var(--secondary-background-color, rgba(0,0,0,0.05));
  }
  .weekday-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .weekday-chip {
    padding: 6px 12px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    border-radius: 16px;
    background: transparent;
    color: var(--secondary-text-color, #666);
    font-size: 13px;
    cursor: pointer;
    font-family: inherit;
    min-width: 44px;
    text-align: center;
  }
  .weekday-chip.active {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, white);
    border-color: var(--primary-color, #03a9f4);
    font-weight: 500;
  }
  .weekday-chip:hover:not(.active) {
    background: var(--secondary-background-color, rgba(0,0,0,0.05));
  }

  /* v0.2.0-beta3.5 times-mode picker (radios). Replaces the
     beta3 .per-weekday-toggle checkbox UI — same data model
     (draft.usePerWeekday boolean), better UX (one source of
     truth for the times input shape). */
  .times-mode-picker {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .times-mode-picker .radio-option {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-size: 14px;
  }
  .times-mode-picker .radio-option input[type="radio"] {
    margin: 0;
    cursor: pointer;
  }
  .per-weekday-rows {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 12px;
    border-left: 2px solid var(--divider-color, rgba(0,0,0,0.2));
    margin-left: 4px;
  }
  .weekday-row {
    display: grid;
    grid-template-columns: 48px 1fr;
    align-items: center;
    gap: 8px;
  }
  .weekday-label {
    font-weight: 500;
    font-size: 13px;
    color: var(--secondary-text-color, #555);
  }
  .weekday-input {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px;
  }

  @media (max-width: 720px) {
    /* On phones the table layout doesn't fit. Collapse the parent grid
       to a 2-column layout (name+status top line, edit button in its
       own column on the right) and let metadata cells wrap to full
       width. Subgrid still works — children inherit whatever the
       parent declares. */
    .med-list {
      grid-template-columns: 1fr auto;
    }
    .med-list-row > .med-list-meta { grid-column: 1 / -1; }
    .med-list-row > *:nth-child(2),
    .med-list-row > *:nth-child(5) {
      justify-self: start;
      text-align: left;
    }
  }
  .med-card {
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    border-radius: 12px;
    padding: 16px;
  }
  .med-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
    gap: 8px;
  }
  .med-name { font-weight: 500; }
  .med-dose {
    font-size: 13px;
    color: var(--secondary-text-color, #727272);
    margin-bottom: 12px;
  }
  .med-meta {
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
    line-height: 1.6;
  }
  .med-note {
    font-size: 12px;
    color: var(--primary-text-color, #212121);
    margin-top: 8px;
    padding: 8px 10px;
    background: var(--secondary-background-color, #f5f5f5);
    border-radius: 6px;
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .med-footer {
    display: flex;
    justify-content: flex-end;
    margin-top: 10px;
  }
  .med-edit-btn {
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.2));
    background: transparent;
    color: var(--secondary-text-color, #727272);
    cursor: pointer;
    font-family: inherit;
  }
  .med-edit-btn:hover {
    background: var(--secondary-background-color, #f5f5f5);
    color: var(--primary-text-color, #212121);
  }
  .pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 500;
    white-space: nowrap;
  }
  .pill-success { background: var(--success-color, #4caf50); color: #fff; }
  .pill-warning { background: var(--warning-color, #ff9800); color: #fff; }
  .pill-error   { background: var(--error-color,   #f44336); color: #fff; }
  .pill-info    { background: var(--info-color,    #03a9f4); color: #fff; }
  .pill-neutral {
    background: var(--secondary-background-color, #eee);
    color: var(--secondary-text-color, #727272);
  }
  .empty {
    text-align: center;
    padding: 64px 24px;
    color: var(--secondary-text-color, #727272);
  }
  .empty-link {
    color: var(--primary-color, #03a9f4);
    text-decoration: none;
    font-weight: 500;
  }
  .empty-link:hover { text-decoration: underline; }
  @media (max-width: 600px) {
    .dose-row {
      grid-template-columns: 60px 1fr auto;
      grid-template-areas:
        "time name actions"
        "time person actions";
      row-gap: 4px;
    }
    .dose-time     { grid-area: time; }
    .dose-name     { grid-area: name; }
    .dose-person   { grid-area: person; }
    .dose-actions  { grid-area: actions; align-self: center; }
    .dose-detail   { display: none; }
  }
`;

class PillPilotPanel extends HTMLElement {
  constructor() {
    super();
    try {
      this.attachShadow({ mode: "open" });
      this._hass = null;
      this._lastSig = null;
      this._watchdogInterval = null;
      // Debug logging gate. Default off — keeps the browser console
      // quiet during normal use. Enable for an install by running
      // ``localStorage.setItem("pillpilot_debug", "1")`` in the
      // browser console and reloading; disable with ``removeItem``.
      // Used by the lifecycle log sites (constructor, connected,
      // disconnected, render, watchdog, visibilitychange). Warnings
      // and errors are never gated.
      this._debug = (() => {
        try {
          return localStorage.getItem("pillpilot_debug") === "1";
        } catch (_) {
          return false;
        }
      })();
      // per-person collapse state, persisted in localStorage.
      // Shape: { "person.alice": "expanded", "__household__": "collapsed", ... }
      // Missing keys fall back to the smart default (expanded if any
      // non-taken dose, collapsed if all taken).
      this._collapseState = this._loadCollapseState();
      // in-memory record of the most recent bulk action per
      // person, for the "Undo last action" kebab menu item. Each entry
      // is a list of {medicineId, scheduledAt} pairs that the bulk
      // call sent to mark_taken. Reset to null after Undo runs. NOT
      // persisted — page reload clears it (acceptable per spec).
      this._lastActionMap = {};
      // v0.2.14: optimistic overrides for dose slot status. Keyed by
      // `${medicineId}::${scheduledAt}`. Each value is
      // {status, actionAt?, snoozedUntil?}. Set immediately when the
      // user clicks Take/Skip/Snooze (or any of the bulk actions),
      // applied on top of slot data in _flattenTodayDoses so the
      // badge flips in the UI before the websocket round-trip
      // completes. Pruned in _flattenTodayDoses once the real slot
      // status already matches the override. Cleared by _unmarkTaken.
      this._optimisticOverrides = new Map();
      // cards-vs-list view mode for the medicines section,
      // persisted per-browser. Default = "cards" matching the
      // pre-v0.2.18 look. Set to "list" via the in-section toggle.
      this._medsView = this._loadMedsView();
      // medicines sort order, persisted per-browser.
      // _sortBy ∈ {"name", "status", "next", "last_taken"} —
      // _sortDir ∈ {"asc", "desc"}. Pre-v0.2.20 the panel rendered
      // medicines in whatever order Object.values(hass.states) returned,
      // which isn't guaranteed stable across HA state pushes — so the
      // list shuffled on every refresh. Default sort is name-ascending,
      // which matches user expectation and is deterministic.
      const sortLoaded = this._loadSortState();
      this._sortBy = sortLoaded.by;
      this._sortDir = sortLoaded.dir;
      // in-panel edit modal state. Null = closed; any other
      // value = the medicine_id being edited. _editFormDraft holds the
      // current form values as the user types so we can re-render the
      // modal without losing input. _editFormErrors maps field names
      // to translation keys returned by the backend on validation
      // failure. _editFormSaving prevents double-submits while the
      // websocket round-trip is in flight.
      //
      // Phase 4B: _addingMedicine is the equivalent flag for the new
      // Add modal (separate component but shares the same draft / errors /
      // saving state — only one main modal can be open at a time).
      // _personSubModal is the per-prescription sub-modal — opened from
      // either Add or Edit when the user clicks "+ Add prescription" or
      // "Edit" on a prescription row. Stacks above the parent modal.
      this._editingMedicineId = null;
      this._addingMedicine = false;
      this._editFormDraft = null;
      this._editFormErrors = {};
    this._editFormErrorDetail = null;
      // Optional human-readable string (typically `ExceptionType: msg`)
      // that the backend attaches under `error_detail` when something
      // unexpected blew up. Rendered under the friendly base error so
      // we can debug without hunting through HA logs.
      this._editFormErrorDetail = null;
      this._editFormSaving = false;
      this._personSubModal = null;
      // Cached medicines catalog from pillpilot/get_medicines_db. Used
      // by the Add/Edit modal's drug-name autocomplete and post-pick
      // auto-fill. Fetched lazily on the first hass set; null while in
      // flight, [] if the WS call ever resolves with an empty catalog
      // (e.g. integration not fully booted) or fails outright. Either
      // way the modal still works — it just falls back to suggesting
      // names from medicines you've already added.
      this._medicinesDb = null;
      this._medicinesDbFetchInFlight = false;
      this._onVisibilityChange = () => {
        if (!document.hidden) {
          if (this._debug) console.log("[PillPilot] visibilitychange → re-render");
          this._lastSig = null;
          this._render();
        }
      };
      // Close any open kebab menu when clicking outside it.
      this._onDocumentClick = (e) => {
        // Path-based check: if the click went through any element
        // marked data-kebab-stop or .kebab-wrapper, leave it alone.
        const path = e.composedPath ? e.composedPath() : [];
        const insideKebab = path.some((n) =>
          n && n.classList && n.classList.contains("kebab-wrapper")
        );
        if (!insideKebab) {
          this.shadowRoot
            ?.querySelectorAll(".kebab-menu.open")
            .forEach((m) => m.classList.remove("open"));
        }
      };
      // Escape closes whichever modal is on top. Sub-modal first if
      // both are open. Suppressed during save so users can't dismiss
      // a request that's already in flight (matches the disabled
      // Cancel button + backdrop guard).
      this._onKeydown = (e) => {
        if (e.key !== "Escape") return;
        if (this._editFormSaving) return;
        if (this._personSubModal) {
          this._closePrescriptionSubModal();
          e.preventDefault();
          return;
        }
        if (this._editingMedicineId) {
          this._closeEditModal();
          e.preventDefault();
          return;
        }
        if (this._addingMedicine) {
          this._closeAddModal();
          e.preventDefault();
        }
      };
      if (this._debug) console.log("[PillPilot] constructed");
    } catch (e) {
      console.error("[PillPilot] constructor failed:", e);
    }
  }

  _loadCollapseState() {
    try {
      const raw = localStorage.getItem("pillpilot:collapseState");
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  _saveCollapseState() {
    try {
      localStorage.setItem(
        "pillpilot:collapseState",
        JSON.stringify(this._collapseState)
      );
    } catch (e) {
      // localStorage might be disabled (privacy mode, quota) —
      // silently fall back to in-memory state. The user's per-person
      // expansion choices won't survive page reloads, but the UI keeps
      // working for the current session.
    }
  }

  _isPersonExpanded(personKey, hasNonTaken) {
    const stored = this._collapseState[personKey];
    if (stored === "expanded") return true;
    if (stored === "collapsed") return false;
    // No stored preference for this person yet → smart default.
    return hasNonTaken;
  }

  // cards-vs-list view mode for the bottom medicines section.
  // Persisted per-browser; falls back to "cards" (the pre-v0.2.18
  // default) if localStorage isn't usable or contains an unknown value.
  _loadMedsView() {
    try {
      const v = localStorage.getItem("pillpilot:medsView");
      return v === "list" ? "list" : "cards";
    } catch (e) {
      return "cards";
    }
  }

  _saveMedsView() {
    try {
      localStorage.setItem("pillpilot:medsView", this._medsView);
    } catch (e) {
      // localStorage disabled — just keep the in-memory choice.
    }
  }

  _setMedsView(view) {
    if (view !== "cards" && view !== "list") return;
    if (this._medsView === view) return;
    this._medsView = view;
    this._saveMedsView();
    this._lastSig = null;
    this._render();
  }

  // sort state load/save + deterministic sort helper.
  // Pre-v0.2.20 the medicines section rendered in whatever order
  // hass.states happened to be in — JS Object key iteration preserves
  // insertion order but HA's state store doesn't guarantee insertion
  // order is stable across reloads, so the cards/list shuffled on
  // every refresh. v0.2.20 always sorts before render.
  _loadSortState() {
    const VALID_BY = ["name", "status", "next", "last_taken"];
    const VALID_DIR = ["asc", "desc"];
    try {
      const raw = localStorage.getItem("pillpilot:medsSort");
      if (!raw) return { by: "name", dir: "asc" };
      const parsed = JSON.parse(raw);
      return {
        by: VALID_BY.includes(parsed.by) ? parsed.by : "name",
        dir: VALID_DIR.includes(parsed.dir) ? parsed.dir : "asc",
      };
    } catch (e) {
      return { by: "name", dir: "asc" };
    }
  }

  _saveSortState() {
    try {
      localStorage.setItem(
        "pillpilot:medsSort",
        JSON.stringify({ by: this._sortBy, dir: this._sortDir })
      );
    } catch (e) {
      // localStorage disabled — keep in-memory choice for the session.
    }
  }

  // Click handler for the card-view dropdown. Value is encoded as
  // "by:dir" (e.g. "name:asc", "last_taken:desc") — keeps the dropdown
  // a single control instead of two.
  _setSort(value) {
    if (typeof value !== "string") return;
    const [by, dir] = value.split(":");
    if (!by || !dir) return;
    this._sortBy = by;
    this._sortDir = dir;
    this._saveSortState();
    this._lastSig = null;
    this._render();
  }

  // Click handler for list-view column headers. Same column → flip
  // direction; different column → switch column, reset to ascending
  // (matches every spreadsheet-style sort users have ever used).
  _toggleSort(by) {
    if (this._sortBy === by) {
      this._sortDir = this._sortDir === "asc" ? "desc" : "asc";
    } else {
      this._sortBy = by;
      this._sortDir = "asc";
    }
    this._saveSortState();
    this._lastSig = null;
    this._render();
  }

  // Map state strings to a priority order for status sort.
  // Lowest = first when ascending: due > missed > snoozed > upcoming > taken > skipped.
  // The "due first" reading users expect.
  _statePriority(state) {
    switch (state) {
      case STATE_DUE: return 0;
      case STATE_MISSED: return 1;
      case STATE_SNOOZED: return 2;
      case STATE_UPCOMING: return 3;
      case STATE_TAKEN: return 4;
      case STATE_SKIPPED: return 5;
      default: return 6;
    }
  }

  _sortKey(item) {
    // Item is a {med, prescription} pair. Name is medicine-level
    // (shared across prescriptions), state/dose-time fields are per-
    // prescription so the same medicine can appear at different
    // positions for different people.
    const a = item.med.attributes;
    const p = item.prescription;
    switch (this._sortBy) {
      case "name":
        return (a.medicine_name || a.friendly_name || item.med.entity_id || "").toLowerCase();
      case "status":
        return this._statePriority(p.state);
      case "next":
        // Null next_dose_at sorts last in ascending. Use a sentinel
        // string that's lexically greater than any ISO timestamp.
        return p.next_dose_at || "9999-12-31T23:59:59";
      case "last_taken":
        // Never-taken sorts last in descending (most-recent-first).
        // Use empty string — lexically smaller than any ISO timestamp.
        return p.last_taken_at || "";
      default:
        return (a.medicine_name || "").toLowerCase();
    }
  }

  _sortItems(items) {
    const dir = this._sortDir === "desc" ? -1 : 1;
    const sorted = [...items];
    sorted.sort((a, b) => {
      const av = this._sortKey(a);
      const bv = this._sortKey(b);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      // Stable secondary sort by name then prescription id so ties
      // don't shuffle.
      const an = (a.med.attributes.medicine_name || "").toLowerCase();
      const bn = (b.med.attributes.medicine_name || "").toLowerCase();
      const byName = an.localeCompare(bn);
      if (byName !== 0) return byName;
      return (a.prescription.id || "").localeCompare(b.prescription.id || "");
    });
    return sorted;
  }

  // Detects whether our content container is currently in the shadow DOM.
  // Used by the hass setter, visibilitychange handler, and watchdog to
  // notice when something has stripped our content. Looks for `.container`
  // specifically (not `firstChild`) — the v0.2.7 fix used `firstChild`
  // which still returned truthy when the `<style>` tag survived but the
  // content was gone, so re-renders never fired.
  _hasRenderedContent() {
    return !!this.shadowRoot.querySelector(".container");
  }

  set hass(value) {
    this._hass = value;
    // Fire-and-forget catalog fetch the first time we see hass. The
    // panel renders fine without it (datalist falls back to empty);
    // when it lands, the next render picks it up.
    this._ensureMedicinesDb();
    // Don't re-render while any modal is open. A re-render would
    // replace innerHTML, blowing away the form inputs the user is
    // filling out. Modals are dismissed on save/cancel, at which point
    // we re-render normally with fresh data.
    if (
      this._editingMedicineId ||
      this._addingMedicine ||
      this._personSubModal
    ) {
      return;
    }
    const sig = this._signature();
    if (sig !== this._lastSig || !this._hasRenderedContent()) {
      this._lastSig = sig;
      this._render();
    }
  }
  get hass() {
    return this._hass;
  }

  set narrow(_) {}
  set panel(_) {}

  connectedCallback() {
    if (this._debug) console.log("[PillPilot] connected");
    // Always render something on connect, even without hass. The element
    // can be mounted before HA pushes its first state — without this,
    // the user sees a blank panel until that first push lands.
    this._render();

    // Watchdog: poll every 3s and re-render if content missing.
    // Runs unconditionally (no hass guard) — even the loading state
    // benefits from being kept visible.
    this._watchdogInterval = setInterval(() => {
      if (!this._hasRenderedContent()) {
        if (this._debug) console.log("[PillPilot] watchdog: content missing → re-render");
        this._lastSig = null;
        this._render();
      }
    }, 3000);

    document.addEventListener("visibilitychange", this._onVisibilityChange);
    document.addEventListener("click", this._onDocumentClick);
    document.addEventListener("keydown", this._onKeydown);
  }

  disconnectedCallback() {
    if (this._debug) console.log("[PillPilot] disconnected");
    if (this._watchdogInterval) {
      clearInterval(this._watchdogInterval);
      this._watchdogInterval = null;
    }
    document.removeEventListener("visibilitychange", this._onVisibilityChange);
    document.removeEventListener("click", this._onDocumentClick);
    document.removeEventListener("keydown", this._onKeydown);
  }

  // --- data --------------------------------------------------------------

  _getMedicines() {
    if (!this._hass || !this._hass.states) return [];
    // v0.2.15: cache per hass.states reference. HA replaces the
    // states object on every entity change, so the reference
    // check is a correct invalidator — and across a single render
    // cycle (`_signature`, `_renderFull`, `_findPersonGroup`) we
    // walk the entity table once instead of three or four times.
    if (this._cachedMedicinesFor === this._hass.states) {
      return this._cachedMedicines;
    }
    this._cachedMedicines = Object.values(this._hass.states).filter(
      (s) =>
        s.entity_id.startsWith("sensor.") &&
        s.attributes &&
        s.attributes.medicine_id !== undefined
    );
    this._cachedMedicinesFor = this._hass.states;
    return this._cachedMedicines;
  }

  // --- medicines DB cache (drug-name autocomplete) ----------------------
  //
  // Populated lazily by a single websocket call to
  // ``pillpilot/get_medicines_db``. The catalog is small (~250 entries)
  // and rarely changes, so a one-shot fetch + cache for the lifetime
  // of this panel instance is plenty. If the user runs the
  // ``pillpilot.refresh_medicines_database`` service, they'll see the
  // new entries on next browser reload — acceptable trade-off versus
  // a polling refresh.

  _ensureMedicinesDb() {
    if (this._medicinesDb !== null) return;
    if (this._medicinesDbFetchInFlight) return;
    if (!this._hass || typeof this._hass.callWS !== "function") return;
    this._medicinesDbFetchInFlight = true;
    this._hass
      .callWS({ type: "pillpilot/get_medicines_db" })
      .then((res) => {
        this._medicinesDb =
          (res && Array.isArray(res.medicines)) ? res.medicines : [];
        this._medicinesDbFetchInFlight = false;
        // If a modal is open when the cache lands, refresh the
        // datalist contents in place. A full re-render would wipe
        // the user's in-progress form state (innerHTML replace);
        // surgical option-list update keeps everything else intact
        // and the browser picks up the new options on next focus.
        this._refreshOpenModalDatalist();
      })
      .catch((err) => {
        console.warn("[PillPilot] get_medicines_db failed:", err);
        this._medicinesDb = [];
        this._medicinesDbFetchInFlight = false;
      });
  }

  // Surgically replace the <option> children of the medicine-name
  // datalist (if a modal containing it is open). Used to backfill
  // autocomplete after the catalog WS call resolves later than the
  // modal opening — the original race where users saw empty
  // autocomplete on first panel load.
  _refreshOpenModalDatalist() {
    if (!this.shadowRoot) return;
    const list = this.shadowRoot.getElementById("pp-edit-name-list");
    if (!list) return;
    const existingNames = this._getMedicines().map(
      (m) => m.attributes.medicine_name || ""
    );
    const optionsHtml = this._buildNameOptions(existingNames)
      .map((o) => {
        if (o.label === o.value) {
          return `<option value="${escapeHtml(o.value)}"></option>`;
        }
        return `<option value="${escapeHtml(o.value)}" label="${escapeHtml(o.label)}"></option>`;
      })
      .join("");
    list.innerHTML = optionsHtml;
  }

  // Build the <option> rows for the drug-name datalist. Brand names
  // come first; aliases come second with a label hint pointing back to
  // the brand; existing-sensor names come last (in case the user has a
  // custom medicine not in the catalog). Brand-name match always wins
  // over a colliding alias — see _lookupMedNameOrAlias for the
  // matching counterpart.
  _buildNameOptions(existingSensorNames) {
    const db = Array.isArray(this._medicinesDb) ? this._medicinesDb : [];
    const seen = new Set();
    const opts = [];
    for (const m of db) {
      const brand = (m.name || "").trim();
      if (!brand) continue;
      if (seen.has(brand.toLowerCase())) continue;
      seen.add(brand.toLowerCase());
      opts.push({ value: brand, label: brand });
    }
    for (const m of db) {
      const brand = (m.name || "").trim();
      for (const alias of m.aliases || []) {
        const a = (alias || "").trim();
        if (!a) continue;
        if (seen.has(a.toLowerCase())) continue;
        seen.add(a.toLowerCase());
        opts.push({ value: a, label: `${a} → ${brand}` });
      }
    }
    for (const name of existingSensorNames || []) {
      const n = (name || "").trim();
      if (!n) continue;
      if (seen.has(n.toLowerCase())) continue;
      seen.add(n.toLowerCase());
      opts.push({ value: n, label: n });
    }
    return opts;
  }

  // Resolve a typed name or alias to the canonical catalog entry.
  // Brand match wins (avoids surprise auto-renames when a generic name
  // like "Paracetamol" is also listed as an alias for a brand).
  _lookupMedNameOrAlias(query) {
    if (!query) return null;
    const needle = String(query).trim().toLowerCase();
    if (!needle) return null;
    const db = Array.isArray(this._medicinesDb) ? this._medicinesDb : [];
    for (const m of db) {
      if ((m.name || "").toLowerCase() === needle) return m;
    }
    for (const m of db) {
      for (const alias of m.aliases || []) {
        if ((alias || "").toLowerCase() === needle) return m;
      }
    }
    return null;
  }

  // Apply auto-fill to the Add/Edit draft based on a typed-or-picked
  // value in the drug-name field. Fills empty atc_code + npl_id + notes
  // from the matched catalog entry; never overwrites user-entered values.
  // Returns true if anything in the draft changed (caller decides
  // whether to re-render).
  _applyDrugNameAutoFill(typedValue) {
    if (!this._editFormDraft || !this._editFormDraft.drug) return false;
    const draft = this._editFormDraft;
    const hit = this._lookupMedNameOrAlias(typedValue);
    if (!hit) {
      // Unknown / free-text: just keep the typed value (the input
      // listener already wrote it). No auto-fill.
      return false;
    }
    let changed = false;
    if (draft.drug.name !== hit.name) {
      draft.drug.name = hit.name;
      changed = true;
    }
    const userAtc = (draft.drug.atc_code || "").trim();
    if (!userAtc && hit.atc_code) {
      draft.drug.atc_code = hit.atc_code;
      changed = true;
    }
    const userNpl = (draft.drug.npl_id || "").trim();
    if (!userNpl && hit.npl_id) {
      draft.drug.npl_id = hit.npl_id;
      changed = true;
    }
    const userNotes = (draft.drug.notes || "").trim();
    if (!userNotes && hit.active_substance) {
      draft.drug.notes = `Aktiv substans: ${hit.active_substance}`;
      changed = true;
    }
    return changed;
  }

  _signature() {
    if (!this._hass || !this._hass.states) return "";
    const meds = this._getMedicines();
    const parts = [];
    for (const m of meds) {
      const a = m.attributes;
      const prescriptions = a.prescriptions || [];
      // One signature line per (medicine, prescription) pair so changes
      // to prescriptions[1+] also fire a re-render. Drug-level fields
      // (med_type, atc_code) are repeated in each line — slightly
      // wasteful but ensures edits to drug identity still bump the
      // signature even when prescription state is unchanged.
      for (const p of prescriptions) {
        const td = (p.today_doses || [])
          .map((d) => `${d.time}:${d.status}:${d.action_at || ""}:${d.snoozed_until || ""}`)
          .join(",");
        parts.push([
          m.entity_id,
          p.id || "",
          p.state || "",
          p.last_taken_at || "",
          p.next_dose_at || "",
          p.person_name || "",
          a.medicine_name || "",
          a.med_type || "",
          a.atc_code || "",
          p.dose || "",
          a.notes || "",
          td,
        ].join(":"));
      }
    }
    return parts.sort().join("|");
  }

  // Build a flat list of every today-dose-slot across all medicines &
  // prescriptions, sorted by scheduled time. Each entry carries enough
  // context for a row + a service call (including person_id so the
  // service can route to the right prescription).
  _flattenTodayDoses(meds) {
    const out = [];
    const ov = this._optimisticOverrides;
    const now = Date.now();
    for (const med of meds) {
      const a = med.attributes;
      const name = a.medicine_name || a.friendly_name || med.entity_id;
      const medId = a.medicine_id;
      const prescriptions = a.prescriptions || [];
      for (const p of prescriptions) {
        const slots = p.today_doses || [];
        for (const slot of slots) {
          const key = `${medId}::${slot.scheduled_at}`;
          // v0.2.14: prune overrides that the real state has caught
          // up with (statuses match), then apply any remaining
          // override on top of the slot data. This makes Take /
          // Skip / Snooze feel instant — the badge flips on click,
          // no waiting for the WS round-trip — and the override
          // disappears as soon as the backend's view of the slot
          // matches.
          // v0.2.15: TTL prune. If the override is older than 60s
          // and the real state still hasn't caught up, the backend
          // probably dropped the call silently — let the real
          // status win so the badge stops lying.
          const override = ov.get(key);
          if (override) {
            if (slot.status === override.status) {
              ov.delete(key);
            } else if (override.ts && now - override.ts > 60000) {
              ov.delete(key);
            }
          }
          const effOverride = ov.get(key);
          const effective = (effOverride && slot.status !== effOverride.status)
            ? { ...slot, status: effOverride.status,
                action_at: effOverride.actionAt || slot.action_at,
                snoozed_until: effOverride.snoozedUntil || slot.snoozed_until }
            : slot;
          out.push({
            scheduledAt: effective.scheduled_at,
            time: effective.time,
            status: effective.status,
            actionAt: effective.action_at,
            snoozedUntil: effective.snoozed_until || null,
            name,
            dose: p.dose || "",
            personName: p.person_name || null,
            personId: p.person_id || null,
            medicineId: medId,
            prescriptionId: p.id || "",
          });
        }
      }
    }
    return out.sort((a, b) =>
      (a.scheduledAt || a.time).localeCompare(b.scheduledAt || b.time)
    );
  }

  // per-person grouping for the new collapsible Today's
  // doses sections. Returns groups in stable order — named persons
  // alphabetically first, "Household" last (and only when it has any
  // doses; otherwise omitted entirely).
  _groupTodayDosesByPerson(meds) {
    const groups = new Map();
    for (const dose of this._flattenTodayDoses(meds)) {
      const personKey = dose.personId || "__household__";
      const personName =
        dose.personName ||
        (personKey === "__household__" ? "Household" : "Unnamed");
      if (!groups.has(personKey)) {
        groups.set(personKey, { personKey, personName, doses: [] });
      }
      groups.get(personKey).doses.push(dose);
    }
    // Each person's doses are already time-sorted by _flattenTodayDoses;
    // we only need to order the GROUPS themselves.
    return Array.from(groups.values()).sort((a, b) => {
      if (a.personKey === "__household__") return 1;
      if (b.personKey === "__household__") return -1;
      return a.personName.localeCompare(b.personName);
    });
  }

  // Expand a list of medicines into a flat list of {med, prescription}
  // pairs — one entry per prescription on each medicine. Medicines with
  // zero prescriptions are skipped (defensive; shouldn't happen with
  // the v0.1.0+ schema). This is the iteration unit for cards, list
  // rows, and grouping — Phase 3 of the multi-prescription work.
  _expandToCardItems(meds) {
    const out = [];
    for (const med of meds) {
      const prescriptions = med.attributes.prescriptions || [];
      if (prescriptions.length === 0) continue;
      for (const prescription of prescriptions) {
        out.push({ med, prescription });
      }
    }
    return out;
  }

  _groupByPerson(meds) {
    // Refactored for Phase 3: groups (med, prescription) pairs by the
    // prescription's person_id, not the medicine's flat person_id.
    // Items are sorted internally per the user's selected sort —
    // _renderPersonSection no longer needs a separate sort pass.
    const items = this._expandToCardItems(meds);
    const sortedItems = this._sortItems(items);
    const groups = new Map();
    for (const item of sortedItems) {
      const personId = item.prescription.person_id || "__household__";
      const personName = item.prescription.person_name;
      if (!groups.has(personId)) {
        const isHousehold = personId === "__household__";
        groups.set(personId, {
          label: isHousehold
            ? "Household medicines"
            : `${personName || "Unnamed"}'s medicines`,
          items: [],
        });
      }
      groups.get(personId).items.push(item);
    }
    return Array.from(groups.entries()).sort(([aId, a], [bId, b]) => {
      if (aId === "__household__") return 1;
      if (bId === "__household__") return -1;
      return a.label.localeCompare(b.label);
    });
  }

  // --- formatting --------------------------------------------------------

  _formatDate(d) {
    return d.toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
  }

  _formatRelative(isoStr) {
    if (!isoStr) return "never";
    const dt = new Date(isoStr);
    if (isNaN(dt.getTime())) return "—";
    const diffMs = Date.now() - dt.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days}d ago`;
    return dt.toLocaleDateString();
  }

  _formatActionTime(isoStr) {
    if (!isoStr) return "";
    const dt = new Date(isoStr);
    if (isNaN(dt.getTime())) return "";
    return dt.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: this._hour12FromHA(),
    });
  }

  // HA locale-aware HH:MM time formatter.
  // Pre-v0.2.19 we displayed "HH:MM" raw, which meant 24h regardless
  // of the user's HA frontend Time format setting (Profile → Time
  // format → 12 hour / 24 hour / Auto). This helper reads
  // ``hass.locale.time_format`` and respects it.
  //
  // Input: "HH:MM" (or "H:MM"). Output: locale-aware string like
  // "08:00", "5:30 PM", "17:30" depending on the user's preference.
  // Falls back to passing the input through unchanged if it can't
  // parse — never throws.
  _formatTime(hhmm) {
    if (!hhmm) return "";
    const parts = String(hhmm).split(":");
    if (parts.length < 2) return hhmm;
    const hours = parseInt(parts[0], 10);
    const minutes = parseInt(parts[1], 10);
    if (isNaN(hours) || isNaN(minutes)) return hhmm;
    const dt = new Date();
    dt.setHours(hours, minutes, 0, 0);
    try {
      return dt.toLocaleTimeString(undefined, {
        hour: "numeric",
        minute: "2-digit",
        hour12: this._hour12FromHA(),
      });
    } catch (e) {
      return hhmm;
    }
  }

  // Resolve the user's HA Time format preference into an Intl
  // ``hour12`` argument. HA's ``hass.locale.time_format`` can be:
  //   "12"       — force 12-hour
  //   "24"       — force 24-hour
  //   "language" — use the language's default
  //   "system"   — use the OS default
  // For "language" / "system" / unset we return ``undefined`` so the
  // Intl runtime picks based on the browser locale, matching HA-core's
  // own format-time helper behavior.
  _hour12FromHA() {
    const fmt = this._hass && this._hass.locale && this._hass.locale.time_format;
    if (fmt === "12") return true;
    if (fmt === "24") return false;
    return undefined;
  }

  // respect the medicine's actual frequency. Pre-v0.2.19 we
  // always rendered "Daily · ..." which mislabeled weekly and monthly
  // entries (e.g. an Ozempic prescribed Sunday-only would show as
  // Daily). The sensor now exposes ``frequency`` and
  // ``scheduled_days_of_month``; we read them here.
  _formatSchedule(attrs) {
    // ends_on (if set) appends " · until <date>" to the rest of the
    // summary regardless of frequency mode. Universal optional field.
    const endsSuffix = attrs.ends_on
      ? ` · until ${this._formatEndDate(attrs.ends_on)}`
      : "";

    // Times portion: when times_per_weekday is set, render a grouped
    // per-weekday string ("Mon-Fri 08:00 · Sat-Sun 10:00"). Otherwise
    // fall back to the flat scheduled_times list.
    const timesPart = this._formatTimesPart(attrs);
    if (timesPart === "—") return "—";

    const frequency = attrs.frequency || "weekly";
    if (frequency === "daily") {
      return `Daily · ${timesPart}${endsSuffix}`;
    }
    if (frequency === "weekly") {
      const days = attrs.scheduled_days || [];
      // Weekly with all 7 days OR with no days listed is functionally
      // daily — show it that way to avoid useless detail.
      if (days.length >= 7 || days.length === 0) {
        return `Daily · ${timesPart}${endsSuffix}`;
      }
      const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
      const dayList = [...days]
        .map((d) => parseInt(d, 10))
        .filter((d) => !isNaN(d) && d >= 0 && d <= 6)
        .sort((a, b) => a - b)
        .map((d) => labels[d])
        .join(", ");
      return `Weekly (${dayList}) · ${timesPart}${endsSuffix}`;
    }
    if (frequency === "monthly") {
      const dom = attrs.scheduled_days_of_month || [];
      if (dom.length === 0) {
        return `Monthly · ${timesPart}${endsSuffix}`;
      }
      const dayList = [...dom]
        .map((d) => parseInt(d, 10))
        .filter((d) => !isNaN(d) && d >= 1 && d <= 31)
        .sort((a, b) => a - b)
        .join(", ");
      return `Monthly (${dayList}) · ${timesPart}${endsSuffix}`;
    }
    if (frequency === "interval") {
      const n = parseInt(attrs.interval_days, 10);
      // For interval mode the start date is meaningful — it anchors
      // the every-N-day phase. Render it inline so the user can spot
      // a misaligned anchor at a glance ("Every 14 days from May 4").
      const fromSuffix = attrs.starts_on
        ? ` from ${this._formatEndDate(attrs.starts_on)}`
        : "";
      // Plain "Every N days" — N=2 reads more naturally as "every
      // other day" but stays explicit to avoid the user wondering
      // whether the math is off-by-one.
      if (Number.isFinite(n) && n >= 2) {
        return `Every ${n} days${fromSuffix} · ${timesPart}${endsSuffix}`;
      }
      return `Every N days${fromSuffix} · ${timesPart}${endsSuffix}`;
    }
    return `${timesPart}${endsSuffix}`;
  }

  // Render the times portion of a schedule summary. When per-weekday
  // overrides exist, group consecutive same-time weekdays into ranges
  // ("Mon-Fri 08:00 · Sat-Sun 10:00"); empty days appear as "(skip)".
  // When no override, flatten the scheduled_times list as before.
  _formatTimesPart(attrs) {
    const tpw = attrs.times_per_weekday;
    if (Array.isArray(tpw) && tpw.length === 7) {
      return this._formatPerWeekdayTimes(tpw);
    }
    const times = attrs.scheduled_times || [];
    if (times.length === 0) return "—";
    return times.map((t) => this._formatTime(t)).join(" / ");
  }

  // Group runs of consecutive weekdays with identical times into
  // ranges. Accepts either an array of arrays (sensor shape) or
  // an array of comma-strings (draft shape) — normalizes both.
  _formatPerWeekdayTimes(tpw) {
    const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    // Normalize each entry to a stable key string: "08:00 / 20:00"
    // for matching, with empty entries as "" (= skip-day).
    const norm = tpw.map((entry) => {
      let parts = [];
      if (Array.isArray(entry)) {
        parts = entry;
      } else if (typeof entry === "string") {
        parts = entry.split(",").map((s) => s.trim()).filter(Boolean);
      }
      return parts.map((t) => this._formatTime(t)).join(" / ");
    });
    // Find runs of consecutive equal entries.
    const groups = [];
    let runStart = 0;
    for (let i = 1; i <= 7; i++) {
      if (i === 7 || norm[i] !== norm[runStart]) {
        groups.push({ start: runStart, end: i - 1, times: norm[runStart] });
        runStart = i;
      }
    }
    return groups
      .map((g) => {
        const dayLabel = g.start === g.end
          ? labels[g.start]
          : `${labels[g.start]}-${labels[g.end]}`;
        if (!g.times) return `${dayLabel} (skip)`;
        return `${dayLabel} ${g.times}`;
      })
      .join(" · ");
  }

  // Format an ISO date ("YYYY-MM-DD") for the schedule summary line.
  // Falls back to the raw string for inputs we don't recognize.
  _formatEndDate(iso) {
    if (!iso || typeof iso !== "string") return String(iso || "");
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return iso;
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    const monthIdx = parseInt(m[2], 10) - 1;
    if (monthIdx < 0 || monthIdx > 11) return iso;
    return `${months[monthIdx]} ${parseInt(m[3], 10)}, ${m[1]}`;
  }

  // --- actions -----------------------------------------------------------

  _markTaken(medicineId, scheduledAt) {
    if (!medicineId || !this._hass) return;
    if (scheduledAt) {
      // v0.2.14: optimistic — paint the slot taken before the WS
      // round-trip completes. _flattenTodayDoses overlays this onto
      // the slot data until the real state catches up.
      // v0.2.15: ts for TTL; the override drops on its own after
      // 60s if real state never catches up (silent backend failure).
      this._optimisticOverrides.set(
        `${medicineId}::${scheduledAt}`,
        { status: STATE_TAKEN, actionAt: new Date().toISOString(), ts: Date.now() }
      );
      if (!this._bulkInProgress) {
        this._lastSig = null;
        this._render();
      }
    }
    const data = { medicine_id: medicineId };
    if (scheduledAt) data.scheduled_for = scheduledAt;
    this._hass.callService("pillpilot", "mark_taken", data);
  }

  _skip(medicineId, scheduledAt) {
    if (!medicineId || !this._hass) return;
    if (scheduledAt) {
      this._optimisticOverrides.set(
        `${medicineId}::${scheduledAt}`,
        { status: STATE_SKIPPED, actionAt: new Date().toISOString(), ts: Date.now() }
      );
      if (!this._bulkInProgress) {
        this._lastSig = null;
        this._render();
      }
    }
    const data = { medicine_id: medicineId };
    if (scheduledAt) data.scheduled_for = scheduledAt;
    this._hass.callService("pillpilot", "skip", data);
  }

  // Default snooze duration matches the notification's "Snooze 15m"
  // button so the row, the bulk actions, and the mobile_app payload
  // all push doses out by the same amount.
  _snooze(medicineId, scheduledAt, minutes = 15) {
    if (!medicineId || !this._hass) return;
    if (scheduledAt) {
      const snoozedUntil = new Date(Date.now() + minutes * 60 * 1000).toISOString();
      this._optimisticOverrides.set(
        `${medicineId}::${scheduledAt}`,
        { status: STATE_SNOOZED, snoozedUntil, ts: Date.now() }
      );
      if (!this._bulkInProgress) {
        this._lastSig = null;
        this._render();
      }
    }
    const data = { medicine_id: medicineId, minutes };
    if (scheduledAt) data.scheduled_for = scheduledAt;
    this._hass.callService("pillpilot", "snooze", data);
  }

  // per-dose undo (hover on green Taken badge → button)
  // and per-person bulk undo (kebab menu → Undo last action).
  // Both call the new pillpilot.unmark_taken service backed by
  // MedicineCoordinator.async_unmark_taken.
  _unmarkTaken(medicineId, scheduledAt) {
    if (!medicineId || !this._hass) return;
    if (scheduledAt) {
      // v0.2.14: clear any optimistic override so the real state
      // (which the backend is about to revert) is what we render.
      this._optimisticOverrides.delete(`${medicineId}::${scheduledAt}`);
      if (!this._bulkInProgress) {
        this._lastSig = null;
        this._render();
      }
    }
    const data = { medicine_id: medicineId };
    if (scheduledAt) data.scheduled_for = scheduledAt;
    this._hass.callService("pillpilot", "unmark_taken", data);
  }

  // v0.2.11: one-shot catalog backfill across all configured medicines.
  // Wraps the pillpilot.backfill_from_catalog service. Fire-and-toast —
  // the service handler logs the per-entry count, the toast just signals
  // completion. Failures are surfaced inline.
  _backfillFromCatalog() {
    if (!this._hass) return;
    this._toggleKebab("global");
    this._hass
      .callService("pillpilot", "backfill_from_catalog", {})
      .then(() => {
        this._toast(
          "Backfill complete — check Settings → System → Logs for the count."
        );
      })
      .catch((err) => {
        const msg = err && err.message ? err.message : String(err);
        this._toast(`Backfill failed: ${msg}`);
      });
  }

  // Fires the HA frontend's built-in toast.
  _toast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", {
        detail: { message },
        bubbles: true,
        composed: true,
      })
    );
  }

  // Bulk action helpers — each scopes to a single person's doses.
  // The kebab menu's "Undo last action" walks _lastActionMap[personKey]
  // back through unmark_taken, so each helper records what it sent.
  _executeBulkForPerson(personKey, doses) {
    if (!doses.length) return;
    this._lastActionMap[personKey] = doses.map((d) => ({
      medicineId: d.medicineId,
      scheduledAt: d.scheduledAt,
    }));
    // v0.2.15: batch the optimistic renders. Each _markTaken sets
    // its own override but skips its inline render while the flag
    // is on; we render once at the end. For "Take all" on 10 doses
    // that's 1 render instead of 11.
    this._bulkInProgress = true;
    try {
      for (const d of doses) {
        this._markTaken(d.medicineId, d.scheduledAt);
      }
    } finally {
      this._bulkInProgress = false;
    }
    this._lastSig = null;
    this._render();
  }

  _takeAllForPerson(personKey) {
    const group = this._findPersonGroup(personKey);
    if (!group) return;
    // "Take all today" = every dose today not yet acted on. Covers
    // due + upcoming + missed + snoozed. Excludes taken and skipped.
    // Snoozed is included because the bulk action represents an
    // explicit user override of any prior snooze.
    const targets = group.doses.filter(
      (d) =>
        d.status === STATE_DUE ||
        d.status === STATE_UPCOMING ||
        d.status === STATE_MISSED ||
        d.status === STATE_SNOOZED
    );
    this._executeBulkForPerson(personKey, targets);
  }

  _takeDueForPerson(personKey) {
    const group = this._findPersonGroup(personKey);
    if (!group) return;
    const targets = group.doses.filter((d) => d.status === STATE_DUE);
    this._executeBulkForPerson(personKey, targets);
  }

  _takeMissedForPerson(personKey) {
    const group = this._findPersonGroup(personKey);
    if (!group) return;
    const targets = group.doses.filter((d) => d.status === STATE_MISSED);
    this._executeBulkForPerson(personKey, targets);
  }

  _snoozeAllDueForPerson(personKey) {
    const group = this._findPersonGroup(personKey);
    if (!group) return;
    const targets = group.doses.filter((d) => d.status === STATE_DUE);
    this._bulkInProgress = true;
    try {
      for (const d of targets) {
        this._snooze(d.medicineId, d.scheduledAt);
      }
    } finally {
      this._bulkInProgress = false;
    }
    this._lastSig = null;
    this._render();
  }

  _snoozeAllMissedForPerson(personKey) {
    const group = this._findPersonGroup(personKey);
    if (!group) return;
    const targets = group.doses.filter((d) => d.status === STATE_MISSED);
    this._bulkInProgress = true;
    try {
      for (const d of targets) {
        this._snooze(d.medicineId, d.scheduledAt);
      }
    } finally {
      this._bulkInProgress = false;
    }
    this._lastSig = null;
    this._render();
  }

  _undoLastForPerson(personKey) {
    const records = this._lastActionMap[personKey] || [];
    this._bulkInProgress = true;
    try {
      for (const r of records) {
        this._unmarkTaken(r.medicineId, r.scheduledAt);
      }
    } finally {
      this._bulkInProgress = false;
    }
    this._lastActionMap[personKey] = null;
    this._lastSig = null;
    this._render();
  }

  _findPersonGroup(personKey) {
    const groups = this._groupTodayDosesByPerson(this._getMedicines());
    return groups.find((g) => g.personKey === personKey) || null;
  }

  _togglePersonCollapse(personKey) {
    const group = this._findPersonGroup(personKey);
    const hasNonTaken = group
      ? group.doses.some(
          (d) => d.status !== STATE_TAKEN && d.status !== STATE_SKIPPED
        )
      : false;
    const currentlyExpanded = this._isPersonExpanded(personKey, hasNonTaken);
    // Persist the OPPOSITE — toggle it.
    this._collapseState[personKey] = currentlyExpanded ? "collapsed" : "expanded";
    this._saveCollapseState();
    this._lastSig = null;
    this._render();
  }

  _toggleKebab(personKey) {
    const root = this.shadowRoot;
    if (!root) return;
    // Close any other person's kebab menu first.
    root.querySelectorAll(".kebab-menu.open").forEach((m) => {
      if (m.getAttribute("data-kebab-for") !== personKey) {
        m.classList.remove("open");
      }
    });
    const target = root.querySelector(
      `.kebab-menu[data-kebab-for="${cssEscape(personKey)}"]`
    );
    if (target) target.classList.toggle("open");
  }

  _openIntegration() {
    history.pushState(null, "", "/config/integrations/integration/pillpilot");
    window.dispatchEvent(new CustomEvent("location-changed"));
  }

  // open the in-panel edit modal for a medicine.
  // Pre-v0.2.21 this navigated to the HA Settings integration page,
  // forcing the user to find the row and click Reconfigure — annoying
  // for everyday changes. The new flow: click Edit → modal opens
  // overlaid on the panel with the medicine's current values pre-
  // filled → user edits → Save submits via the websocket command
  // ``pillpilot/update_medicine`` → modal closes, panel refreshes.
  _editMedicine(medicineId) {
    if (!medicineId) return;
    const med = this._getMedicines().find(
      (m) => m.attributes && m.attributes.medicine_id === medicineId
    );
    if (!med) {
      console.warn("[PillPilot] _editMedicine: no sensor for", medicineId);
      return;
    }
    this._editingMedicineId = medicineId;
    this._editFormDraft = this._draftFromMed(med);
    this._editFormErrors = {};
    this._editFormErrorDetail = null;
    this._editFormSaving = false;
    this._render();
  }

  _closeEditModal() {
    if (!this._editingMedicineId) return;
    this._editingMedicineId = null;
    this._editFormDraft = null;
    this._editFormErrors = {};
    this._editFormErrorDetail = null;
    this._editFormSaving = false;
    // Also close any sub-modal that may be open.
    this._personSubModal = null;
    // Force the next set hass to re-render with fresh data — the panel
    // skipped re-renders while the modal was open.
    this._lastSig = null;
    this._render();
  }

  // --- Add Medicine modal -----------------------------------------------

  // Open the panel-side Add Medicine modal. Replaces the v0.2.x
  // behavior of redirecting to HA Settings → Devices & Services.
  _openAddModal() {
    if (this._addingMedicine || this._editingMedicineId) return;
    this._addingMedicine = true;
    this._editFormDraft = this._blankDraft();
    this._editFormErrors = {};
    this._editFormErrorDetail = null;
    this._editFormSaving = false;
    this._render();
  }

  _closeAddModal() {
    if (!this._addingMedicine) return;
    this._addingMedicine = false;
    this._editFormDraft = null;
    this._editFormErrors = {};
    this._editFormErrorDetail = null;
    this._editFormSaving = false;
    this._personSubModal = null;
    this._lastSig = null;
    this._render();
  }

  // Submit the Add modal — calls pillpilot/create_medicine. On success,
  // closes the modal and lets the panel refresh from the new sensor.
  // On validation failure, surfaces errors in the same nested shape
  // the Edit modal uses.
  async _saveAdd() {
    if (!this._addingMedicine || this._editFormSaving) return;
    if (!this._hass) return;
    this._editFormSaving = true;
    this._editFormErrors = {};
    this._editFormErrorDetail = null;
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "pillpilot/create_medicine",
        data: this._draftToServerInput(this._editFormDraft),
      });
      if (result && result.success) {
        this._closeAddModal();
      } else {
        this._editFormErrors = (result && result.errors) || { base: "unknown" };
        this._editFormSaving = false;
        this._render();
      }
    } catch (err) {
      console.error("[PillPilot] create_medicine WS call failed:", err);
      this._editFormErrors = { base: "ws_error" };
      this._editFormSaving = false;
      this._render();
    }
  }

  // --- prescription sub-modal -------------------------------------------

  // Open the per-prescription sub-modal. ``index`` is the position in
  // _editFormDraft.prescriptions to edit (or null/undefined to add a new
  // one). The sub-modal is a separate stacked overlay above the parent
  // (Add or Edit) modal — the parent modal stays mounted underneath
  // (preserving its own form state).
  _openPrescriptionSubModal(index) {
    if (!this._editFormDraft) return;
    if (this._personSubModal) return; // already open
    let draft;
    if (index == null) {
      draft = this._blankPrescriptionDraft();
    } else {
      const existing = this._editFormDraft.prescriptions[index];
      if (!existing) return;
      // Clone (including the Set) so edits to the sub-modal draft
      // don't mutate the parent draft until the user clicks Save.
      draft = {
        ...existing,
        daysOfWeek: new Set(existing.daysOfWeek),
      };
    }
    this._personSubModal = {
      sourceMode: this._addingMedicine ? "add" : "edit",
      editingIndex: index == null ? null : index,
      draft,
      errors: {},
    };
    this._render();
  }

  _closePrescriptionSubModal() {
    if (!this._personSubModal) return;
    this._personSubModal = null;
    this._render();
  }

  // Apply the sub-modal's draft to the parent _editFormDraft. New
  // prescription = push; editing existing = replace at editingIndex.
  // Closes the sub-modal. No backend call — the prescription is held in
  // the parent draft until the user clicks Save on the parent.
  //
  // Local validation is intentionally minimal (only: must have at least
  // one time). The full validation runs server-side on parent Save and
  // surfaces errors per-prescription back in the parent modal.
  _savePrescriptionSubModal() {
    const sub = this._personSubModal;
    if (!sub || !this._editFormDraft) return;
    const errors = {};
    const times = (sub.draft.times || "").trim();
    if (!times) {
      errors.times = "times_required";
    }
    if (Object.keys(errors).length > 0) {
      sub.errors = errors;
      this._render();
      return;
    }
    const next = [...this._editFormDraft.prescriptions];
    if (sub.editingIndex == null) {
      next.push(sub.draft);
    } else {
      next[sub.editingIndex] = sub.draft;
    }
    this._editFormDraft = {
      ...this._editFormDraft,
      prescriptions: next,
    };
    this._personSubModal = null;
    this._render();
  }

  _removePrescription(index) {
    if (!this._editFormDraft) return;
    const next = [...this._editFormDraft.prescriptions];
    next.splice(index, 1);
    this._editFormDraft = {
      ...this._editFormDraft,
      prescriptions: next,
    };
    this._render();
  }

  // Build the initial form draft from a sensor state. Returns the
  // multi-prescription shape {drug, prescriptions} that the modal
  // renderer and _draftToServerInput both expect. One prescription
  // entry per element of med.attributes.prescriptions[].
  _draftFromMed(med) {
    const a = med.attributes || {};
    const prescriptions = (a.prescriptions || []).map((p) =>
      this._prescriptionDraftFromAttr(p)
    );
    return {
      drug: {
        name: a.medicine_name || "",
        type: a.med_type || MED_TYPE_PILL,
        notes: a.notes || "",
        atc_code: a.atc_code || "",
        npl_id: a.npl_id || "",
        varunummer: a.varunummer || "",
      },
      prescriptions,
    };
  }

  // Convert one prescription dict (from the sensor's prescriptions[]
  // attribute) into the editable draft shape. Times are joined into a
  // comma string; days are stringified into a Set; days_of_month
  // joined into a comma string.
  _prescriptionDraftFromAttr(p) {
    // v0.2.13: variant fields. Pre-migration data on the server side
    // is normalized to variant_strength="{n} mg" before we see it,
    // so this path doesn't need to read unit_strength_mg at all.
    return {
      id: p.id || "",
      person: p.person_id || "",
      unit_count: p.unit_count != null ? String(p.unit_count) : "1",
      variant_strength: p.variant_strength || "",
      variant_form: p.variant_form || "",
      variant_npl_id: p.variant_npl_id || "",
      frequency: p.frequency || "daily",
      times: (p.scheduled_times || []).join(", "),
      daysOfWeek: new Set(
        (p.scheduled_days || []).map((d) => String(parseInt(d, 10)))
      ),
      daysOfMonth: (p.scheduled_days_of_month || []).join(", "),
      // v0.2.0-beta3 fields. interval_days only matters when
      // frequency=interval; default 2 keeps the spinner sensible if
      // the user later flips to interval mode. ends_on is universal
      // and always optional — empty string means "no end date".
      // times_per_weekday is the per-weekday override: null = simple
      // mode (flat times every firing day), set = 7-element array of
      // comma-separated time strings (Mon=0..Sun=6). usePerWeekday is
      // the toggle state — true when timesPerWeekday is in effect.
      intervalDays:
        p.interval_days != null ? String(p.interval_days) : "2",
      startsOn: p.starts_on || "",
      endsOn: p.ends_on || "",
      usePerWeekday: !!p.times_per_weekday,
      timesPerWeekday: p.times_per_weekday
        ? p.times_per_weekday.map((row) => (row || []).join(", "))
        : ["", "", "", "", "", "", ""],
      remind_window:
        p.remind_window_minutes != null
          ? String(p.remind_window_minutes)
          : "60",
    };
  }

  // Empty draft for the Add Medicine modal — drug fields blank, no
  // prescriptions yet (user adds them via the + Add prescription button
  // in the modal). Backend will reject submission with
  // at_least_one_prescription if the user tries to save without adding
  // any.
  _blankDraft() {
    return {
      drug: {
        name: "",
        type: MED_TYPE_PILL,
        notes: "",
        atc_code: "",
        npl_id: "",
        varunummer: "",
      },
      prescriptions: [],
    };
  }

  // Blank prescription used by the sub-modal when the user clicks
  // "+ Add prescription". Sensible defaults: daily, no person assigned
  // (Household), 60-minute reminder window. id is empty so the backend
  // stamps a fresh uuid on save.
  _blankPrescriptionDraft() {
    return {
      id: "",
      person: "",
      unit_count: "1",
      variant_strength: "",
      variant_form: "",
      variant_npl_id: "",
      frequency: "daily",
      times: "",
      daysOfWeek: new Set(),
      daysOfMonth: "",
      intervalDays: "2",
      startsOn: "",
      endsOn: "",
      usePerWeekday: false,
      timesPerWeekday: ["", "", "", "", "", "", ""],
      remind_window: "60",
    };
  }

  // Serialize the draft into the shape pillpilot/update_medicine and
  // pillpilot/create_medicine expect — a nested {drug, prescriptions}
  // payload. The draft is already that shape (Phase 4B refactor); this
  // just normalizes string→number conversion for the wire.
  //
  // Numeric parsing is careful: we don't use ``parseInt(x) || default``
  // because that silently rewrites a deliberate ``0`` as the default.
  // 0 is meaningful: ``remind_window_minutes=0`` means "no remind
  // window — never goes into 'due' state".
  _draftToServerInput(draft) {
    const numOrDefault = (raw, parser, fallback) => {
      const v = parser(raw);
      return Number.isNaN(v) ? fallback : v;
    };
    const prescriptionToWire = (p) => {
      const wire = {
        person_id: p.person || null,
        unit_count: numOrDefault(p.unit_count, parseFloat, 0),
        variant_strength: (p.variant_strength || "").trim(),
        variant_form: (p.variant_form || "").trim(),
        variant_npl_id: (p.variant_npl_id || "").trim() || null,
        frequency: p.frequency,
        times: (p.times || "").trim(),
        days: Array.from(p.daysOfWeek).sort((a, b) => parseInt(a) - parseInt(b)),
        days_of_month: (p.daysOfMonth || "").trim(),
        // v0.2.0-beta3: only sent when meaningful. The validator
        // ignores interval_days for non-interval modes anyway, but
        // omitting the key keeps the wire payload tidy and makes
        // older non-interval prescriptions deserialize cleanly.
        interval_days:
          p.frequency === "interval"
            ? numOrDefault(p.intervalDays, (s) => parseInt(s, 10), 2)
            : null,
        starts_on: (p.startsOn || "").trim(),
        ends_on: (p.endsOn || "").trim(),
        // times_per_weekday: send null when toggle is off (simple
        // mode), or the array of 7 strings when on. The validator
        // accepts comma-separated strings or pre-split lists, so we
        // pass the raw strings — no client-side normalization needed.
        times_per_weekday: p.usePerWeekday
          ? (Array.isArray(p.timesPerWeekday)
              ? p.timesPerWeekday
              : ["", "", "", "", "", "", ""])
          : null,
        remind_window_minutes: numOrDefault(
          p.remind_window,
          (s) => parseInt(s, 10),
          60,
        ),
      };
      // Only include id for prescriptions that already have one — this
      // distinguishes "update existing" from "add new" in the backend's
      // match-by-id merge.
      if (p.id) wire.id = p.id;
      return wire;
    };
    return {
      drug: {
        name: (draft.drug.name || "").trim(),
        med_type: draft.drug.type,
        notes: (draft.drug.notes || "").trim(),
        atc_code: (draft.drug.atc_code || "").trim(),
        npl_id: (draft.drug.npl_id || "").trim(),
        varunummer: (draft.drug.varunummer || "").trim(),
      },
      prescriptions: draft.prescriptions.map(prescriptionToWire),
    };
  }

  async _saveEdit() {
    if (!this._editingMedicineId || this._editFormSaving) return;
    if (!this._hass) return;
    this._editFormSaving = true;
    this._editFormErrors = {};
    this._editFormErrorDetail = null;
    // Re-render to disable the Save button (visual feedback). We can't
    // call _render directly while _editingMedicineId is set because
    // hass updates are blocked — but _render itself isn't blocked.
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "pillpilot/update_medicine",
        medicine_id: this._editingMedicineId,
        data: this._draftToServerInput(this._editFormDraft),
      });
      if (result && result.success) {
        this._closeEditModal();
      } else {
        this._editFormErrors = (result && result.errors) || { base: "unknown" };
        this._editFormSaving = false;
        this._render();
      }
    } catch (err) {
      console.error("[PillPilot] update_medicine WS call failed:", err);
      this._editFormErrors = { base: "ws_error" };
      this._editFormSaving = false;
      this._render();
    }
  }

  // Delete the medicine currently open in the Edit modal. Confirms with
  // the user first because deletion is destructive — removes the
  // subentry, the sensor entity, and any per-medicine device. Dose
  // history (stored separately under the medicine_id key) becomes
  // orphaned but is harmless; the medicine no longer surfaces in the
  // panel or in HA Settings.
  async _deleteMedicine() {
    if (!this._editingMedicineId || this._editFormSaving) return;
    if (!this._hass) return;
    const medName =
      (this._editFormDraft && this._editFormDraft.drug && this._editFormDraft.drug.name) ||
      "this medicine";
    if (
      !window.confirm(
        `Delete "${medName}"? This removes the medicine and its sensor. ` +
        `Dose history is not removed but will no longer be visible.`
      )
    ) {
      return;
    }
    this._editFormSaving = true;
    this._editFormErrors = {};
    this._editFormErrorDetail = null;
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "pillpilot/delete_medicine",
        medicine_id: this._editingMedicineId,
      });
      if (result && result.success) {
        this._closeEditModal();
      } else {
        this._editFormErrors = (result && result.errors) || { base: "unknown" };
        // Stash the optional exception detail (string) coming back
        // from the backend so the banner can show it. Without this
        // detail, "delete_failed" / "ws_error" stay opaque.
        this._editFormErrorDetail = (result && result.error_detail) || null;
        this._editFormSaving = false;
        this._render();
      }
    } catch (err) {
      console.error("[PillPilot] delete_medicine WS call failed:", err);
      this._editFormErrors = { base: "ws_error" };
      this._editFormErrorDetail = (err && (err.message || String(err))) || null;
      this._editFormSaving = false;
      this._render();
    }
  }

  // --- render ------------------------------------------------------------

  _render() {
    let html;
    try {
      if (!this._hass) {
        html = this._renderLoading();
      } else {
        const meds = this._getMedicines();
        html = meds.length === 0 ? this._renderEmpty() : this._renderFull(meds);
      }
    } catch (e) {
      console.error("[PillPilot] render failed:", e);
      html = this._renderError(e);
    }
    // Modal layering: main modal (Edit OR Add) overlays the content,
    // sub-modal stacks above the main modal via higher z-index. Only
    // one main modal is open at a time. Sub-modal can only be open when
    // a main modal is also open.
    let mainModalHtml = "";
    if (this._editingMedicineId) {
      mainModalHtml = this._renderEditModal();
    } else if (this._addingMedicine) {
      mainModalHtml = this._renderAddModal();
    }
    const subModalHtml = this._personSubModal
      ? this._renderPrescriptionSubModal()
      : "";
    this.shadowRoot.innerHTML =
      `<style>${STYLES}</style>${html}${mainModalHtml}${subModalHtml}`;
    this._wireListeners();
    if (this._editingMedicineId || this._addingMedicine) {
      this._wireMainModalListeners();
    }
    if (this._personSubModal) {
      this._wireSubModalListeners();
    }
    if (this._debug) console.log("[PillPilot] rendered");
  }

  // Shown immediately on mount, before HA pushes hass to the element.
  // Without this the user could see a blank panel for the brief window
  // between connectedCallback firing and the first `set hass` call.
  _renderLoading() {
    return `
      <div class="container">
        <header>
          <div>
            <h1>PillPilot</h1>
            <p class="subtitle">Loading…</p>
          </div>
        </header>
      </div>
    `;
  }

  // Surface render errors visibly rather than blanking the panel.
  // If the user ever sees this, it's a bug worth reporting — the error
  // text gives us something concrete to investigate.
  _renderError(e) {
    const msg = (e && e.message) ? e.message : String(e);
    return `
      <div class="container">
        <header>
          <div>
            <h1>PillPilot</h1>
            <p class="subtitle">Render error — open DevTools console for details</p>
          </div>
        </header>
        <div class="empty">${escapeHtml(msg)}</div>
      </div>
    `;
  }

  _renderEmpty() {
    return `
      <div class="container">
        <header>
          <div>
            <h1>PillPilot</h1>
            <p class="subtitle">No medicines yet</p>
          </div>
          <div class="header-actions">
            <button class="config-btn" data-action="open-config" aria-label="Configure integration" title="Configure integration">⚙</button>
            <button class="add-btn" data-action="add">+ Add medicine</button>
          </div>
        </header>
        <div class="empty">
          Click <a class="empty-link" href="#" data-action="add">+ Add medicine</a> above to get started.
        </div>
      </div>
    `;
  }

  // Phase 4B: in-panel main modal — TWO components share the same body
  // structure (drug fields + prescriptions list) but differ in chrome:
  //
  //   _renderEditModal — title "Edit medicine", calls
  //     pillpilot/update_medicine on save (keeps medicine_id)
  //   _renderAddModal  — title "Add medicine", calls
  //     pillpilot/create_medicine on save (no medicine_id)
  //
  // Both render the body via _renderMainModalBody and the prescription
  // rows via _renderPrescriptionRow. Sub-modal for individual
  // prescriptions is _renderPrescriptionSubModal — stacks above either
  // main modal.
  _renderEditModal() {
    const draft = this._editFormDraft;
    if (!draft) return "";
    const errors = this._editFormErrors || {};
    const saving = this._editFormSaving;
    return this._renderMainModalShell({
      title: "Edit medicine",
      closeAction: "close-edit-modal",
      saveAction: "save-edit",
      saveLabel: saving ? "Saving…" : "Save",
      saving,
      // Delete is Edit-only — there's nothing to delete in the Add flow.
      showDelete: true,
      body: this._renderMainModalBody(draft, errors),
    });
  }

  _renderAddModal() {
    const draft = this._editFormDraft;
    if (!draft) return "";
    const errors = this._editFormErrors || {};
    const saving = this._editFormSaving;
    return this._renderMainModalShell({
      title: "Add medicine",
      closeAction: "close-add-modal",
      saveAction: "save-add",
      saveLabel: saving ? "Adding…" : "Add medicine",
      saving,
      showDelete: false,
      body: this._renderMainModalBody(draft, errors),
    });
  }

  // Common chrome: overlay + card + header + body + footer. Used by
  // both Edit and Add modals; also used by the prescription sub-modal
  // (with different actions) so the structure stays consistent.
  // showDelete adds a danger-styled "Delete medicine" button on the
  // left of the footer; right-aligned Cancel/Save stay grouped.
  _renderMainModalShell({ title, closeAction, saveAction, saveLabel, saving, showDelete, body }) {
    const errors = this._editFormErrors || {};
    const errMsg = (key) => this._editErrorText(key);
    const detail = this._editFormErrorDetail;
    const detailHtml = detail
      ? `<div class="modal-error-detail">${escapeHtml(detail)}</div>`
      : "";
    const baseError = errors && errors.base
      ? `<div class="modal-error-banner">${escapeHtml(errMsg(errors.base))}${detailHtml}</div>`
      : "";
    const deleteBtn = showDelete
      ? `<button class="modal-btn modal-btn-danger" data-action="delete-edit" ${saving ? "disabled" : ""}>Delete medicine</button>`
      : "";
    return `
      <div class="modal-overlay" data-action="${closeAction}">
        <div class="modal-card" data-action="modal-stop">
          <header class="modal-header">
            <h2>${escapeHtml(title)}</h2>
            <button class="modal-close-btn" data-action="${closeAction}" aria-label="Close">×</button>
          </header>
          ${baseError}
          <div class="modal-body">
            ${body}
          </div>
          <footer class="modal-footer">
            ${deleteBtn}
            <div class="modal-footer-right">
              <button class="modal-btn modal-btn-secondary" data-action="${closeAction}" ${saving ? "disabled" : ""}>Cancel</button>
              <button class="modal-btn modal-btn-primary" data-action="${saveAction}" ${saving ? "disabled" : ""}>${escapeHtml(saveLabel)}</button>
            </div>
          </footer>
        </div>
      </div>
    `;
  }

  // The drug-fields section + the prescriptions list. Shared between
  // Add and Edit modals.
  _renderMainModalBody(draft, errors) {
    const drugErrors = (errors && errors.drug) || {};
    const prescriptionErrors = (errors && errors.prescriptions) || [];
    const errMsg = (key) => this._editErrorText(key);
    const drugFieldError = (field) =>
      drugErrors[field]
        ? `<div class="field-error">${escapeHtml(errMsg(drugErrors[field]))}</div>`
        : "";

    // Build options for the medicine-name datalist (autocomplete).
    // Combines the bundled medicines catalog (fetched once via
    // pillpilot/get_medicines_db) with names of medicines already
    // present in this install. Each catalog alias becomes its own
    // option so a user typing a misspelling like "alvadon" still finds
    // Alvedon — the change-listener wired in _wireMainModalListeners
    // resolves the alias to the canonical brand on commit and auto-
    // fills ATC + notes (if those fields are empty).
    //
    // Free-text typed values that aren't in the list still pass
    // through — it's an <input list=...>, not a <select>.
    const existingNames = this._getMedicines().map(
      (m) => m.attributes.medicine_name || ""
    );
    const nameOptions = this._buildNameOptions(existingNames)
      .map((o) => {
        // For brand entries (where label == value) the label attribute
        // is redundant and Chrome shows it twice, so omit it.
        if (o.label === o.value) {
          return `<option value="${escapeHtml(o.value)}"></option>`;
        }
        return `<option value="${escapeHtml(o.value)}" label="${escapeHtml(o.label)}"></option>`;
      })
      .join("");

    const typeOptions = [
      [MED_TYPE_PILL, "Pill"],
      [MED_TYPE_INJECTION, "Injection"],
      [MED_TYPE_DROPS, "Drops"],
    ]
      .map(
        ([v, label]) =>
          `<option value="${v}" ${draft.drug.type === v ? "selected" : ""}>${escapeHtml(label)}</option>`
      )
      .join("");

    const prescriptionRows = draft.prescriptions
      .map((p, i) =>
        this._renderPrescriptionRow(p, i, prescriptionErrors[i] || {})
      )
      .join("");

    // v0.2.12: catalog variants hint. When the typed name matches a
    // known medicine, surface the available strength/form combinations
    // from the bundled catalog. Read-only — the form's strength input
    // is still free-text in this release.
    const catalogHit = this._lookupMedNameOrAlias(draft.drug.name);
    const catalogVariants =
      catalogHit && Array.isArray(catalogHit.variants)
        ? catalogHit.variants.filter(
            (v) => (v.strength || "").trim() || (v.form || "").trim()
          )
        : [];
    const variantsHtml = catalogVariants.length
      ? `
      <div class="form-section catalog-variants">
        <h3 class="form-section-title">Available strengths (from catalog)</h3>
        <ul class="catalog-variants-list">
          ${catalogVariants
            .map((v) => {
              const s = (v.strength || "").trim();
              const f = (v.form || "").trim();
              const text = s && f ? `${s} — ${f}` : s || f;
              return `<li>${escapeHtml(text)}</li>`;
            })
            .join("")}
        </ul>
      </div>
      `
      : "";

    return `
      <div class="form-section">
        <h3 class="form-section-title">Identity</h3>
        <label class="form-field">
          <span class="form-label">Name *</span>
          <input type="text" class="form-input" data-edit-field="drug.name" value="${escapeHtml(draft.drug.name)}" list="pp-edit-name-list" autocomplete="off">
          <datalist id="pp-edit-name-list">${nameOptions}</datalist>
          ${drugFieldError("name")}
        </label>
        <label class="form-field">
          <span class="form-label">Type *</span>
          <select class="form-input" data-edit-field="drug.type">${typeOptions}</select>
          ${drugFieldError("med_type")}
        </label>
      </div>

      <div class="form-section">
        <h3 class="form-section-title">Notes</h3>
        <label class="form-field">
          <input type="text" class="form-input" data-edit-field="drug.notes" value="${escapeHtml(draft.drug.notes)}" placeholder="Free-form notes (active substance, etc.)">
        </label>
      </div>

      <div class="form-section">
        <h3 class="form-section-title">Codes (optional)</h3>
        <div class="form-row">
          <label class="form-field">
            <span class="form-label">ATC code</span>
            <input type="text" class="form-input" data-edit-field="drug.atc_code" value="${escapeHtml(draft.drug.atc_code)}">
          </label>
          <label class="form-field">
            <span class="form-label">Varunummer</span>
            <input type="text" class="form-input" data-edit-field="drug.varunummer" value="${escapeHtml(draft.drug.varunummer)}">
          </label>
          <label class="form-field">
            <span class="form-label">NPL ID</span>
            <input type="text" class="form-input" data-edit-field="drug.npl_id" value="${escapeHtml(draft.drug.npl_id)}">
          </label>
        </div>
      </div>

      ${variantsHtml}

      <div class="form-section">
        <div class="form-section-titlerow">
          <h3 class="form-section-title">Prescriptions</h3>
        </div>
        ${draft.prescriptions.length === 0
          ? `<div class="prescription-empty">No prescriptions yet — add one to get started.</div>`
          : `<div class="prescription-list">${prescriptionRows}</div>`
        }
        <button class="modal-btn modal-btn-secondary add-prescription-btn" data-action="add-prescription">+ Add prescription</button>
      </div>
    `;
  }

  // One row in the prescriptions list inside the Add/Edit main modal.
  // Shows a one-line summary (person · dose · schedule) and Edit /
  // Remove buttons. If the backend rejected this prescription with
  // errors on save, a small error chip appears.
  _renderPrescriptionRow(p, index, perPrescriptionErrors) {
    const personName = this._personNameFor(p.person);
    const summary = this._formatPrescriptionDraftSummary(p);
    const hasErrors = perPrescriptionErrors && Object.keys(perPrescriptionErrors).length > 0;
    return `
      <div class="prescription-row${hasErrors ? " prescription-row-error" : ""}">
        <div class="prescription-summary">
          <div class="prescription-person">${escapeHtml(personName)}</div>
          <div class="prescription-detail">${escapeHtml(summary)}</div>
          ${hasErrors
            ? `<div class="prescription-errors">${escapeHtml(this._formatPrescriptionErrors(perPrescriptionErrors))}</div>`
            : ""}
        </div>
        <div class="prescription-row-actions">
          <button class="modal-btn modal-btn-secondary" data-action="edit-prescription" data-prescription-index="${index}">Edit</button>
          <button class="modal-btn modal-btn-secondary" data-action="remove-prescription" data-prescription-index="${index}">Remove</button>
        </div>
      </div>
    `;
  }

  // Single line summarizing a prescription for the row display.
  // Format: "{dose} · {schedule}". v0.2.13: dose composed from
  // unit_count + variant_strength + variant_form, with "= total mg"
  // appended only when variant_strength parses as <number> mg
  // (matches the server-side Dose.total_mg logic — combos, IUs and
  // concentrations stay as "{count} × {variant_strength} {form}").
  _formatPrescriptionDraftSummary(p) {
    const count = parseFloat(p.unit_count);
    const drugType =
      (this._editFormDraft && this._editFormDraft.drug && this._editFormDraft.drug.type) ||
      MED_TYPE_PILL;
    const unitWord =
      drugType === MED_TYPE_INJECTION ? "injection"
      : drugType === MED_TYPE_DROPS ? "drop"
      : "pill";
    const unitLabel = count === 1 ? unitWord : `${unitWord}s`;
    const strength = (p.variant_strength || "").trim();
    const form = (p.variant_form || "").trim();
    let dosePart;
    if (Number.isNaN(count)) {
      dosePart = "?";
    } else if (!strength && !form) {
      dosePart = `${count} ${unitLabel}`;
    } else {
      const desc = [strength, form].filter(Boolean).join(" ");
      const mgMatch = strength.match(/^\s*(\d+(?:[.,]\d+)?)\s*mg\s*$/i);
      let tail = "";
      if (mgMatch) {
        const mgValue = parseFloat(mgMatch[1].replace(",", "."));
        if (!Number.isNaN(mgValue)) {
          const total = count * mgValue;
          tail = ` = ${total % 1 === 0 ? total : total.toFixed(3).replace(/\.?0+$/, "")} mg`;
        }
      }
      dosePart = `${count} ${unitLabel} × ${desc}${tail}`;
    }
    // Convert the draft's daysOfWeek Set + daysOfMonth string + times
    // string into the same shape _formatSchedule expects.
    const sched = this._formatSchedule({
      scheduled_times: (p.times || "").split(",").map((t) => t.trim()).filter(Boolean),
      frequency: p.frequency,
      scheduled_days: Array.from(p.daysOfWeek).map((d) => parseInt(d, 10)),
      scheduled_days_of_month: (p.daysOfMonth || "")
        .split(",").map((d) => parseInt(d.trim(), 10)).filter((d) => !isNaN(d)),
      interval_days: parseInt(p.intervalDays, 10),
      ends_on: (p.endsOn || "").trim() || null,
      // Pass per-weekday strings only when the toggle is on; null
      // otherwise so the summary shows the flat times instead.
      times_per_weekday: p.usePerWeekday
        ? (Array.isArray(p.timesPerWeekday) ? p.timesPerWeekday : null)
        : null,
    });
    return `${dosePart} · ${sched}`;
  }

  _formatPrescriptionErrors(errs) {
    return Object.entries(errs)
      .map(([field, key]) => this._editErrorText(key))
      .join(" • ");
  }

  // Look up a person's friendly name by entity_id. Returns "Household"
  // for the empty/null case.
  _personNameFor(personEntityId) {
    if (!personEntityId) return "Household";
    if (this._hass && this._hass.states && this._hass.states[personEntityId]) {
      const s = this._hass.states[personEntityId];
      return s.attributes.friendly_name || personEntityId;
    }
    return personEntityId;
  }

  // ---------------------------------------------------------------------
  // Prescription sub-modal — opened from either Add or Edit when the
  // user clicks "+ Add prescription" or "Edit" on a prescription row.
  // Stacks above the parent modal via higher z-index.
  // ---------------------------------------------------------------------
  _renderPrescriptionSubModal() {
    const sub = this._personSubModal;
    if (!sub) return "";
    const draft = sub.draft;
    const errors = sub.errors || {};
    const isAdd = sub.editingIndex == null;
    const errMsg = (key) => this._editErrorText(key);
    const fieldError = (field) =>
      errors[field]
        ? `<div class="field-error">${escapeHtml(errMsg(errors[field]))}</div>`
        : "";

    // Person dropdown: blank ("Household") + every person.* entity.
    // Per audit decision F26: dropdown shows everyone always, no
    // filtering.
    const personOptions = [
      `<option value="" ${!draft.person ? "selected" : ""}>Household (no person)</option>`,
    ];
    if (this._hass && this._hass.states) {
      Object.values(this._hass.states)
        .filter((s) => s.entity_id.startsWith("person."))
        .sort((a, b) =>
          (a.attributes.friendly_name || a.entity_id).localeCompare(
            b.attributes.friendly_name || b.entity_id
          )
        )
        .forEach((s) => {
          const id = escapeHtml(s.entity_id);
          const name = escapeHtml(s.attributes.friendly_name || s.entity_id);
          const sel = draft.person === s.entity_id ? "selected" : "";
          personOptions.push(`<option value="${id}" ${sel}>${name}</option>`);
        });
    }

    const freqOptions = [
      ["daily", "Daily — every day"],
      ["weekly", "Weekly — on selected weekdays"],
      ["monthly", "Monthly — on selected days of the month"],
      ["interval", "Every N days — every other day, every 3 days, etc."],
    ]
      .map(
        ([v, label]) =>
          `<option value="${v}" ${draft.frequency === v ? "selected" : ""}>${escapeHtml(label)}</option>`
      )
      .join("");

    const dayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    // beta3.6: which preset (if any) matches the current selection,
    // for active-state highlighting. None matches → custom selection
    // → no preset highlighted (user is mid-edit on individual chips).
    const selectedDays = Array.from(draft.daysOfWeek)
      .map((d) => parseInt(d, 10))
      .sort((a, b) => a - b);
    const isEveryDay = selectedDays.length === 7;
    const isWeekdays =
      selectedDays.length === 5 &&
      selectedDays.every((d, i) => d === i);
    const isWeekends =
      selectedDays.length === 2 &&
      selectedDays[0] === 5 &&
      selectedDays[1] === 6;
    const presetButtons = [
      ["every-day", "Every day", isEveryDay],
      ["weekdays", "Weekdays", isWeekdays],
      ["weekends", "Weekends", isWeekends],
    ]
      .map(
        ([preset, label, active]) =>
          `<button type="button" class="weekday-preset-btn ${active ? "active" : ""}" data-action="weekday-preset" data-preset="${preset}">${label}</button>`,
      )
      .join("");
    const dayChips = dayLabels
      .map((label, idx) => {
        const active = draft.daysOfWeek.has(String(idx)) ? "active" : "";
        return `<button type="button" class="weekday-chip ${active}" data-action="weekday-toggle" data-day-index="${idx}">${label}</button>`;
      })
      .join("");

    const showWeekly = draft.frequency === "weekly";
    const showMonthly = draft.frequency === "monthly";
    const showInterval = draft.frequency === "interval";

    // v0.2.13: variant strength input. When the parent modal's
    // medicine name matches a catalog entry, render a dropdown of
    // its variants ("5 mg — Filmdragerad tablett", etc.) plus
    // synthetic "(current)" and "Custom…" options. When custom is
    // active (off-catalog medicine, or user-picked custom), show
    // two free-text fields (strength + form).
    const drugName =
      (this._editFormDraft && this._editFormDraft.drug && this._editFormDraft.drug.name) || "";
    const catalogHit = this._lookupMedNameOrAlias(drugName);
    const catalogVariants =
      catalogHit && Array.isArray(catalogHit.variants)
        ? catalogHit.variants.filter(
            (v) => (v.strength || "").trim() || (v.form || "").trim()
          )
        : [];
    const currentStrength = (draft.variant_strength || "").trim();
    const currentForm = (draft.variant_form || "").trim();
    const variantKey = (s, f) => `${s}\u0000${f}`;
    const currentKey = variantKey(currentStrength, currentForm);
    const matchedVariant = catalogVariants.find(
      (v) => variantKey((v.strength || "").trim(), (v.form || "").trim()) === currentKey
    );
    const customActive = !!draft.variant_custom;
    // The dropdown is shown when the catalog has variants for the
    // medicine. The user-typed custom path activates either when
    // (a) no catalog variants exist, or (b) the user explicitly
    // picks Custom from the dropdown (sets draft.variant_custom),
    // or (c) the existing prescription doesn't match any variant
    // — pre-selecting "(current)" still shows the dropdown but
    // labels the current value.
    let strengthInputHtml;
    if (catalogVariants.length === 0 || customActive) {
      strengthInputHtml = `
        <label class="form-field">
          <span class="form-label">Strength *</span>
          <input type="text" class="form-input" data-sub-field="variant_strength" value="${escapeHtml(currentStrength)}" placeholder="e.g. 5 mg">
          ${fieldError("variant_strength")}
        </label>
        <label class="form-field">
          <span class="form-label">Form</span>
          <input type="text" class="form-input" data-sub-field="variant_form" value="${escapeHtml(currentForm)}" placeholder="e.g. Filmdragerad tablett">
        </label>
      `;
    } else {
      const options = [];
      if (currentStrength && !matchedVariant) {
        const label = currentForm
          ? `${currentStrength} — ${currentForm} (current)`
          : `${currentStrength} (current)`;
        options.push(
          `<option value="__current__" selected>${escapeHtml(label)}</option>`
        );
      }
      catalogVariants.forEach((v) => {
        const s = (v.strength || "").trim();
        const f = (v.form || "").trim();
        const label = s && f ? `${s} — ${f}` : s || f;
        const value = `${s}|${f}`;
        const isMatch = matchedVariant === v;
        options.push(
          `<option value="${escapeHtml(value)}" ${isMatch ? "selected" : ""}>${escapeHtml(label)}</option>`
        );
      });
      options.push(`<option value="__custom__">Custom…</option>`);
      strengthInputHtml = `
        <label class="form-field">
          <span class="form-label">Strength *</span>
          <select class="form-input" data-sub-field="variant_select">${options.join("")}</select>
          ${fieldError("variant_strength")}
        </label>
      `;
    }

    return `
      <div class="modal-overlay sub-modal-overlay" data-action="close-sub-modal">
        <div class="modal-card sub-modal-card" data-action="modal-stop">
          <header class="modal-header">
            <h2>${isAdd ? "Add prescription" : "Edit prescription"}</h2>
            <button class="modal-close-btn" data-action="close-sub-modal" aria-label="Close">×</button>
          </header>
          <div class="modal-body">

            <div class="form-section">
              <h3 class="form-section-title">Person</h3>
              <label class="form-field">
                <span class="form-label">Assigned to</span>
                <select class="form-input" data-sub-field="person">${personOptions.join("")}</select>
              </label>
            </div>

            <div class="form-section">
              <h3 class="form-section-title">Dose</h3>
              <div class="form-row">
                <label class="form-field">
                  <span class="form-label">Unit count *</span>
                  <input type="number" min="0.1" step="0.1" class="form-input" data-sub-field="unit_count" value="${escapeHtml(draft.unit_count)}">
                  ${fieldError("unit_count")}
                </label>
                ${strengthInputHtml}
              </div>
            </div>

            <div class="form-section">
              <h3 class="form-section-title">Schedule</h3>
              <label class="form-field">
                <span class="form-label">Frequency *</span>
                <select class="form-input" data-sub-field="frequency">${freqOptions}</select>
              </label>
              <div class="form-field times-mode-picker">
                <span class="form-label">Times mode</span>
                <label class="radio-option">
                  <input type="radio" name="times-mode" data-sub-field="usePerWeekday" data-mode="same" ${!draft.usePerWeekday ? "checked" : ""}>
                  <span>Same times every day</span>
                </label>
                <label class="radio-option">
                  <input type="radio" name="times-mode" data-sub-field="usePerWeekday" data-mode="perWeekday" ${draft.usePerWeekday ? "checked" : ""}>
                  <span>Different times per weekday</span>
                </label>
              </div>
              ${!draft.usePerWeekday ? `
              <label class="form-field">
                <span class="form-label">Times of day *</span>
                <input type="text" class="form-input" data-sub-field="times" value="${escapeHtml(draft.times)}" placeholder="07:00, 20:00">
                <span class="form-hint">Comma-separated 24-hour times (HH:MM).</span>
                ${fieldError("times")}
              </label>` : `
              <div class="form-field per-weekday-rows">
                ${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((label, idx) => `
                  <div class="weekday-row">
                    <span class="weekday-label">${label}</span>
                    <input type="text" class="form-input weekday-input" data-sub-field="timesPerWeekday" data-day-index="${idx}" value="${escapeHtml((draft.timesPerWeekday && draft.timesPerWeekday[idx]) || "")}" placeholder="08:00, 20:00 — blank = skip">
                  </div>
                `).join("")}
                <span class="form-hint">Leave a row blank to skip doses on that weekday.</span>
                ${fieldError("times_per_weekday")}
              </div>`}
              ${showWeekly ? `
              <div class="form-field">
                <span class="form-label">Days of week</span>
                <div class="weekday-presets">${presetButtons}</div>
                <div class="weekday-chip-row">${dayChips}</div>
                ${fieldError("days")}
              </div>` : ""}
              ${showMonthly ? `
              <label class="form-field">
                <span class="form-label">Days of month *</span>
                <input type="text" class="form-input" data-sub-field="daysOfMonth" value="${escapeHtml(draft.daysOfMonth)}" placeholder="1, 15">
                <span class="form-hint">Comma-separated days 1–31.</span>
                ${fieldError("days_of_month")}
              </label>` : ""}
              ${showInterval ? `
              <label class="form-field">
                <span class="form-label">Interval (days) *</span>
                <input type="number" min="2" max="365" step="1" class="form-input" data-sub-field="intervalDays" value="${escapeHtml(draft.intervalDays || "2")}">
                <span class="form-hint">Fires every N days from the start date. Use 2 for every other day, 3 for every third day, and so on. Survives month boundaries.</span>
                ${fieldError("interval_days")}
              </label>
              <label class="form-field">
                <span class="form-label">Start date</span>
                <input type="date" class="form-input" data-sub-field="startsOn" value="${escapeHtml(draft.startsOn || "")}">
                <span class="form-hint">Optional — leave empty to start today. Set to a past date if you've already taken the medicine recently (e.g. last dose 7 days ago for a 14-day cycle).</span>
                ${fieldError("starts_on")}
              </label>` : ""}
              <label class="form-field">
                <span class="form-label">End date</span>
                <input type="date" class="form-input" data-sub-field="endsOn" value="${escapeHtml(draft.endsOn || "")}">
                <span class="form-hint">Optional — leave empty for no end date. Useful for antibiotic courses or other time-limited prescriptions.</span>
                ${fieldError("ends_on")}
              </label>
              <label class="form-field">
                <span class="form-label">Reminder window</span>
                <div class="slider-with-input">
                  <input type="range" min="5" max="240" step="5" class="form-slider"
                         data-sub-field="remind_window"
                         value="${escapeHtml(draft.remind_window)}"
                         aria-label="Reminder window in minutes">
                  <input type="number" min="5" max="240" step="5" class="form-input slider-number"
                         data-sub-field="remind_window"
                         value="${escapeHtml(draft.remind_window)}">
                  <span class="slider-unit">min</span>
                </div>
                <span class="form-hint">How long after the scheduled time the dose stays in "due" state before it's marked missed.</span>
              </label>
            </div>

          </div>
          <footer class="modal-footer">
            <button class="modal-btn modal-btn-secondary" data-action="close-sub-modal">Cancel</button>
            <button class="modal-btn modal-btn-primary" data-action="save-sub-modal">${isAdd ? "Add" : "Update"}</button>
          </footer>
        </div>
      </div>
    `;
  }

  // Translate backend error keys to human-readable strings. The keys
  // match what validate_medicine_input_multi emits + a few panel-specific
  // ones (ws_error, unknown).
  _editErrorText(key) {
    const messages = {
      // Drug-identity errors
      name_required: "Medicine name is required.",
      invalid_type: "Type must be Pill, Drops, or Injection.",
      // Prescription errors
      days_of_month_range: "Days of month must each be between 1 and 31.",
      days_of_month_invalid: "Couldn't parse days of month — use comma-separated numbers.",
      days_of_month_required: "Monthly schedule needs at least one day of the month.",
      days_invalid: "Couldn't parse weekdays — expected 0–6 (Mon–Sun).",
      days_range: "Weekdays must be between 0 (Mon) and 6 (Sun).",
      days_required: "Weekly schedule needs at least one weekday.",
      duplicate_prescription_id: "This prescription has the same id as another. Each must be unique.",
      ends_on_invalid: "End date must be in YYYY-MM-DD format. Leave empty for no end date.",
      starts_on_invalid: "Start date must be in YYYY-MM-DD format. Leave empty to start today.",
      frequency_invalid: "Frequency must be daily, weekly, monthly, or every N days.",
      interval_days_required: "Every-N-days schedule needs an interval (2 or more days).",
      interval_days_invalid: "Interval must be a whole number.",
      interval_days_range: "Interval must be between 2 and 365 days.",
      times_per_weekday_invalid: "Per-weekday times must be 7 entries (Mon to Sun) of comma-separated HH:MM times.",
      times_per_weekday_length: "Per-weekday times need exactly 7 entries (one per weekday).",
      times_per_weekday_required: "Per-weekday times need at least one weekday with a dose time.",
      times_per_weekday_time_invalid: "One of the per-weekday rows has a malformed time. Use HH:MM format.",
      times_invalid: "Times must be in HH:MM format (e.g. '07:00' or '7:00').",
      invalid_number: "Enter a valid number.",
      // Sub-modal local validation
      times_required: "Add at least one time of day.",
      // Base errors
      at_least_one_prescription: "Add at least one prescription.",
      medicine_not_found: "This medicine no longer exists.",
      update_failed: "Saving failed. Please try again.",
      create_failed: "Creating the medicine failed. Please try again.",
      delete_failed: "Deleting the medicine failed.",
      no_pillpilot_entry: "PillPilot is not set up. Add it from Settings → Devices & Services first.",
      ws_error: "Couldn't reach Home Assistant. Please try again.",
      unknown: "Something went wrong.",
    };
    return messages[key] || key;
  }

  _wireMainModalListeners() {
    const root = this.shadowRoot;
    if (!root) return;

    // Modal close on backdrop / X button. The data-action distinguishes
    // Edit (close-edit-modal) from Add (close-add-modal). modal-stop
    // catches clicks inside the card so they don't bubble to the
    // backdrop and trigger close.
    root.querySelectorAll('[data-action="close-edit-modal"]').forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        if (this._editFormSaving) return;
        if (
          e.currentTarget === e.target ||
          e.currentTarget.classList.contains("modal-close-btn")
        ) {
          this._closeEditModal();
        }
      });
    });
    root.querySelectorAll('[data-action="close-add-modal"]').forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        if (this._editFormSaving) return;
        if (
          e.currentTarget === e.target ||
          e.currentTarget.classList.contains("modal-close-btn")
        ) {
          this._closeAddModal();
        }
      });
    });
    root.querySelectorAll('[data-action="modal-stop"]').forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
      });
    });

    // Save buttons.
    root.querySelectorAll('[data-action="save-edit"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._saveEdit();
      });
    });
    root.querySelectorAll('[data-action="save-add"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._saveAdd();
      });
    });
    root.querySelectorAll('[data-action="delete-edit"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._deleteMedicine();
      });
    });

    // Drug-field inputs — paths like "drug.name", "drug.type", etc.
    // Update the corresponding key in _editFormDraft.drug.
    root.querySelectorAll("[data-edit-field]").forEach((el) => {
      const path = el.dataset.editField;
      const eventName = el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(eventName, (e) => {
        if (!this._editFormDraft) return;
        const value = e.currentTarget.value;
        // Path is dotted (e.g. "drug.name"). Walk one level, set the
        // leaf. Currently always two segments — kept generic for future
        // extension.
        const parts = path.split(".");
        if (parts.length === 2) {
          const [obj, key] = parts;
          if (!this._editFormDraft[obj]) this._editFormDraft[obj] = {};
          this._editFormDraft[obj][key] = value;
        } else {
          this._editFormDraft[path] = value;
        }
      });
    });

    // Drug-name auto-fill — fires when the user commits a value
    // (blurs the field or picks an option from the datalist). On a
    // catalog hit, rewrites the name to the canonical brand and
    // pre-fills empty atc_code / notes from the catalog entry. Only
    // wired on the name field itself; other drug-fields are pure
    // pass-through.
    const nameInput = root.querySelector('[data-edit-field="drug.name"]');
    if (nameInput) {
      nameInput.addEventListener("change", (e) => {
        if (!this._editFormDraft) return;
        const typed = e.currentTarget.value;
        const changed = this._applyDrugNameAutoFill(typed);
        if (changed) {
          // Re-render so the canonical brand name + filled fields show.
          // Modal stays open because _editingMedicineId / _addingMedicine
          // is still set, so set hass would have been suppressed; this
          // explicit _render is the only way to reflect the change.
          this._render();
        }
      });
    }

    // + Add prescription button — opens sub-modal with blank draft.
    root.querySelectorAll('[data-action="add-prescription"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._openPrescriptionSubModal(null);
      });
    });

    // Edit prescription row button — opens sub-modal with that row's draft.
    root.querySelectorAll('[data-action="edit-prescription"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const idx = parseInt(e.currentTarget.dataset.prescriptionIndex, 10);
        if (!isNaN(idx)) this._openPrescriptionSubModal(idx);
      });
    });

    // Remove prescription row button — splices that index from
    // draft.prescriptions. No confirm dialog (per audit O-E).
    root.querySelectorAll('[data-action="remove-prescription"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const idx = parseInt(e.currentTarget.dataset.prescriptionIndex, 10);
        if (!isNaN(idx)) this._removePrescription(idx);
      });
    });
  }

  _wireSubModalListeners() {
    const root = this.shadowRoot;
    if (!root) return;

    // Backdrop / X / Cancel close. Same pattern as main modal — only
    // close when click is on the backdrop or the close button itself,
    // not on something that bubbled up from inside.
    root.querySelectorAll('[data-action="close-sub-modal"]').forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        if (this._editFormSaving) return;
        if (
          e.currentTarget === e.target ||
          e.currentTarget.classList.contains("modal-close-btn") ||
          e.currentTarget.classList.contains("modal-btn-secondary")
        ) {
          this._closePrescriptionSubModal();
        }
      });
    });
    // Note: modal-stop is wired by _wireMainModalListeners' selector
    // (querySelectorAll catches both modals' modal-stop elements). But
    // when only the sub-modal is open without a main modal, that wiring
    // doesn't run. Re-wire here defensively.
    root.querySelectorAll('[data-action="modal-stop"]').forEach((el) => {
      // Don't double-wire — addEventListener with the same handler
      // would still fire twice. Use a sentinel attribute to dedup.
      if (el.dataset._stopWired === "1") return;
      el.dataset._stopWired = "1";
      el.addEventListener("click", (e) => {
        e.stopPropagation();
      });
    });

    root.querySelectorAll('[data-action="save-sub-modal"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._savePrescriptionSubModal();
      });
    });

    // beta3.6: weekday chip click — toggle the day's membership in
    // draft.daysOfWeek, then re-render so the chip's active class
    // and any matched preset's highlight update.
    root.querySelectorAll('[data-action="weekday-toggle"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        if (!this._personSubModal) return;
        const draft = this._personSubModal.draft;
        const idx = String(e.currentTarget.dataset.dayIndex);
        if (draft.daysOfWeek.has(idx)) {
          draft.daysOfWeek.delete(idx);
        } else {
          draft.daysOfWeek.add(idx);
        }
        this._render();
      });
    });

    // beta3.6: weekday preset button — overwrite draft.daysOfWeek
    // with the preset's day set, then re-render. Subsequent chip
    // taps customize from there.
    root.querySelectorAll('[data-action="weekday-preset"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        if (!this._personSubModal) return;
        const draft = this._personSubModal.draft;
        const preset = e.currentTarget.dataset.preset;
        const PRESETS = {
          "every-day": ["0", "1", "2", "3", "4", "5", "6"],
          "weekdays": ["0", "1", "2", "3", "4"],
          "weekends": ["5", "6"],
        };
        draft.daysOfWeek = new Set(PRESETS[preset] || []);
        this._render();
      });
    });

    // Sub-modal field inputs — update _personSubModal.draft. Frequency
    // changes re-render so the conditional sections show/hide. Multiple
    // controls can share a data-sub-field (e.g. remind_window has both
    // a slider and a number input bound to the same value); dragging
    // one updates the other so they stay in visual sync.
    root.querySelectorAll("[data-sub-field]").forEach((el) => {
      const field = el.dataset.subField;
      const eventName = el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input";
      el.addEventListener(eventName, (e) => {
        if (!this._personSubModal) return;
        const draft = this._personSubModal.draft;
        if (field === "usePerWeekday") {
          // Times-mode picker (radios). Switching modes is lossless:
          // both draft.times (single field) and draft.timesPerWeekday
          // (7-row array) stay alive in the draft regardless of which
          // mode is active. On save, prescriptionToWire decides which
          // one persists based on draft.usePerWeekday. Only seed the
          // 7 rows from draft.times on first switch to per-weekday
          // (when timesPerWeekday is empty) so the user has a sensible
          // starting point — subsequent switches preserve what's there.
          const mode = e.currentTarget.dataset.mode;
          draft.usePerWeekday = mode === "perWeekday";
          if (draft.usePerWeekday) {
            const empty =
              !Array.isArray(draft.timesPerWeekday) ||
              draft.timesPerWeekday.every((row) => !row || !String(row).trim());
            if (empty) {
              const flat = (draft.times || "").trim();
              draft.timesPerWeekday = [flat, flat, flat, flat, flat, flat, flat];
            }
          }
          this._render();
        } else if (field === "timesPerWeekday") {
          // Per-weekday row input. data-day-index identifies which
          // weekday slot to write to (0=Mon..6=Sun).
          const idx = parseInt(e.currentTarget.dataset.dayIndex, 10);
          if (!Array.isArray(draft.timesPerWeekday)) {
            draft.timesPerWeekday = ["", "", "", "", "", "", ""];
          }
          if (idx >= 0 && idx <= 6) {
            draft.timesPerWeekday[idx] = e.currentTarget.value;
          }
        } else if (field === "variant_select") {
          // v0.2.13: variant dropdown. Value is either "{strength}|{form}"
          // for a real catalog variant, "__current__" for the
          // synthetic "(current)" placeholder (no-op, keeps draft
          // strength/form as-is), or "__custom__" to flip into the
          // two-text-field free-text path.
          const value = e.currentTarget.value;
          if (value === "__custom__") {
            draft.variant_custom = true;
            this._render();
          } else if (value === "__current__") {
            // no-op — keeps existing variant_strength/form
          } else {
            const [strength, form] = value.split("|");
            draft.variant_strength = strength || "";
            draft.variant_form = form || "";
            draft.variant_npl_id = "";
            this._render();
          }
        } else {
          const value = e.currentTarget.value;
          draft[field] = value;
          // Push the new value to any sibling control bound to the
          // same field. Skips identical-value writes so we don't churn
          // the cursor in a number input while typing.
          root
            .querySelectorAll(`[data-sub-field="${field}"]`)
            .forEach((other) => {
              if (other !== e.currentTarget && other.value !== value) {
                other.value = value;
              }
            });
          if (field === "frequency") {
            this._render();
          }
        }
      });
    });
  }

  _renderFull(meds) {
    const allDoses = this._flattenTodayDoses(meds);
    const personGroups = this._groupTodayDosesByPerson(meds);
    const medGroups = this._groupByPerson(meds);
    const dateStr = this._formatDate(new Date());
    const doseCount = allDoses.length;
    const subtitle = `${dateStr} · ${doseCount} dose${doseCount === 1 ? "" : "s"} scheduled today`;

    return `
      <div class="container">
        <header>
          <div>
            <h1>PillPilot</h1>
            <p class="subtitle">${escapeHtml(subtitle)}</p>
          </div>
          <div class="header-actions">
            <button class="config-btn" data-action="open-config" aria-label="Configure integration" title="Configure integration">⚙</button>
            <div class="kebab-wrapper">
              <button class="config-btn" data-action="toggle-kebab" data-person-key="global" aria-label="More actions" title="More actions">⋮</button>
              <div class="kebab-menu" data-kebab-for="global">
                <button data-action="backfill-from-catalog">Backfill empty fields from catalog</button>
              </div>
            </div>
            <button class="add-btn" data-action="add">+ Add medicine</button>
          </div>
        </header>
        ${personGroups.length > 0 ? this._renderTodaySection(personGroups) : ""}
        ${medGroups.map(([_, g]) => this._renderPersonSection(g)).join("")}
      </div>
    `;
  }

  // Today's doses is now a card containing one collapsible
  // section per person (and one for "Household" doses, if any).
  // Each section has its own [Take all] [Take due] [⋮] action buttons
  // scoped to that person's doses only — no global bulk action header.
  // The kebab menu holds [Take missed today] and [Undo last action].
  _renderTodaySection(personGroups) {
    return `
      <section class="today-section">
        <div class="section-header">
          <span>Today's doses</span>
        </div>
        ${personGroups.map((g) => this._renderPersonDosesSection(g)).join("")}
      </section>
    `;
  }

  _renderPersonDosesSection(group) {
    const { personKey, personName, doses } = group;
    const personIdAttr = escapeHtml(personKey);

    // Counts for status summary + button enable/disable. Done in one
    // pass over doses to avoid five repeated scans.
    let dueCount = 0,
      missedCount = 0,
      upcomingCount = 0,
      takenCount = 0,
      skippedCount = 0,
      snoozedCount = 0;
    for (const d of doses) {
      if (d.status === STATE_DUE) dueCount++;
      else if (d.status === STATE_MISSED) missedCount++;
      else if (d.status === STATE_UPCOMING) upcomingCount++;
      else if (d.status === STATE_TAKEN) takenCount++;
      else if (d.status === STATE_SKIPPED) skippedCount++;
      else if (d.status === STATE_SNOOZED) snoozedCount++;
    }
    const nonTakenCount = dueCount + missedCount + upcomingCount + snoozedCount;
    const expanded = this._isPersonExpanded(personKey, nonTakenCount > 0);
    const arrow = expanded ? "▼" : "▶";

    // Status summary — short and human. Priority order: due > missed
    // > snoozed > upcoming > all-taken.
    let summary;
    if (dueCount > 0) {
      summary = `${dueCount} due`;
    } else if (missedCount > 0) {
      summary = `${missedCount} missed`;
    } else if (snoozedCount > 0) {
      summary = `${snoozedCount} snoozed`;
    } else if (upcomingCount > 0) {
      summary = `${upcomingCount} upcoming`;
    } else if (doses.length > 0 && takenCount === doses.length - skippedCount) {
      summary = "all taken";
    } else {
      summary = `${doses.length} dose${doses.length === 1 ? "" : "s"}`;
    }

    const hasUndo = (this._lastActionMap[personKey] || []).length > 0;

    // Disabled flags. The "[Take all]" button covers due+upcoming+missed+snoozed,
    // so it's enabled when any of those are present. "[Take due]" only
    // enabled when there's at least one due. Kebab items each have
    // their own enabled-when conditions.
    const disableTakeAll = nonTakenCount === 0;
    const disableTakeDue = dueCount === 0;
    const disableTakeMissed = missedCount === 0;
    const disableUndo = !hasUndo;

    return `
      <div class="person-doses-section" data-person-key="${personIdAttr}">
        <div class="person-doses-header">
          <button class="person-toggle" data-action="toggle-person" data-person-key="${personIdAttr}">
            <span class="collapse-arrow">${arrow}</span>
            <span class="person-name">${escapeHtml(personName)}</span>
            <span class="person-summary">· ${doses.length} dose${doses.length === 1 ? "" : "s"} · ${escapeHtml(summary)}</span>
          </button>
          <div class="person-actions">
            <button class="bulk-action-btn" data-action="take-all-person" data-person-key="${personIdAttr}" ${disableTakeAll ? "disabled" : ""}>Take all</button>
            <button class="bulk-action-btn" data-action="take-due-person" data-person-key="${personIdAttr}" ${disableTakeDue ? "disabled" : ""}>Take due</button>
            <div class="kebab-wrapper">
              <button class="kebab-btn" data-action="toggle-kebab" data-person-key="${personIdAttr}" aria-label="More actions">⋮</button>
              <div class="kebab-menu" data-kebab-for="${personIdAttr}">
                <button data-action="take-missed-person" data-person-key="${personIdAttr}" ${disableTakeMissed ? "disabled" : ""}>Take missed today</button>
                <button data-action="snooze-due-person" data-person-key="${personIdAttr}" ${disableTakeDue ? "disabled" : ""}>Snooze all due (15m)</button>
                <button data-action="snooze-missed-person" data-person-key="${personIdAttr}" ${disableTakeMissed ? "disabled" : ""}>Snooze all missed (15m)</button>
                <button data-action="undo-person" data-person-key="${personIdAttr}" ${disableUndo ? "disabled" : ""}>Undo last action</button>
              </div>
            </div>
          </div>
        </div>
        ${
          expanded
            ? `
          <div class="person-doses-body">
            ${doses.map((d) => this._renderDoseRow(d)).join("")}
          </div>
        `
            : ""
        }
      </div>
    `;
  }

  _renderDoseRow(d) {
    const personLabel = d.personName ? escapeHtml(d.personName) : "Household";
    const actionsHtml = this._renderRowActions(d);
    // respect HA's user Time format preference. Previously
    // d.time was rendered raw (always 24h "HH:MM" from the sensor).
    const timeStr = this._formatTime(d.time);
    return `
      <div class="dose-row">
        <div class="dose-time">${escapeHtml(timeStr)}</div>
        <div>
          <div class="dose-name">${escapeHtml(d.name)}</div>
          ${d.dose ? `<div class="dose-detail">${escapeHtml(d.dose)}</div>` : ""}
        </div>
        <div class="dose-person">${personLabel}</div>
        ${actionsHtml}
      </div>
    `;
  }

  _renderRowActions(d) {
    if (d.status === STATE_TAKEN) {
      const at = this._formatActionTime(d.actionAt);
      const sched = escapeHtml(d.scheduledAt || "");
      const medId = escapeHtml(d.medicineId);
      // hover-to-undo. The wrapper holds the green Taken
      // badge and a hidden red Undo button at the same position;
      // hovering swaps them via CSS. Click on the Undo button fires
      // pillpilot.unmark_taken for this exact slot.
      return `
        <div class="dose-taken-wrapper">
          <div class="dose-status-label taken">✓ Taken${at ? ` at ${escapeHtml(at)}` : ""}</div>
          <button class="dose-undo-btn" data-action="undo-dose" data-medicine-id="${medId}" data-scheduled-at="${sched}">Undo</button>
        </div>
      `;
    }
    if (d.status === STATE_SKIPPED) {
      const at = this._formatActionTime(d.actionAt);
      return `<div class="dose-status-label skipped">⊘ Skipped${at ? ` at ${escapeHtml(at)}` : ""}</div>`;
    }
    if (d.status === STATE_SNOOZED) {
      // Snooze surfaces the elapse time (action_at carries snoozed_until)
      // alongside Take/Skip so the user can override their own snooze.
      // Once snoozed_until elapses the slot flips back to due/missed
      // automatically — the panel re-renders on the next sensor tick.
      const until = this._formatActionTime(d.actionAt);
      const sched = escapeHtml(d.scheduledAt || "");
      const medId = escapeHtml(d.medicineId);
      return `
        <div class="dose-snoozed-wrapper">
          <div class="dose-status-label snoozed">⏰ Snoozed${until ? ` until ${escapeHtml(until)}` : ""}</div>
          <div class="dose-actions">
            <button class="dose-action-btn take" data-action="take" data-medicine-id="${medId}" data-scheduled-at="${sched}">Take</button>
            <button class="dose-action-btn skip" data-action="skip" data-medicine-id="${medId}" data-scheduled-at="${sched}">Skip</button>
          </div>
        </div>
      `;
    }
    if (ACTIONABLE.has(d.status)) {
      const sched = escapeHtml(d.scheduledAt || "");
      const medId = escapeHtml(d.medicineId);
      return `
        <div class="dose-actions">
          <button class="dose-action-btn take" data-action="take" data-medicine-id="${medId}" data-scheduled-at="${sched}">Take</button>
          <button class="dose-action-btn snooze" data-action="snooze" data-medicine-id="${medId}" data-scheduled-at="${sched}">Snooze</button>
          <button class="dose-action-btn skip" data-action="skip" data-medicine-id="${medId}" data-scheduled-at="${sched}">Skip</button>
        </div>
      `;
    }
    return `<div class="dose-status-label">${escapeHtml(d.status)}</div>`;
  }

  _renderPersonSection(group) {
    // header has a Cards / List toggle. The toggle is global
    // (controls _medsView for all person sections), but the button
    // lives in each section header so the user always has it in reach
    // without scrolling. Active mode is highlighted; clicking the
    // inactive button flips _medsView and re-renders.
    //
    // Phase 3 (multi-prescription): group.items is a list of
    // {med, prescription} pairs already sorted by _groupByPerson per
    // the user's selected sort. No additional sort pass here.
    const cardsActive = this._medsView !== "list";
    const listActive = this._medsView === "list";
    const items = group.items;
    const body = listActive
      ? `<div class="med-list">${this._renderMedListHeader()}${items
          .map((item) => this._renderMedListRow(item))
          .join("")}</div>`
      : `<div class="med-grid">${items
          .map((item) => this._renderMedCard(item))
          .join("")}</div>`;
    // Dropdown only appears in cards mode — list mode has its own
    // clickable column headers and an additional dropdown would just
    // be visual noise.
    const sortControl = cardsActive ? this._renderSortDropdown() : "";
    return `
      <section class="person-section">
        <div class="person-section-header">
          <h3>${escapeHtml(group.label)} · ${items.length}</h3>
          <div class="header-controls">
            ${sortControl}
            <div class="view-toggle" role="group" aria-label="Medicine list view">
              <button class="view-toggle-btn ${cardsActive ? "active" : ""}" data-action="set-meds-view" data-view="cards" aria-pressed="${cardsActive}">Cards</button>
              <button class="view-toggle-btn ${listActive ? "active" : ""}" data-action="set-meds-view" data-view="list" aria-pressed="${listActive}">List</button>
            </div>
          </div>
        </div>
        ${body}
      </section>
    `;
  }

  // card-view sort dropdown. Each <option> encodes both the
  // column AND the direction in a single value string ("name:asc",
  // "last_taken:desc"). That keeps it one control instead of two,
  // and the visible label spells out the direction so it's obvious.
  _renderSortDropdown() {
    const current = `${this._sortBy}:${this._sortDir}`;
    const opt = (value, label) =>
      `<option value="${value}" ${current === value ? "selected" : ""}>${escapeHtml(label)}</option>`;
    return `
      <select class="sort-select" data-action="sort-set" aria-label="Sort medicines">
        ${opt("name:asc", "Sort: Name (A–Z)")}
        ${opt("name:desc", "Sort: Name (Z–A)")}
        ${opt("status:asc", "Sort: Status (due first)")}
        ${opt("next:asc", "Sort: Next dose (soonest)")}
        ${opt("last_taken:desc", "Sort: Last taken (recent)")}
      </select>
    `;
  }

  // list-view sortable column headers. Three columns are
  // sortable (Name, Schedule, Last taken); Status and Dose render as
  // static labels — Status sorting is available via the dropdown if
  // someone really wants it, and Dose has no meaningful natural
  // ordering ("1 pill × 5 mg" < "1 pill × 100 mg" alphabetically
  // would be misleading). Active column shows a direction arrow.
  _renderMedListHeader() {
    const cell = (key, label) => {
      const active = this._sortBy === key;
      const arrow = active ? (this._sortDir === "asc" ? " ▲" : " ▼") : "";
      return `<button class="sort-header ${active ? "active" : ""}" data-action="sort-toggle" data-sort="${escapeHtml(key)}">${escapeHtml(label)}${arrow}</button>`;
    };
    return `
      <div class="med-list-row med-list-header">
        ${cell("name", "Name")}
        <span class="sort-header sort-header-static">Status</span>
        <span class="sort-header sort-header-static">Dose</span>
        ${cell("next", "Schedule")}
        ${cell("last_taken", "Last taken")}
        <span></span>
      </div>
    `;
  }

  _renderMedCard(item) {
    // Phase 3: takes a {med, prescription} pair. State pill, dose,
    // schedule, and last-taken come from the prescription (per-
    // prescription view). Name/notes/medicine-id come from the
    // medicine (shared across prescriptions).
    const { med, prescription } = item;
    const a = med.attributes;
    const labelInfo = STATE_LABELS[prescription.state] || {
      text: prescription.state || "",
      kind: "neutral",
    };
    const lastTaken = this._formatRelative(prescription.last_taken_at);
    // _formatSchedule reads scheduled_times/frequency/scheduled_days/
    // scheduled_days_of_month — same field names on the prescription
    // dict as on the flat med.attributes, so we pass it directly.
    const sched = this._formatSchedule(prescription);
    const name = a.medicine_name || a.friendly_name || med.entity_id;
    const medId = escapeHtml(a.medicine_id);
    const note = (a.notes || "").trim();
    return `
      <div class="med-card">
        <div class="med-header">
          <span class="med-name">${escapeHtml(name)}</span>
          <span class="pill pill-${labelInfo.kind}">${escapeHtml(labelInfo.text)}</span>
        </div>
        ${prescription.dose ? `<div class="med-dose">${escapeHtml(prescription.dose)}</div>` : ""}
        <div class="med-meta">${escapeHtml(sched)}</div>
        <div class="med-meta">Last taken: ${escapeHtml(lastTaken)}</div>
        ${note ? `<div class="med-note">${escapeHtml(note)}</div>` : ""}
        <div class="med-footer">
          <button class="med-edit-btn" data-action="edit" data-medicine-id="${medId}">Edit</button>
        </div>
      </div>
    `;
  }

  // Compact one-line-per-prescription alternative to _renderMedCard.
  // Same data, just laid out horizontally in a grid row. Notes are
  // omitted at this density — they'd push everything out of the row.
  _renderMedListRow(item) {
    const { med, prescription } = item;
    const a = med.attributes;
    const labelInfo = STATE_LABELS[prescription.state] || {
      text: prescription.state || "",
      kind: "neutral",
    };
    const lastTaken = this._formatRelative(prescription.last_taken_at);
    const sched = this._formatSchedule(prescription);
    const name = a.medicine_name || a.friendly_name || med.entity_id;
    const medId = escapeHtml(a.medicine_id);
    return `
      <div class="med-list-row">
        <div class="med-list-name">${escapeHtml(name)}</div>
        <span class="pill pill-${labelInfo.kind}">${escapeHtml(labelInfo.text)}</span>
        <div class="med-list-meta">${escapeHtml(prescription.dose || "—")}</div>
        <div class="med-list-meta">${escapeHtml(sched)}</div>
        <div class="med-list-meta">${escapeHtml(lastTaken)}</div>
        <button class="med-edit-btn" data-action="edit" data-medicine-id="${medId}">Edit</button>
      </div>
    `;
  }

  _wireListeners() {
    const root = this.shadowRoot;
    root.querySelectorAll('[data-action="take"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const t = e.currentTarget;
        this._markTaken(t.dataset.medicineId, t.dataset.scheduledAt);
      });
    });
    root.querySelectorAll('[data-action="skip"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const t = e.currentTarget;
        this._skip(t.dataset.medicineId, t.dataset.scheduledAt);
      });
    });
    root.querySelectorAll('[data-action="snooze"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const t = e.currentTarget;
        this._snooze(t.dataset.medicineId, t.dataset.scheduledAt);
      });
    });
    // per-dose hover-undo button (visible only on hover over
    // the green Taken badge).
    root.querySelectorAll('[data-action="undo-dose"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const t = e.currentTarget;
        this._unmarkTaken(t.dataset.medicineId, t.dataset.scheduledAt);
      });
    });
    // per-person collapsible header toggle.
    root.querySelectorAll('[data-action="toggle-person"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._togglePersonCollapse(e.currentTarget.dataset.personKey);
      });
    });
    // per-person bulk actions.
    root.querySelectorAll('[data-action="take-all-person"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        if (e.currentTarget.disabled) return;
        this._takeAllForPerson(e.currentTarget.dataset.personKey);
      });
    });
    root.querySelectorAll('[data-action="take-due-person"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        if (e.currentTarget.disabled) return;
        this._takeDueForPerson(e.currentTarget.dataset.personKey);
      });
    });
    root.querySelectorAll('[data-action="take-missed-person"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.currentTarget.disabled) return;
        this._takeMissedForPerson(e.currentTarget.dataset.personKey);
        // Close the kebab menu after the action fires.
        this._toggleKebab(e.currentTarget.dataset.personKey);
      });
    });
    root.querySelectorAll('[data-action="snooze-due-person"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.currentTarget.disabled) return;
        this._snoozeAllDueForPerson(e.currentTarget.dataset.personKey);
        this._toggleKebab(e.currentTarget.dataset.personKey);
      });
    });
    root.querySelectorAll('[data-action="snooze-missed-person"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.currentTarget.disabled) return;
        this._snoozeAllMissedForPerson(e.currentTarget.dataset.personKey);
        this._toggleKebab(e.currentTarget.dataset.personKey);
      });
    });
    root.querySelectorAll('[data-action="undo-person"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.currentTarget.disabled) return;
        this._undoLastForPerson(e.currentTarget.dataset.personKey);
        this._toggleKebab(e.currentTarget.dataset.personKey);
      });
    });
    root.querySelectorAll('[data-action="toggle-kebab"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._toggleKebab(e.currentTarget.dataset.personKey);
      });
    });
    root.querySelectorAll('[data-action="backfill-from-catalog"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._backfillFromCatalog();
      });
    });
    // Old global "Mark X due" button is gone in v0.2.17 — actions are
    // now per-person. The old [data-action="mark-all-due"] hook stays
    // here as a no-op for safety in case anything in the wild still
    // emits it; new render path doesn't produce the button anymore.
    root.querySelectorAll('[data-action="edit"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._editMedicine(e.currentTarget.dataset.medicineId);
      });
    });
    // Cards / List view toggle in each person-section header.
    // Global mode — clicking either button anywhere flips _medsView for
    // every person section.
    root.querySelectorAll('[data-action="set-meds-view"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._setMedsView(e.currentTarget.dataset.view);
      });
    });
    // card-view sort dropdown. Value is "by:dir".
    root.querySelectorAll('[data-action="sort-set"]').forEach((sel) => {
      sel.addEventListener("change", (e) => {
        this._setSort(e.currentTarget.value);
      });
    });
    // list-view sortable column headers. Click toggles
    // direction on the same column or switches to a new column at asc.
    root.querySelectorAll('[data-action="sort-toggle"]').forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._toggleSort(e.currentTarget.dataset.sort);
      });
    });
    root.querySelectorAll('[data-action="add"]').forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        this._openAddModal();
      });
    });
    root.querySelectorAll('[data-action="open-config"]').forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        // HA's SPA router listens for `location-changed` events on
        // window. Pushing to history alone doesn't trigger the route
        // swap — the event is what makes the navigation happen
        // without a full page reload. Pattern is documented for
        // custom panels and used by lovelace itself.
        const target = "/config/integrations/integration/pillpilot";
        history.pushState(null, "", target);
        window.dispatchEvent(
          new CustomEvent("location-changed", { composed: true, bubbles: true })
        );
      });
    });
  }
}

// Helper to safely insert a string as a CSS attribute selector value.
// Used by _toggleKebab when searching for the right kebab menu by
// person-key. Persons are real entity_ids ("person.alice"), so the
// dot would otherwise read as a class selector. This is a tiny
// implementation — sufficient for entity-id-shaped strings; for full
// CSS.escape compliance we'd polyfill.
function cssEscape(s) {
  if (CSS && typeof CSS.escape === "function") return CSS.escape(s);
  return String(s).replace(/([^a-zA-Z0-9_-])/g, "\\$1");
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

customElements.define("pillpilot-panel", PillPilotPanel);
