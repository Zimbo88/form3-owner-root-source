# Form 3 Owner Root

The latest panel update adds passive preheat/tank-phase observations and stricter
sensor freshness checks: [findings, live acceptance and screenshot](docs/public/PANEL_RESEARCH_UPDATE.md).
Access remains optional through the [owner preference](docs/public/PANEL_ACCESS.md).

![Original Owner Root project mark](assets/signature-brand.svg)

Repair, preservation and local maintenance for a reference Formlabs Form 3:
a protected acquisition route, separate authenticated root SSH/SFTP, and an
unprivileged owner panel. This is an independent owner project, not manufacturer
firmware or a universal Form 3 unlock.

## Status / compatibility

- **Source version:** [VERSION](VERSION). Reviewed target: **Form 3 / Daguerre,
  selected p6, firmware 2.5.6-2773**, exact layout and file-hash gates.
- **Hardware evidence:** historical Rescue/acquisition and normal owner access;
  the 0.5.18 receipt confirms a limited panel update and read-only acceptance. It does
  not prove every current path, a fresh installation or another printer revision.
  [Evidence matrix and unresolved acceptance](docs/public/EVIDENCE_STATUS.md).
- **Required experience:** safe unpowered board work, chip/package identification,
  multimeter checks, Linux terminals, SSH trust and backup/rollback review.
  [Reference equipment and unknown versions](docs/public/REFERENCE_SETUP.md).
- **Brick-relevant phase:** writing QSPI. Unknown chip suffix, voltage, shared rail,
  layout or hash means **STOP**. The code does not adapt unknown hardware.
- **Distribution:** authored code, transformation recipes, guides and checksums;
  no vendor firmware, device dumps, keys or private logs. Inputs come from your
  own authorized acquisition. A stock software-only first-root route is unproved.

## Third-party resin: one successful reference print

I completed a print with **Anycubic High Clear**, the standard **Clear V4
(`FLGPCL04`) profile**, and **no Open Material Mode**. I considered the result
excellent. This is an owner-reported successful experiment, not a general resin
compatibility certification. [Full report, cartridge reuse experience and limits](docs/public/THIRD_PARTY_RESIN.md).

## Start here

1. Read [ROOT_GUIDE](docs/public/ROOT_GUIDE.md) for the concept, limits and prerequisites.
2. Audit [MODIFICATION_MAP](docs/public/MODIFICATION_MAP.md) before any write and
   [PI5_CLIP_GUIDE](docs/public/PI5_CLIP_GUIDE.md) before touching the board.
3. Follow **[COMMAND_WALKTHROUGH](docs/public/COMMAND_WALKTHROUGH.md)**: the single
   canonical complete command sequence, with terminal labels, checks and recovery.
   [OWNER_INSTALL](docs/public/OWNER_INSTALL.md) and [SECURE_SSH](docs/public/SECURE_SSH.md)
   are deeper references, not additional parallel first-install procedures.
4. Developing without hardware? Start with [BUILD](docs/public/BUILD.md).

### Enter at your verified state

| Existing state | Next step |
|---|---|
| Unmodified printer | Prerequisites and read-only identification; do not skip electrical gates |
| Verified own QSPI/eMMC backups | Check provenance/current target, then walkthrough's applicable state; do not reacquire or reflash just to start at page one |
| Installed owner services | Verify current installation over pinned SSH; [ordinary use](docs/public/SECURE_SSH.md#7-daily-login-without-repeatedly-typing-a-passphrase) |
| Updating owner software | [Signed package update](docs/public/OWNER_INSTALL.md#6-ordinary-updates-disable-and-recovery); preserve QSPI and SSH identity |
| Interrupted installation | Preserve pending transaction/backups; [recovery reference](docs/public/OWNER_INSTALL.md#6-ordinary-updates-disable-and-recovery), never blind reinstall |

### Installation phases

| Phase | What changes / recovery point |
|---|---|
| Read-only hardware identification | Nothing programmed; verify complete part, voltage and topology |
| QSPI acquisition and verification | Three meaningful reads and independent originals; no write yet |
| Temporary Rescue | Gated QSPI environment/reserve change; retain same-printer original for restoration |
| eMMC backup | RAM root and protected reads; preserve user area and both boot areas |
| Persistent owner installation | First approved writable p6/p7 mounts, then bounded account/hook/owner files with transactions |
| Original QSPI restoration | Restore and fully read back the same printer's original image; p6/p7 owner files remain |
| Normal-boot acceptance | Vendor boot plus independent SSH :2222 and panel :1328; verify on each target |

## Maintenance and optional features

The source includes owner-signed **installation/update packages**, plan/verify/
rollback tooling, source-labeled status and bounded diagnostic exports. Source
review tarballs are unsigned. The primary panel uses HTTPS; deliberately selected
private-LAN HTTP remains plaintext. Unknown data is UNAVAILABLE; saved observations
are HISTORICAL/CACHED.

- [Panel and limitations](owner-ui/README.md), [saved print diagnostics](docs/public/LOG_REVIEW.md).
- [Optional local touchscreen clock and original artwork](docs/public/NATIVE_DISPLAY.md).
- [Consumable backups and material workflows](docs/public/CONSUMABLE_BACKUPS.md),
  [tank decoding and emulator evidence](docs/public/TANK_DATA.md),
  [illustrated panel guide](docs/public/PANEL_GUIDE.md).
- [Scoped legacy Clear usage adjustment](docs/public/CARTRIDGE_PANEL_RESET.md):
  implemented and fixture-tested, read-only panel preview accepted on hardware;
  separate earlier live-write evidence has a narrower provenance boundary.
- [Research API/privacy/stock-root boundaries](docs/public/RESEARCH_BOUNDARIES.md).
- [Material settings and OMM research](docs/public/MATERIAL_SETTINGS_RESEARCH.md):
  desktop findings compared with existing evidence, profile conflicts and a bounded
  offline comparator; no license activation or general settings writer.

No generic actuator proxy, universal consumable reset, license issuer or automatic
vendor privacy modification is provided. Panel power controls remain disabled.
Root access does not establish a mechanical repair or safe printing condition.

## Background and distribution

I started this project to repair my Form 3 when the manufacturer's repair route
was no longer available to me. Encrypted support archives made independent
diagnosis difficult. Some local diagnostics are plaintext; root does not decrypt
every support archive.

This public source edition was selected from private research. Manufacturer binaries,
private data and material with unresolved redistribution questions are omitted;
those omissions are not a guarantee of legal clearance. The
[rights boundary](docs/public/RIGHTS_AND_RELEASE.md), [security policy](SECURITY.md)
and [maintainer release checklist](docs/maintainer/RELEASE_CHECKLIST.md) explain
what can be shared and what still needs review. This source repository became
public on 2026-10-08 after an explicit maintainer decision and the
[recorded release checks](docs/maintainer/PUBLIC_RELEASE.md). The separate research
repository and raw evidence remain private; project tools do not change visibility.

## Why the demonstrated route works

The inspected U-Boot can load the printer's genuine kernel/DTB together with a small
external rescue from verified free QSPI space. An intentionally changed environment
selects that rescue while preserving SPL/U-Boot executable bytes. Rescue provides
initial root and backups. A separate p6/p7 file transaction then installs owner
services. Restoring **the same printer's own original QSPI** returns to normal vendor
boot with those services alongside it. An existing vendor public key is not owner
authorization. Another printer's dump or identity is never an installation input.

The checked-in rescue profile is tied to one authenticated reference acquisition.
A different factory hash requires the [profile review procedure](docs/public/ROOT_GUIDE.md),
not a removed safety check. The photos available during research did not resolve
all electrical details. The wiring guide separates the recorded connection table
from the still-required identification and electrical measurements for an actual setup.

## Credit and license

I thank **Łukasz Jakóbiec** for documenting the work that helped me access my system:
[wemakerobots part 1](https://wemakerobots.com/en/projects/debricking-form-3-part-1/)
and [part 2](https://wemakerobots.com/en/projects/debricking-form-3-part-2/).
Those articles cover a Form 3+ with a different fault and procedure; no endorsement
is implied. I used a clip on the still-soldered flash after removing the SOM,
without soldering UART or removing the chip. That is still hardware intervention.

[MIT](LICENSE) applies to my authored contribution, with earlier contributor notices
retained. [Third-party notices](docs/public/RIGHTS_AND_RELEASE.md) separately cover
BusyBox patches, dependencies and the wordmark. Product names identify compatibility.
Neither source-only packaging nor a checksum establishes legal permission.

Maintained by **Mathias Zimmermann**. This project is not affiliated with or
endorsed by Formlabs.

Tank material editing and same-tank saved-material restoration are documented in
[the tank panel workflow](docs/public/TANK_MATERIAL_PANEL.md). Current lifetime
and physical identity are preserved; unknown formats remain refused.
