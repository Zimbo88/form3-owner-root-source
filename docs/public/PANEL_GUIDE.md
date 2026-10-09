# Owner panel: live pages and consumable workflows

These are original screenshots of **the actual installed 0.5.15-review panel**,
opened directly over its owner LAN connection on 2026-10-09. A fresh Firefox profile
was used. Private hostname, IP/MAC addresses, consumable identifiers and backup
hashes were obscured in the browser before capture. Numeric observations were not
replaced with demo data. The conservative identifier filter also obscured a long
fractional digit sequence in two captures; that is redaction, not a missing device
reading. PNG metadata was removed before publication.

**No consumable write, vendor service restart, print or printer reboot was used
to make these screenshots.** Source labels such as LIVE, CACHED, HISTORICAL and
UNAVAILABLE belong to each observation; a live screenshot can contain cached data.
The [acceptance receipt](consumable_panel_acceptance.json) separates the real
read-only workflows from fixture-tested write paths.

Use **Materials → Review cartridge reset** for backups, usage and material
previews. Keep power connected and follow the typed confirmation/idle/version
gates before any independently intended write. This guide is not permission to
copy another consumable’s identity or turn an unknown format into a supported one.
[Scope and recovery](CONSUMABLE_BACKUPS.md) and [tank findings](TANK_DATA.md) are
part of the workflow. Click images for full resolution; long dialogs/pages scroll.

The separate [synthetic fixture gallery](PANEL_FIXTURE_GUIDE.md) shows isolated
write/rollback UI scenarios that were **not executed on consumables for this
release review**. It must not be mistaken for live write acceptance.

## Overview

Firmware/slot, uptime, CPU activity, memory, cached printer state and tank-level observation. A CACHED label is retained; idle is not a safety clearance.

![Live panel; private identifiers redacted: Overview](assets/panel-live-0.5.15/status-LIVE.png)

## Sensors

Five live SoC temperature channels plus supplied historical print/heater observations. GPU temperature is not GPU utilization; unavailable channels stay unavailable.

![Live panel; private identifiers redacted: Sensors](assets/panel-live-0.5.15/sensors-LIVE.png)

## Materials and refill notes

Reported cartridge/tank material, estimated cartridge remaining volume and the last saved tank level. The level in mm is not a measured tank volume. Owner refill notes are separate from native usage; they do not reset counters or inhibit dispensing.

![Live panel; private identifiers redacted: Materials and refill notes](assets/panel-live-0.5.15/materials-LIVE.png)

## Print history

Prepared/recovered metadata with private job names and identifiers excluded by the adapter. A record is not proof of a complete printable payload or successful print.

![Live panel; private identifiers redacted: Print history](assets/panel-live-0.5.15/jobs-LIVE.png)

## Diagnostics

Local summaries and bounded export controls. Sanitize exports before sharing. The full-log option requires explicit authentication and excludes key stores. This capture did not create or publish a private log export.

![Live panel; private identifiers redacted: Diagnostics](assets/panel-live-0.5.15/diagnostics-LIVE.png)

## Network and SSH

Current listener interface, transport and ports. HTTP is plaintext. The current fingerprint adapter is unavailable; that does not mean the already-enrolled SSH access is absent.

![Live panel; private identifiers redacted: Network and SSH](assets/panel-live-0.5.15/network-LIVE.png)

## Preferences and capabilities

Owner preferences are separate from vendor settings, license issuance and device identity. Disabled vendor operations remain disabled. No preferences were changed while taking these screenshots.

![Live panel; private identifiers redacted: Preferences and capabilities](assets/panel-live-0.5.15/settings-LIVE.png)

## Privacy

An owner policy preference and dependency preview, not a verified applied vendor privacy policy. No manufacturer-facing status is falsified.

![Live panel; private identifiers redacted: Privacy](assets/panel-live-0.5.15/privacy-LIVE.png)

## Maintenance

Current version, source boundaries and disabled power controls. An unavailable safe-idle backend is not replaced by a guessed value.

![Live panel; private identifiers redacted: Maintenance](assets/panel-live-0.5.15/maintenance-LIVE.png)

## Narrow viewport

The live layout at the browser’s narrow viewport. The test checked horizontal overflow; this is not a claim about every phone/browser.

![Live panel; private identifiers redacted: Narrow viewport](assets/panel-live-0.5.15/mobile-LIVE.png)

## Authentication for privileged actions

The consumable workflow requires owner login even when ordinary WLAN viewing is configured without login. The access-secret field is empty in this screenshot.

![Live panel; private identifiers redacted: Authentication for privileged actions](assets/panel-live-0.5.15/authentication-LIVE.png)

## Cartridge backup

Two stable main-memory reads, checksums and persistent-mirror projection; the actual private backup is stored on the printer and was copied privately to the laptop.

![Live panel; private identifiers redacted: Cartridge backup](assets/panel-live-0.5.15/backup-cartridge-LIVE.png)

## Tank backup

The separate 512-byte T/65 codec verifies RO and both RW records. No tank EEPROM programming or daemon restart occurs during backup.

![Live panel; private identifiers redacted: Tank backup](assets/panel-live-0.5.15/backup-tank-LIVE.png)

## Saved backups

Lists retained snapshots. Cartridge usage restoration is restricted to the same physical cartridge and material. Tank restore is visibly disabled; a backup is not proof of an implemented restore.

![Live panel; private identifiers redacted: Saved backups](assets/panel-live-0.5.15/backups-LIVE.png)

## Cartridge usage preview

Actual current before/after plan, including the monotonic write counter. This screenshot is a preview: the apply button was not pressed and the cartridge was not reset for the review.

![Live panel; private identifiers redacted: Cartridge usage preview](assets/panel-live-0.5.15/usage-preview-LIVE.png)

## Material catalog

Only explicit public Form 3 entries from the installed catalog are offered. Catalog membership does not establish chemical compatibility of third-party resin. Tank material programming remains unavailable.

![Live panel; private identifiers redacted: Material catalog](assets/panel-live-0.5.15/material-catalog-LIVE.png)

## Material assignment preview

A real read-only proposed cartridge material change, with current identity and usage preserved by the generator. The different target shown was never applied. The workflow was finally returned to the already-matching current material.

![Live panel; private identifiers redacted: Material assignment preview](assets/panel-live-0.5.15/material-preview-LIVE.png)

## Usage restore preview

A real read-only plan from a saved same-cartridge backup. Native EEPROM volume has 0.1 mL resolution. Restore planning uses that decoded value; it does not transplant another cartridge’s image. Apply was not invoked.

![Live panel; private identifiers redacted: Usage restore preview](assets/panel-live-0.5.15/restore-preview-LIVE.png)

## Already-matching material

Final no-op request for the currently reported material. No EEPROM write or service restart is required, and no actionable write plan is left selected.

![Live panel; private identifiers redacted: Already-matching material](assets/panel-live-0.5.15/material-noop-LIVE.png)
