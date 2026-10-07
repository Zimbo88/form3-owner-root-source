# Cartridge writeback ordering and failure results

> HISTORICAL RESULT: this report describes its named research tool and milestone.
> The later [panel write implementation and acceptance](CARTRIDGE_PANEL_RESET.md#evidence-and-tests)
> has a separate scope; see the [central evidence index](EVIDENCE_STATUS.md).

This continuation tests selected native writeback control flow using synthetic
memory only. It does not write a consumable, generate a replacement chip image,
change identity/material/date or prove a working refill/reset procedure.

## Reference and isolation

**FILE/CODE + ISOLATED FUNCTION TEST:** p6 `/usr/bin/TankCartridgeDaemon`,
2.5.6-2773, SHA256
`a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1`.
Addresses are ELF virtual addresses; historical Ghidra coordinates add `0x10000`.

Unicorn 2.1.4 ran selected ARM instructions inside a disposable bubblewrap mount,
user and network namespace. The firmware copy was read-only. No host credentials,
device nodes for physical hardware, writable evidence or external networking
were available. No vendor daemon/startup or installer was started.

For `main.Flush` (`0x4ebeb8`), the harness supplied synthetic cartridge and bus
interfaces. It modeled context with no cancellation, filesystem results, logging,
allocation, record equality/validity and serialization. Bus writes changed an
in-memory dictionary only; reads returned its contents. `main.writeRW`
(`0x4edf8c`) ran natively inside these fixtures. Modeled serialization is **not**
an independent encryption test. The prior [decoder tests](CARTRIDGE_DECODING.md)
have a separate scope. These fixtures do not prove hardware or full-daemon behavior.

## Selected native Flush paths

The modeled memory type uses A at 64 and B at 96, with 16-byte records. Actual
captured layout and its limitations are described in the decoder guide.

| Synthetic condition | Observed sequence after filesystem attempt and initial reads | Result code / error |
|---|---|---|
| Both records valid, both differ from RAM | Write B, readback B, write A, readback A | 1 / no error |
| Both already equal | No chip write | 3 / no error |
| Only A already equal | Write/readback B only | 1 / no error |
| Only B already equal | Write/readback A only | 1 / no error |
| A invalid, B valid | Write/readback A before B | 1 / no error |
| B invalid, A valid | Write/readback B before A | 1 / no error |
| Both invalid, modeled serialization succeeds | Write/readback A before B | 1 / no error |
| First B write persistently fails | Attempt B twice; no A write | 5 / error |
| B succeeds, subsequent A write fails | B updated, A attempt fails | 5 / error |
| First B readback repeatedly differs | Write/readback B twice; no A write | 5 / error |
| Filesystem callback returns an error | Error logging path, then B and A updates still occur | 1 / no final error in this fixture |
| Initial A or B read errors, non-cancelled context | Stop after the failed read; no chip write | 5 / error |

Seventeen selected Flush scenarios completed, including single-copy persistent
write failures. The observed loop allows two write attempts in these paths; a
successful first-copy write consumes one attempt. Result codes are observations,
not a complete recovered enum or a claim about every mode/flag combination.

Exact references: filesystem call `0x4ebfbc`; initial reads `0x4ec54c` and
`0x4ec654`; equality dispatch `0x4ec744`/`0x4ec810`; serialization `0x4eca48`;
A/B verification `0x4ecb14`/`0x4ecb9c`; A/B helper dispatch
`0x4ed860`/`0x4ed958`. The second filesystem call location is not proof of a
post-write commit: instruction address order must not replace actual control flow.

**Consequence:** a successful selected native return is not proof of an atomic
file-plus-two-copy transaction. The filesystem can diverge, and a second-copy
failure can leave partial progress. Power loss, concurrent writer exclusion and
all restart recovery branches still need separate proof.

## Readback and lower-level boundaries

Seven isolated `writeRW` fixtures confirmed:

- Matching bytes and length succeed.
- A write error returns failure without readback.
- A read error fails even when supplied bytes would match.
- Equal-length corruption, shorter, empty and longer readback fail.

Bus dispatches are `0x4ee008` (write) and `0x4ee0f0` (read); the length-qualified
comparison reaches `runtime.memequal` at `0x4ee1b4`. These are modeled I/O results,
not an EEPROM endurance or physical restoration test.

Five separate `DS2431.writeBytes` (`0x4a6ce8`) fixtures showed that this helper
propagates seek/write errors but does not independently reject a synthetic short
write with a nil error. That does **not** prove the real `os.File.Write` or kernel
produces such a result: the callback was intentionally adversarial. The outer
readback comparison is therefore important; a low-level nil error is insufficient.

Four leaf fixtures for `CartridgeRW.IncrementWriteCount` (`0x48efd4`) showed an
ordinary uint32 increment, including wrap from the maximum to zero. This is not
a reset mechanism or an ordered generation-number guarantee. A separate selected
`RWToBytes` (`0x48f678`) fixture serialized the supplied write count unchanged;
allocation, marshaling and encryption were modeled. The complete real caller
schedule that increments WriteCount is not established here.

## Reproduce the authored projection

Use the [developer setup](BUILD.md). No private inputs are required:

```sh
# LAPTOP — offline synthetic fixtures, no printer target or native writer.
python3 -m unittest discover -s tests -p test_cartridge_writeback_model.py
: "${PRIVATE_REVIEW:?existing private output directory}"
python3 tools/model_cartridge_reconciliation.py --demo \
  --output "$PRIVATE_REVIEW/writeback-demo.json"
```

Expected: 16 additional unit tests pass. The demo is explicitly SYNTHETIC and
never authorizes native writes or dispensing. Existing output files are refused.
Fourteen of the seventeen native Flush scenarios map directly to this small
projection; initial read errors and post-write mismatched readback are separately
tested native/helper cases, not silently claimed as simulated Flush features.

The model bounds byte fixtures and rejects contradictory or unknown inputs. It
reports native file-error continuation while blocking any owner commit claim.
No temporary-file rename, journal repair, chip write or vendor command is hidden
behind a modeled success.

## Empty cartridge versus manually filled tank

In the current use case the supply cartridge remains physically empty, while
resin may be added directly to the printing tank. Reporting the cartridge as
physically full would be unsupported. Tank level, cartridge consumption estimate
and supply availability must stay separate.

`TellCartridgeVolumeDispensed_mL` queues an external usage report;
`writeCartridge` adds reported volume/time rather than measuring the cartridge
contents. The new [completed-print comparison](PRINT_VOLUME_ACCOUNTING.md) finds
1,171 consumption changes correlated with tank printed-volume changes, despite
unchanged recorded dispensing time/count in that interval. The ratio matches
the configured 1.15 resin-cling factor. The complete upstream virtual caller and
all modes remain unresolved; this is not a measured-flow result.

A suitable manual-supply workflow still needs a verified pre-actuation boundary,
intact tank-level/overflow/low-level protections and truthful supply status. It
must not merely mask empty state while leaving automatic dispensing reachable.
The separate material mismatch is not corrected by clearing consumption, and a
White record must not be copied over a Clear identity. No firmware writer,
cartridge reset or panel deployment is delivered by this investigation.
