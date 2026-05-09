# Privacy

PillPilot stores everything locally on your Home Assistant instance. Nothing leaves the box unless you explicitly send it somewhere — a backup destination, a notification service, an exposed sensor read by another app. That's a real privacy advantage over cloud-based medication trackers, but it isn't the same as "encrypted." The data sits plaintext on disk. A few specifics worth knowing before you decide how much to put in.

## What's stored, where

- **Medicine config** (name, type, dose, schedule, person assignment, optional notes, ATC code / NPL ID / varunummer if set) — `<config>/.storage/core.config_entries`. Plaintext JSON.
- **Dose history** (taken / skipped / snoozed / missed events with timestamps) — `<config>/.storage/pillpilot.history`. Plaintext JSON.
- **Sensor state and attributes** — exposed to Home Assistant's state machine. Recorded to `<config>/home-assistant_v2.db` by the `recorder` integration, included in HA backups, and queryable via the History tab, Developer Tools, the `history` template functions, and the REST API.

## Who can read it

- **Anyone with a Home Assistant login** — admin or not — can see the entity list, current state, attributes, and history graphs of every PillPilot sensor. The non-admin flag in HA gates configuration, not entity visibility. A non-admin household member sharing your HA instance sees `sensor.levaxin` and its history without elevation.
- **Any HA admin** can additionally read all subentry config data via the integrations UI and reconfigure flows.
- **Anyone with file-system access to the HA config directory** sees everything. This includes backup destinations: HA Cloud, local snapshots, NAS shares, cloud sync targets (Google Drive, OneDrive, iCloud, etc.) wherever you've pointed your backup pipeline.

## What gets exposed to the recorder

If your HA instance is shared, here's what other users can see today via the History tab and Developer Tools without any elevation:

- The list of medicines, via entity names like `sensor.levaxin`.
- Whose medicine each one is, via device names like `Sam's Medicines`.
- Dose schedule, last taken time, free-text notes, and identifiers (ATC / NPL / varunummer) in the entity attributes.
- Per-dose history (state changes timestamped) if the recorder is on (default).

The medicine name in particular is set when the sensor is first created and shows up in:

- `entity_id` (e.g. `sensor.levaxin`)
- `friendly_name` (e.g. `Sam's Medicines Levaxin`)
- the `medicine_name` attribute
- the `prescriptions[]` attribute (full per-prescription dump)
- the recorder's state log on every state change
- HA backups containing the recorder DB

## What you can do

### Encrypt your backups

Biggest single fix. HA's backup system supports passphrase-encrypted archives; turn it on if you back up anywhere except a fully-trusted local disk. A backup landing in cloud storage without encryption is the realistic leak vector for most installs.

### Filesystem-level encryption on the host

LUKS (Linux), BitLocker (Windows), FileVault (macOS), or HAOS's full-disk encryption. Protects against physical theft and disk-image leak.

### Limit who has admin

Other HA admins see all subentry data regardless of any other setting in the integration. Non-admin users on a shared HA instance still see entities and history — admin scope only affects configuration access.

### Exclude PillPilot from the recorder

If you don't need the in-HA history graph (the panel keeps its own dose history independently), exclude PillPilot sensors from the recorder. Add to `configuration.yaml`:

```yaml
recorder:
  exclude:
    entities:
      - sensor.<your_medicine_name_1>
      - sensor.<your_medicine_name_2>
```

The `entities` list is the precise option — list each PillPilot sensor by entity_id. Doses still get tracked inside PillPilot; only HA's recorder DB stops storing the state changes and attributes.

If you'd rather not maintain that list as you add medicines, you can use a glob pattern, but only if your other sensors don't share the prefix:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.<some_distinctive_prefix>_*
```

There's no built-in way to exclude only specific attributes from the recorder while keeping the entity recorded. It's all or nothing per entity.

### Be careful with notifications

The `notify_dose` blueprint includes the medicine name in the notification body by default. If your phone shows notification previews on the lock screen, the medicine name is visible there. Either disable lock-screen previews on your device, or customize the blueprint's notification template to use a less-revealing string.

### Be careful with voice assistants

If you've exposed PillPilot entities to Google Assistant, Alexa, or HA's local voice assistant, anyone in earshot can ask about them. Unexpose PillPilot entities specifically if that's a concern.

## What PillPilot doesn't do

The integration doesn't encrypt its own storage. There are two reasons for this and they're worth being honest about:

**Unattended boot.** HA starts on its own — after a power cycle, after an OS update, after a server reboot. The PillPilot coordinator has to come up without human intervention to compute "what's due now," fire reminders, and update sensors. A passphrase-on-boot scheme would block all of that until someone manually unlocked the integration, which defeats the integration's purpose.

**Key location.** The only place an unattended-boot integration can store its key is the same disk as its data. An attacker with file-system access reads the data and the key. Encrypting under those conditions adds runtime cost and complexity without changing the threat model — and worse, gives users a false sense of protection that isn't there.

There are scenarios where integration-level encryption could work — dedicated TPM hardware on a known HA platform with a stable secret-store API, for instance — but those scenarios don't generalize across the four HA install types (HAOS, Container, Supervised, Core) the integration has to support. The honest position is local-first plus the mitigations above, not bolted-on crypto that overpromises.

## What this means for shared installs

If your HA instance is shared with a partner, family member, roommate, or kid, the realistic threat model is:

- They can see all your meds and schedules without elevation.
- They can see when you took (or didn't take) doses if the recorder is on.
- They can see your free-text notes.
- They can mute or alter notifications via HA automations if they have admin.

If any of those is a problem for you, this integration may not be the right fit until per-user data isolation is added at the Home Assistant platform level — which is a Home Assistant core gap, not a PillPilot one.
