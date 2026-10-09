# Panel fixture gallery (synthetic)

These are **real Firefox screenshots of the authored 0.5.14 interface**, captured
in a disposable, network-isolated browser with synthetic data and credentials.
They are not mock-up drawings, photographs of the successful print, or proof of
hardware acceptance. DEMO/SYNTHETIC labels remain in the filenames and captions.
No private browser profile, owner access secret, device identity or job payload
was used. Images were re-encoded without metadata before publication.

Reproduce with [the browser fixture](../../tools/test_panel_browser.py). It needs
the documented local Firefox/bubblewrap environment; it is not a public CI or
hardware test. Click an image for its full resolution. The
[consumable guide](CONSUMABLE_BACKUPS.md) explains prerequisites and recovery.

## Login

An actual login form, captured before entering the synthetic test credential. No shared production password is distributed.

![DEMO/SYNTHETIC: Login](assets/panel-0.5.14/login-DEMO.png)

## Overview

Version/slot, uptime, load/RAM and printer observations. Every value carries a source/freshness state; fixture values are DEMO.

![DEMO/SYNTHETIC: Overview](assets/panel-0.5.14/status-DEMO.png)

## Sensors

CPU/GPU/core/DSP-EVE/IVA temperatures and available historical channels. GPU temperature is not GPU utilization. Unknown live fan RPM stays unavailable.

![DEMO/SYNTHETIC: Sensors](assets/panel-0.5.14/sensors-DEMO.png)

## Materials and refill ledger

Tank level observations are separate from estimated cartridge usage. The owner refill notebook does not rewrite native usage. The unavailable pre-dispense pause is not a motor inhibit.

![DEMO/SYNTHETIC: Materials and refill ledger](assets/panel-0.5.14/materials-DEMO.png)

## Print history

Prepared metadata, recovered artifacts and unavailable payloads are distinguished. This fixture contains no private jobs or models.

![DEMO/SYNTHETIC: Print history](assets/panel-0.5.14/jobs-DEMO.png)

## Diagnostics

Read-only fault references, saved-session categories, bounded logs and exports. A task-finished log alone is not proof of a successful physical print.

![DEMO/SYNTHETIC: Diagnostics](assets/panel-0.5.14/diagnostics-DEMO.png)

## Owner settings

Owner-only preferences and typed capability/settings descriptions. Unsupported vendor writes remain disabled.

![DEMO/SYNTHETIC: Owner settings](assets/panel-0.5.14/settings-DEMO.png)

## Network and SSH

Displays network/trust state and supported policy; it is not an arbitrary network configuration terminal.

![DEMO/SYNTHETIC: Network and SSH](assets/panel-0.5.14/network-DEMO.png)

## Privacy

The policy selector is a preview. It must not claim that native cloud settings were applied.

![DEMO/SYNTHETIC: Privacy](assets/panel-0.5.14/privacy-DEMO.png)

## Maintenance

Version/rollback information and explicitly unavailable power actions. Process presence is not a safe-idle proof.

![DEMO/SYNTHETIC: Maintenance](assets/panel-0.5.14/maintenance-DEMO.png)

## Narrow viewport

Actual Firefox viewport 500 × 758; no horizontal overflow. This is not a claim about every phone.

![DEMO/SYNTHETIC: Narrow viewport](assets/panel-0.5.14/overview-mobile-DEMO.png)

## Usage preview

Separate before/after accounting, unchanged physical-volume knowledge, expiring plan and explicit confirmation.

![DEMO/SYNTHETIC: Usage preview](assets/panel-0.5.14/reset-preview-SYNTHETIC.png)

## Usage result

A synthetic transaction result. No EEPROM was written to create this screenshot.

![DEMO/SYNTHETIC: Usage result](assets/panel-0.5.14/reset-SYNTHETIC.png)

## Cartridge snapshot

Shows the private backup summary without keys, ROM identity or raw EEPROM.

![DEMO/SYNTHETIC: Cartridge snapshot](assets/panel-0.5.14/backup-cartridge-SYNTHETIC.png)

## Tank snapshot

A 512-byte raw copy is distinct from a validated tank restore format.

![DEMO/SYNTHETIC: Tank snapshot](assets/panel-0.5.14/backup-tank-SYNTHETIC.png)

## Saved snapshots

Recent verified snapshots; usage restore is available only for the same supported cartridge. Tank restore remains disabled.

![DEMO/SYNTHETIC: Saved snapshots](assets/panel-0.5.14/backups-SYNTHETIC.png)

## Usage restore preview

Restores saved accounting while preserving identity and advancing the current write count.

![DEMO/SYNTHETIC: Usage restore preview](assets/panel-0.5.14/restore-preview-SYNTHETIC.png)

## Usage restore result

Synthetic result only; not a hardware restoration receipt.

![DEMO/SYNTHETIC: Usage restore result](assets/panel-0.5.14/restore-complete-SYNTHETIC.png)

## Material selection

Only eligible catalog codes are offered. Tank material assignment stays disabled pending native-path validation.

![DEMO/SYNTHETIC: Material selection](assets/panel-0.5.14/material-assignment-SYNTHETIC.png)

## Material preview

Material assignment has its own confirmation and apply endpoint; usage reset cannot consume this plan.

![DEMO/SYNTHETIC: Material preview](assets/panel-0.5.14/material-preview-SYNTHETIC.png)

## Material result

Synthetic material transaction result; no device state changed during capture.

![DEMO/SYNTHETIC: Material result](assets/panel-0.5.14/material-complete-SYNTHETIC.png)
