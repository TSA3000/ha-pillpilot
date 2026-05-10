# v0.2.9

> Medicine list rebuilt from Läkemedelsverket. Drop-in upgrade from 0.2.8.

## What's new

`medicines_se.json` is now generated from [Läkemedelsverket's open-data register](https://www.dataportal.se/datasets/140_5467) (Sök läkemedelsfakta, dataset 140_5467) instead of being hand-curated. 216 entries → 7331. Covers every human medicine currently `Godkänd` or `Registrerad`. Veterinary and deregistered products are filtered at build time. Snapshot 2026-05-10.

Each entry now carries `npl_id`, and `aliases` includes former product names from the `Tidigare läkemedelsnamn` column — searching an old brand name finds the current entry.

## Build tool

`tools/build_medicines_se.py` regenerates the JSON from a fresh `Lakemedelsprodukter.xlsx` export. Maintainer tool — not shipped in the integration zip.

```
pip install openpyxl
python tools/build_medicines_se.py \
    --input ~/Downloads/Lakemedelsprodukter.xlsx \
    --output custom_components/pillpilot/medicines_se.json
```

Curated aliases on existing entries are preserved across rebuilds.

## Upgrading

Replace the `pillpilot` directory in `custom_components/` with the contents of this zip and restart Home Assistant. HACS users: update normally. Existing medicines are unaffected.

ATC codes come straight from Läkemedelsverket. Still verify against FASS or Sök VARA before relying on them clinically.
