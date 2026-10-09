# Evidence status

This is the evidence index, not a new hardware acceptance receipt. The current
repository version is [VERSION](../../VERSION). A version string alone does not
bind a hardware observation to every file in a later checkout.

## Tank material extension

The [0.5.16 tank material workflow](TANK_MATERIAL_PANEL.md) implements an owner
material-only transaction and same-tank saved-material restoration. Lifetime is
preserved. Source, synthetic failure/rollback tests and driver instruction
emulation are distinct from a successful live write; the earlier 0.5.15 receipt
is not promoted to write acceptance. Current deployment observations have their
own [receipt](tank_panel_acceptance.json) and
[screenshots](TANK_MATERIAL_PANEL.md#installed-reference-and-original-screenshots).
The maintenance package is installed; 26 synthetic checks ran on its genuine
Python/kernel. Live previews and no-ops passed. A real tank write remains
**NOT CONFIRMED**, independently of the implemented and fixture-tested writer.

## Consumable extension (2026-10-09)

The current source adds format-scoped cartridge backup/usage/material workflows
and a validated T/65 tank snapshot decoder. The source/fixture boundary remains
separate from a hardware write: [current scope](CONSUMABLE_BACKUPS.md),
[tank layout and emulator proof](TANK_DATA.md), and the sanitized
[tank receipt](tank_codec_acceptance.json). The recorded genuine-runtime capture
is read-only; it does not certify a new tank writer or restore path.

**CURRENT-SOURCE HARDWARE, LIMITED:** the 0.5.14 maintenance extension and
0.5.15 panel fix were installed on the reference printer. The
[package-bound receipt](consumable_panel_acceptance.json) records real browser
backup, authentication, catalog and preview checks. The [19 live screenshots](PANEL_GUIDE.md)
show that installed panel with private identifiers redacted. No consumable write,
vendor-service restart or printer reboot was performed for this review.


## How to read the labels

| Label | What it establishes | What it does not establish |
|---|---|---|
| SOURCE | An authored implementation exists | Correct execution or compatibility |
| STATIC / OFFLINE | Inspected files, hashes, grammar or selected control flow | A running physical printer |
| FIXTURE | Synthetic inputs exercised named cases | Actual buses, power loss or actuators |
| EMULATION | Named ARM code ran with modeled hardware/kernel | Genuine printer-kernel or electrical behavior |
| HISTORICAL HARDWARE | A reference-device observation at its recorded milestone | Every later source revision |
| CURRENT-SOURCE HARDWARE, LIMITED | A receipt binds a named source/package to specific physical observations | Complete acceptance of the repository |
| NOT CONFIRMED | No sufficient retained evidence for this claim | Evidence that the feature cannot work |

Older documents use FILE/CODE, OFFLINE TEST and OWNER HARDWARE OBSERVATION. These
map to the corresponding rows above; a narrative observation is not silently
upgraded to a publicly reproducible machine receipt.

## Evidence matrix

| Component / scope | Evidence and version binding | Status / limits |
|---|---|---|
| QSPI acquisition and Rescue V2 | [Acquisition receipt](../../rescue/hardware_results.json), [locked build inputs](../../rescue/sources.lock.json), [root guide](ROOT_GUIDE.md) | HISTORICAL HARDWARE: isolated RAM root and protected acquisition. V1 and V2 observations are labeled separately. This receipt predates normal owner installation |
| Reference layout and runtime | [Hash/size manifest](../../checksums/rescue-runtime-files.json), `Target.preflight` in [ownerctl](../../owner-maintenance/ownerctl.py) | STATIC: p6 / 2.5.6-2773, ARMv7 and exact partition checks. Hashes are compatibility gates, not redistributed binaries or a new-device approval |
| Initial owner installation, root SSH/SFTP and reboot return | Historical account in [maintenance reference](../../owner-maintenance/README.md) and [SSH guide](SECURE_SSH.md) | HISTORICAL HARDWARE. The public tree does not contain a complete independently auditable initial-install receipt binding every observation to a source commit |
| Panel maintenance deployment | [2026-10-03 receipt](../../analysis/owner/cartridge-panel-0.5.13.json), source `4c501b185d39ed81e67d3cc32f88dd8b80afd202`, package hash recorded there | CURRENT-SOURCE HARDWARE, LIMITED for the recorded 0.5.13 package: ownerctl verification, WLAN HTTP authentication/CSRF/logout, unprivileged panel, SSH/Formule continuity and read-only Clear preview |
| Primary HTTPS and full reboot acceptance of that update | Same receipt | NOT CONFIRMED in this milestone: no primary Ethernet IPv4, no printer reboot. Earlier observations must not fill those gaps |
| Package/runtime regression | Same receipt: 601 canonical fixtures, 467 curated fixtures, 39 target-Python synthetic checks; 18 package member hashes matched | FIXTURE / target-runtime synthetic execution. Historical counts remain unchanged; they are not current CI results or unique hardware tests |
| Clear reset implementation | [Codec, broker and transaction references](CARTRIDGE_PANEL_RESET.md#evidence-and-tests) | SOURCE + FIXTURE: typed write path, before/after checks, rollback and reauthentication |
| Earlier explicit Clear live write | [Retained narrative](CARTRIDGE_PANEL_RESET.md#evidence-and-tests): usage 1033.6 → 0 mL, write count 538 → 539 | HISTORICAL HARDWARE report. Detailed raw receipts remain private; no independent public raw-receipt reproduction is claimed |
| Browser-to-device Clear write in panel acceptance | Receipt explicitly says `cartridge_writes_this_milestone: false` | Preview/read-only hardware accepted; **live browser-triggered EEPROM write acceptance NOT CONFIRMED**. ALREADY_FRESH performed no write |
| Native clock / original logo | [Pinned before/after hashes and observations](NATIVE_DISPLAY.md) | Installation/readback described; current Printing visual fit and latest original mark's later boot observation remain separately unconfirmed in this public record |
| Print logging and accounting | [Capture scope](../methodology/LIVE_PRINT_CAPTURE.md), [completed-print analysis](PRINT_VOLUME_ACCOUNTING.md) | HISTORICAL HARDWARE capture plus offline analysis. This is not a complete fault diagnosis or evidence of safe automatic refill |
| Stock software-only root / factory netboot | [Research boundary appendix](RESEARCH_BOUNDARIES.md) | NOT CONFIRMED; not part of the clip-based installation sequence |
| Other boards, models, slots or firmware | [Reference setup](REFERENCE_SETUP.md) and actual code gates | NOT CONFIRMED. A compatible-looking filename or chip prefix is insufficient |

## Resolving the apparent contradictions

`rescue/hardware_results.json` describes the **acquisition/rescue phase**. Its
historical `not_confirmed` list is preserved, including normal-OS access. It is
not a current project-wide denial of the later normal-OS observations.

The decoder, reconciliation and writeback reports are successive research
milestones. Their statements that no writer was delivered describe those tools
and phases. The later panel chapter separately documents the added write path.
The earlier native flush fixtures also show different ordering for invalid copies;
file → B → A is the owner transaction for two validated copies, not a universal
vendor rule.

There is **no defensible single “last completely hardware-confirmed version”**
in the public artifacts. Report the version, package and tested behavior together.
The earlier public-documentation review changed no printer runtime. The separate
2026-10-09 deployment above records its own limited hardware observations and
does not extend the historical receipts. New source-only results belong in the
[publication review](../maintainer/PUBLICATION_REVIEW.md), not in old receipts.
