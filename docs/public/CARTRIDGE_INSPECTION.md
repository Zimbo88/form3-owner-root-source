# Inspect a copied cartridge record without changing it

These envelope-only laptop tools inspect a private copy and pinned firmware metadata. They do
not connect to a printer, decrypt with device keys, encode a reset or change a
cartridge. They are useful for separating a filesystem mirror, a raw data-area
backup, a decoded record and a proven restoration procedure.

## Prerequisites

Use the [developer setup](BUILD.md), your own separately acquired inputs and a new
private output directory. Do not obtain someone else's cartridge identity/key or
publish your raw capture. An image's SHA256 must come from your retained acquisition
receipt, not from a value supplied by an untrusted download. A raw EEPROM backup
is not automatically a backup of ROM, scratchpad or protection registers.

```sh
# LAPTOP — explicitly copied regular files only; no device path or network target.
: "${EEPROM_COPY:?private copy of the reviewed 128-byte data area}"
: "${EEPROM_SHA256:?independently retained acquisition SHA256}"
: "${TKD_COPY:?private authenticated 2.5.6-2773 TankCartridgeDaemon copy}"
: "${PRIVATE_REVIEW:?new output directory below research-private}"
umask 077
mkdir -m 700 -- "$PRIVATE_REVIEW"
python3 tools/inspect_cartridge_memory.py "$EEPROM_COPY" \
  --sha256 "$EEPROM_SHA256" --output "$PRIVATE_REVIEW/envelope.json"
python3 tools/inspect_cartridge_layout.py "$TKD_COPY" \
  --output "$PRIVATE_REVIEW/layout.json"
```

Expected: exact input hash/size checks, metadata for two candidate 16-byte records,
whether they match, and a static type/call catalog. The firmware tool pins one exact
binary hash; do not remove the pin to claim support for another version. It reads
ELF/Go metadata without executing vendor software or extracting keys. Corrupt,
truncated, unsupported or symlink inputs fail. Unknown RW versions remain unreviewed.

## Interpreting the result

- `rw_copies_equal` only compares bytes. It does not mean checksum-valid or full.
- `checksum_verified` and `write_supported` are **false** by design.
- A saved manufacture date does not prove current resin condition or compatibility.
- The 11-byte decrypted payload layout is distinct from the 16-byte encrypted
  envelope. The helper for already-obtained plaintext does not authenticate it.
- A monotonic usage model shows why lowering one mirror may not lower merged
  consumption. It excludes the complete native write-count/recovery state machine.
- A material mismatch, supply usage estimate and actual tank level are separate
  decisions. Do not change a material identifier to disguise incompatible contents.

No recovery command is provided: write ordering, native concurrent writers,
protection state, power-loss recovery and actual readback must be demonstrated
before a native reset can be treated as reversible. A backup alone is insufficient.
Existing filling faults and all vendor interlocks remain separate prerequisites.

The fixtures in `tests/test_cartridge_memory.py` contain authored synthetic bytes,
not real cartridge data or keys. They test hash/size/type rejection, unequal copies,
unknown versions, plaintext shape and the limited monotonic model. They do not test
physical writes, native checksum validation, chip recovery or printing. Run the
standard disconnected suite described in [BUILD](BUILD.md).

## Optional decoded inspection

The separate [copied-memory decoder](CARTRIDGE_DECODING.md) now validates the
reviewed C/0 + RW/1 format using privately supplied inputs. Its fixtures and
selected-function checks are distinct from the envelope-only tests above. It
exports selected usage values and comparisons, with no native write support.
