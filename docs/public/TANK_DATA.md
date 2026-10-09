# Tank memory: decoded format and emulator results

## Scope and result

The reference Form 3 tank snapshot uses **T/65**, a 512-byte main-memory image
and the `TankRO` / `TankRW` implementation in firmware 2.5.6-2773. It is **not**
the `SeniorTankRW` layout, even though both use RW version 65. Cartridge C/0
records and their write counter must not be transplanted into a tank.

**READ-ONLY HARDWARE RESULT (2026-10-09):** the authored backup code ran under
the printer's Python 3.5.3 on its genuine Linux 4.9 kernel. Two matching reads,
RO/A/B checksums and the decoded usage/date/material projections against the
persistent tank record passed. The connected cartridge passed its separate
128-byte validation too. Neither test programmed consumable memory or stopped
a vendor service. Raw snapshots and identities remain private.

**OFFLINE / EMULATION RESULT:** see the sanitized
[receipt](tank_codec_acceptance.json). The independent native block-cipher tests
have no crypto hook. The nine native serialization tests model Go allocation,
reflection and encryption; they are not full native execution of every dependency.
No full firmware boot, native tank write, tank restore or new resin compatibility
claim follows from these tests.

## Layout and meaning

All addresses below are **ELF virtual addresses**, not file offsets. The earlier
Ghidra project applies an additional `0x10000` image-base adjustment.

Reference `TankCartridgeDaemon` SHA256:
`a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1`.

| Region | Image offset / bytes | Meaning |
|---|---|---|
| RO | 0 / 32 | Type, version, IV component, checksum, encrypted identity/mechanical fields |
| RW A | 32 / 41 | Version, 4-byte checksum, 36-byte encrypted payload |
| RW B | 128 / 41 | Second copy of the same record layout |
| Remaining bytes | Outside those regions | Preserved; no assumption that they are disposable |

RW plaintext uses little-endian packed `<fIQIf8sI`:

| Payload offset | Field | Interpretation |
|---|---|---|
| 0 | `VolumePrinted_mm3` | Float32 cumulative print accounting, not remaining resin |
| 4 | `NumLayersPrinted` | Unsigned 32-bit lifetime layer count |
| 8 | `PrintTime_mS` | Unsigned 64-bit accumulated print time |
| 16 | `LastPrintDate` | Unsigned 32-bit epoch seconds; mirror renders a date string |
| 20 | `LastResinLevel_mm` | Float32 **last saved** level; not live or a volume in mL |
| 24 | `LastResinUsed` | Eight ASCII material-code bytes |
| 32 | `DateFirstFill` | Unsigned 32-bit epoch seconds |

There is **no cartridge-style WriteCount in this tank RW format**. The decoder
retains lifetime values. JSON decimal floats are compared after float32 projection;
an exact comparison of decimal text would falsely reject valid native records.
Checksums are integrity checks, not manufacturer signatures or chemical approval.

## Exact implementation evidence

| Reference function | ELF address | Evidence |
|---|---|---|
| `TankRW.FillRWFromBytes` | `0x4991e0` | Static version, envelope and decryption path |
| `TankRW.RWToBytes` | `0x4994f8` | Static layout plus 9 bounded synthetic ARM cases |
| A/B offset and record-size accessors | `0x499950`, `0x499964`, `0x499978` | Return 32, 128 and 41 |
| `main.daguerreTank.Merge` | `0x4e88f0` | 3 ARM cases: same-type inputs return nil without modifying either object |
| XTEA key expansion / block encryption | `0x1db458`, `0x1daf98` | Native instruction execution, 6 stream comparisons including RO skip and RW length |

The no-op same-type merge is unlike the cartridge's maximum-usage merge. It does
**not** by itself establish which file/EEPROM instance wins in every load path.
The crypto stream uses the existing cartridge codec's little-endian XTEA primitive,
with the recovered tank lengths and offsets. Device keys never enter test fixtures.

## Reproduce without a printer

Run the ordinary public fixture suite for the authored decoder. The native probe
requires your own hash-matching executable and an existing Unicorn installation;
these inputs are intentionally absent from the public repository.

```bash
# LAPTOP — copied evidence only; no network/hardware operations
: "${TANK_DAEMON_COPY:?Set the path to your copied reference executable}"
: "${UNICORN_MODULE_ROOT:?Set the directory containing the unicorn package}"
python3 tools/probe_tank_native.py \
  --binary "$TANK_DAEMON_COPY" --unicorn-dir "$UNICORN_MODULE_ROOT" \
  --output build/tank-native-review.json
```

The launcher requires unprivileged bubblewrap, refuses another firmware hash,
mounts inputs read-only, isolates networking and bounds execution. A dependency
failure means **NOT RUN**, not a pass. Do not run vendor startup code to work
around a missing emulator dependency.

For a private snapshot produced by the panel's backup store:

```bash
# LAPTOP — no raw data is printed; report remains private
: "${PRIVATE_TANK_SNAPSHOT:?Set the directory containing the copied tank backup}"
: "${PRIVATE_REPORT:?Set a new private report filename}"
python3 tools/inspect_tank_snapshot.py \
  --snapshot "$PRIVATE_TANK_SNAPSHOT" --output "$PRIVATE_REPORT"
```

## Material assignment and restoration boundary

The offline candidate changes only `LastResinUsed` and the two RW checksums,
while preserving RO, lifetime, dates and padding. This is useful for verifying
an eventual transaction; it is **not a released tank writer**.

The native touchscreen reprogram path calls `TellTankPrinted`. Static inspection
also shows accounting/date effects in its writer. Calling it with invented zero
arguments is not equivalent to a harmless material-only setter. Native material
eligibility, the exact supported arguments, load/reload behaviour and interruption
rollback still need a complete transaction proof. The panel therefore exposes
real validated tank backups while tank material apply and tank restore remain
unavailable with that reason. A raw backup is not proof of a working restore.

The backing chip family is `4c`; this report does not infer an exact part number
or borrow the DS2431 cartridge protection semantics for it. No tank lifetime reset
is provided. See [consumable UI and recovery scope](CONSUMABLE_BACKUPS.md).
