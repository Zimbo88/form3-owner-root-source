# Consumable backups, usage and material assignment

**Current access/UI:** [Optional secret and direct actions](PANEL_ACCESS.md).
The 0.5.16/0.5.15 screenshots below retain their historical labels.

## Current implementation and evidence

The [0.5.16 tank extension](TANK_MATERIAL_PANEL.md) adds material-only editing
and saved-material restoration for the same reference tank, preserving lifetime.
The [0.5.16 receipt](tank_panel_acceptance.json) confirms installation, genuine-runtime
synthetic tests and live previews/no-ops. Its live tank write remains untested.
The 0.5.15 acceptance below is historical and does not certify that new write path.

The consumable extension was installed as a **0.5.14 maintenance update**;
0.5.15 is a panel-only navigation fix on that baseline. Real backups, catalog
and read-only previews passed the [live review](consumable_panel_acceptance.json).
The new write paths are tested with synthetic fixtures; their
complete browser-to-device write flows have not been accepted on hardware.
Historical Clear reset and Clear V2-to-V4 assignment observations do not certify
every material or this generalized release. No consumable writes are part of the
screenshot or regression tests.

| Operation | Implemented boundary | Hardware evidence / limitation |
|---|---|---|
| Cartridge backup | Two matching 128-byte reads, stable mirror, checksums and mirror values verified | Legacy 2d family only; Genuine-runtime capture and browser backup passed; no new generalized write acceptance |
| Tank backup | Two matching 512-byte reads, T/65 RO/A/B checksums, float32/date/material mirror projection | Read-only genuine-runtime capture passed; no tank live writer or restore acceptance |
| Usage reset | Legacy C/0, RW1, 1000 mL; zero usage and native monotonic write counter | Historical Clear reset; not a universal cartridge writer |
| Restore saved usage | Same physical cartridge, same RO/material and non-usage fields; current WriteCount + 1 | Fixture tested; cannot transplant another cartridge's backup |
| Cartridge material assignment | Explicit public Form 3 catalog entries, exact firmware pins, writable DS2431 pages, same identity | Earlier Clear V2-to-V4 observation; generalized panel path requires acceptance |
| Tank material assignment | T/65 mechanical 3.3 only; current accounting/identity retained | Owner transaction with driver emulation and failure fixtures; separate live-write acceptance |
| Tank saved-material restore | Same physical tank; saved material, current lifetime | Not full-memory or lifetime restoration |

See [tank format and native emulator results](TANK_DATA.md) for the separate tank evidence.

## Panel workflow

Open **Materials → Manage cartridge & tank** to open the consumable dialog.
Authenticate even if ordinary WLAN viewing permits anonymous sessions. HTTP does
not encrypt the secret; use the enrolled HTTPS path where available.

- **Back up cartridge / Back up tank:** creates a private snapshot and reports its
  opaque ID, kind, size and validation status. It does not stop a service or write
  consumable memory. Changing consumables or state during capture rejects it.
- **Review saved backups:** lists at most the latest 12 verified entries and the
  total retained. Cartridge entries offer a read-only usage restore preview.
  Tank entries offer saved-material restoration, preserving current lifetime.
- **Prepare a fresh preview:** inspects the current legacy cartridge and prepares
  a zero-usage plan. Already-matching state performs no write.
- **Review material assignment:** lists only explicitly eligible public Form 3
  codes in the installed catalog. Select a code to inspect a separate material
  preview; catalog membership is not resin chemistry approval.
- **Apply:** review before/after values, type the displayed operation-specific
  confirmation, and re-enter the access secret. A material plan cannot be applied
  through the usage endpoint. Plans expire and are pinned to the device, source
  data and reviewed implementation.

No automatic reset occurs on insertion, boot or a threshold. Usage restore is
not whole-image recovery and does not undo a material change. Unknown format,
protect state, firmware, pending transaction, changed baseline or unsafe state
must refuse the operation.

The native hash checks can take about a minute on this target. PREPARING is
read-only; keep the dialog open or reopen it to inspect the saved state. A READY
preview retains backup/material navigation. Planning a different operation
replaces the old preview; apply must still match its exact unexpired plan.

## Storage, privacy and recovery

The broker stores explicit snapshots in
`/data/owner-maintenance/cartridge-reset/backups/<opaque-id>/` with private
permissions. Each contains `eeprom.bin`, `record.private.json` and
`manifest.private.json`. Hashes bind both input files. These files contain device
identity and potentially key material: **do not upload them to GitHub or share
raw exports**. The panel returns an allowlisted summary, never raw keys, filenames
chosen by a browser, ROM IDs or EEPROM bytes.

Snapshots use a new temporary directory, durable file writes and atomic rename.
An interrupted snapshot remains visible as an unresolved private directory;
listing fails instead of silently treating it as complete. At 128 snapshots the
store refuses more captures; it never deletes originals automatically.

The transaction engine retains an additional durable pre-write backup. Usage
writes keep the existing file → B → A ordering, full readbacks and daemon reload
verification. Cartridge material changes preserve usage and identity but modify the
material field/checksum in the RO data area: unlike usage A/B copies, this area
has **no redundant record**. A power interruption between material rows is a
recovery case. Page protection is inspected, never cleared or programmed.

On a caught failure the engine attempts rollback and verifies readback. An
interrupted/failed transaction blocks another apply. Preserve its files and
receipt for private inspection; never remove the marker just to retry. Owner
software rollback does not automatically roll back consumable contents.

## Evidence and implementation references

- [Private snapshot store](../../owner-maintenance/consumable_backup.py)
- [Typed broker](../../owner-maintenance/cartridge_broker.py),
  [transaction engine](../../owner-maintenance/cartridge_transaction.py),
  [material transformation](../../owner-maintenance/cartridge_material.py)
- [Synthetic snapshot tests](../../tests/test_consumable_backup.py),
  [material interruption tests](../../tests/test_cartridge_material.py),
  [HTTP boundary tests](../../tests/test_cartridge_reset_http.py)
- [Historical 0.5.13 Clear panel acceptance](CARTRIDGE_PANEL_RESET.md)
- [Third-party resin owner report](THIRD_PARTY_RESIN.md),
  [panel screenshots](PANEL_GUIDE.md)
