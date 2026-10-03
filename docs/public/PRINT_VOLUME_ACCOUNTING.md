# Printed volume and cartridge consumption

## Question and result

Does manual tank filling stop the cartridge's estimated consumption from rising?
The captured completed print provides strong evidence that it does not, on the
inspected Form 3 / 2.5.6-2773 path. This is a consumption estimate, not a physical
measurement of resin leaving the supply cartridge.

**OBSERVED IN HISTORICAL EVIDENCE:** one uninterrupted capture continuation has
2,169 snapshots, 2,613 verified distinct objects, no recorded monotonic-clock
discontinuity and no unstable-file observation. It contains two cartridge records
and one tank record; merely being present in the mirror does not prove insertion.
One cartridge record remains unchanged throughout this window.

| Field in the changing record | Increase during this window | Nonzero changes |
|---|---:|---:|
| Cartridge `EstimatedVolumeDispensed_ml` | 35.31384204796706 mL | 1,171 |
| Cartridge `CumulativeDispenseTime_s` | 0 seconds | 0 |
| Cartridge `DispenseCount` | 0 | 0 |
| Tank `VolumePrinted_mm3` | 30,708 mm³ = 30.708 mL | 1,171 |
| Tank `NumLayersPrinted` | 1,172 | distinct from volume-step count |

These are deltas of persisted numerical fields, not a direct trace of motor
power, physical flow or actual remaining cartridge contents. An unchanged time
counter alone cannot prove that no actuator moved. Manual tank filling and print
completion were separately reported by the owner. A tank's layer counter and a
job's layer count need not have identical update semantics.

The aggregate volume ratio is approximately **1.149988**. Pairing nonzero volume
changes in sequence gives 1,171 pairs; after dividing cartridge delta by 1.15
and converting to mm³, the maximum absolute difference from the tank delta is
0.154 mm³. This is strong correlation, not proof of atomic publication or a join
on independently captured layer IDs. Do not silently discard the discrepancy.

## Firmware references and remaining caller gap

**FILE/CODE:** p6 `/etc/formlabs/FORM-3/PrintEngine.json`, SHA256
`b440f44f7d8ec3e52095308128586d17549efe428809c941823eadf9284a7d78`,
contains `ResinClingFactor_mL_per_mL: 1.15`. Its name suggests an allowance for
adhering resin. The matching numerical ratio is strong evidence of an accounting
relationship; this investigation has not yet proven the complete dynamic
calculation or that the running process used this exact configuration value.

Sauron `/usr/bin/Sauron`, SHA256
`025a21f7cdfaf2f10b2a40f2580d62992794a1d500643194e4606eb4e8676e34`:

- `Sauron::Daguerre::Resource_Cartridge_DBus` has a vtable at `0x174b268`.
  Its entries at `0x174b2a8` and `0x174b2ac` point to the volume/time reporting
  functions at `0x883540` and `0x884994`, respectively. Corresponding method-name
  references occur at `0x884374` and `0x8856cc`.
- The configuration-name string is at `0x14937d8`. Literal-load/PC-add references
  in the JSON-reading function `0x295174` occur at `0x2957e0`/`0x2957f4` and
  `0x295a0c`/`0x295a10`; the JSON-producing function `0x297670` references it at
  `0x297788`/`0x297790`. These establish configuration access, not the missing
  caller that multiplies printed volume and dispatches the cartridge report.

Addresses above are ELF virtual addresses, equal to this Sauron Ghidra project's
addresses. They are not file offsets. The ELF load mappings and ARM exception
unwind table were used to locate functions before private decompilation. A missing
Ghidra reference is not evidence of an absent call, particularly for virtual calls.

TankCartridgeDaemon `/usr/bin/TankCartridgeDaemon`, SHA256
`a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1`:
`TellCartridgeVolumeDispensed_mL` at ELF `0x4b6448` accepts an external report;
`queueWriteRequest` at `0x4b6530` queues it; `SMConsumable.writeCartridge` at
`0x4e37bc` adds reported volume/time to consumable state. These are accounting
inputs, not a flow-meter read. Historical TKD Ghidra addresses add `0x10000`;
do not apply that offset to Sauron.

**STRONGLY SUPPORTED:** in this capture, cartridge estimated consumption is
booked in step with printed-volume usage, with a factor matching the Form 3
configuration. It must not be interpreted as measured supply flow. **UNKNOWN:**
the complete layer-to-report call chain, all alternate modes, runtime overrides,
and precisely which other accounting paths can contribute deltas.

## Reproduce from an owner's sealed capture

The updated reader accepts a named continuation under the original session seal.
It validates index/object sizes and SHA256, bounds parsing, rejects symlink/path
escapes and has no fallback to objects from a different continuation. Only
allowlisted numerical fields are exported. Raw map keys can contain secrets;
never dump arbitrary JSON keys while investigating consumables.

```sh
# LAPTOP — offline; use your own captured session, never a printer target.
: "${CAPTURE_SESSION:?path to your sealed session directory}"
: "${CAPTURE_INDEX:?consumable-state/snapshots.private.jsonl or named continuation}"
: "${PRIVATE_REVIEW:?new private output under research-private}"
python3 tools/review_consumable_history.py \
  --session "$CAPTURE_SESSION" --index "$CAPTURE_INDEX" \
  --output "$PRIVATE_REVIEW/usage.private.json" \
  --summary "$PRIVATE_REVIEW/usage-summary.json"
```

Expected: verified coverage counts and a private numerical history. Existing
output files are refused. A manifest proves consistency with that seal, not
independent authenticity of the original acquisition. Receipt timestamps are not
sensor measurement timestamps. Analyze boot/capture intervals separately.

Research provenance: session seal SHA256
`29237060a02c8a7d7e686de393486a84ec4a5572f6cc04106bb7d1fdbe62254d`;
selected index SHA256
`0217fa6134836e8fa716c74a381ceeb1c0b4ca21abdc8a1d74c46e3cef3a6107`.
Raw logs, consumable identities and complete private histories are not distributed.

## Consequence for a refill workflow

Keep four quantities separate: physical tank level, tank lifetime printed volume,
cartridge estimated consumption and an owner-entered refill ledger. An empty
cartridge is not physically full merely because an estimate is changed. Changing
this estimate also does not disable automatic dispensing or resolve a material
mismatch. No counter write, cartridge identity change or panel deployment was
performed by this analysis.

The [writeback investigation](CARTRIDGE_WRITEBACK.md) explains why changing one
JSON value is not a coherent transaction. A reliable manual-supply design still
needs a proven pre-actuation boundary and intact level/overflow protections.
The next useful offline task is resolving the virtual caller and the relevant
mode-specific volume calculation; it does not require another print attempt.
