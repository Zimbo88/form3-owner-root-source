# Bounded live print observation

This recorder observes an explicitly authorized, already rooted reference printer
through its existing pinned SSH configuration. It never starts a print, acknowledges
a fault, queries a destructive error queue, rotates a log, runs vendor collectors,
or changes display/services. The operator controls the physical print attempt.

## Verified scope and boundaries

**LIVE OBSERVATION:** the authored target observer executed with Python 3.5.3 on
the reference ARMv7 Linux 4.9.65+, p6 firmware 2.5.6-2773, owner release 0.5.8-review.
Log bytes, temperature signals, state transitions and consumable filesystem mirrors
arrived on the laptop. This is a capture test, not proof of successful printing or
safe refill/reset behavior. Target identity/version checks deliberately refuse other
contexts; do not remove them simply to connect to a different installation.

| Source | Acquisition | Interpretation and limits |
|---|---|---|
| `/data/logs`, `/var/volatile/log` | Allowlisted regular log/CSV/TSV/MessagePack names; incremental bytes | Raw plaintext/private records, not public exports. No symlinks, FIFOs or process output pipes. |
| Kernel ring | Bounded `dmesg` snapshots, no clearing | Last untransmitted records may be lost on power failure. |
| `/proc` and thermal sysfs | Approximately 1-second samples; selected process snapshots every 10 seconds | SoC temperatures are not resin/heater temperatures. Process presence is not health. |
| Selected D-Bus signals | Passive `dbus-monitor`, no vendor method calls | Signals from shared sender connections can include more interfaces than their service names suggest. Retain actual interface/member and raw typed values; do not invent units. |
| `/data/Cartridges`, `/data/Tanks` | Bounded JSON byte snapshots every approximately 10 seconds | Persistent mirrors, not a physical chip image or guaranteed current RAM state. Filenames and JSON keys can contain secrets. |
| Two named diagnostic SQLite stores | Main/WAL/SHM/journal byte copies where present | No SQLite connection or replay on the printer; concurrent file copies are not a consistent database transaction. |

The supply cartridge and printing tank are separate. Nominal cartridge capacity and
estimated consumption do not measure physical remaining volume. A newly captured
zero consumption field is not proof of a physically full cartridge. Vendor flush
timing can delay persistent mirrors; do not force a flush or call write methods to
make a snapshot look current. Native lifetime counters and owner refill accounting
remain separate. No cartridge/tank chip, identity, counter or mode is changed.

All recorder file descriptors are read-only, with NOATIME where supported. The
normal operating system still writes logs and state, including records generated
by SSH and D-Bus observation. This is not a forensically write-free normal boot.

## Explicit laptop invocation

Use the reviewed source in `tools/print_capture_agent.py`,
`tools/record_print_session.py`, `tools/print_state_snapshot.py` and
`tools/record_print_state.py`. Host tools need current Python; only the two target
sources execute under the printer's Python 3.5. The target sources stream through
SSH stdin and are not installed on the printer. No keys or passwords are embedded.

```sh
# LAPTOP — authenticated reference printer only; no discovery or network scan.
: "${OWNER_SSH_CONFIG:?existing reviewed strict host-key-pinned SSH config}"
: "${OWNER_SSH_ALIAS:?explicit alias in that config}"
: "${PRINT_SESSION:?new path beneath research-private}"
umask 077
mkdir -m 700 -- "$PRINT_SESSION"
python3 tools/record_print_session.py run --session "$PRINT_SESSION" \
  --ssh-config "$OWNER_SSH_CONFIG" --ssh-alias "$OWNER_SSH_ALIAS" --seconds 43200
```

The command stays running. A second laptop process can run the independent bounded
state snapshot recorder against the same session:

```sh
# LAPTOP — also remains running; writes private laptop files only.
python3 tools/record_print_state.py --session "$PRINT_SESSION" \
  --ssh-config "$OWNER_SSH_CONFIG" --ssh-alias "$OWNER_SSH_ALIAS" --seconds 43200
```

Before tank insertion or print start, verify `status.json`: state `recording`,
fresh saved-through time, received samples, running signal observer, and completed
initial log backlog. Verify `consumable-state/status.json` separately; neither
process proves the other's health. A missing source must be reported as unavailable.
Keep the laptop powered, awake and connected. A sleep inhibitor may accompany the
bounded capture; it cannot protect against power loss or forced shutdown.

```sh
# LAPTOP — these affect recording metadata only, not the printer.
python3 tools/record_print_session.py status --session "$PRINT_SESSION"
python3 tools/record_print_session.py mark --session "$PRINT_SESSION" \
  --event print_start_requested
python3 tools/record_print_session.py stop --session "$PRINT_SESSION"
```

The local STOP marker stops both recorders. A live session may contain separately
preserved continuation segments: stop each active segment and the state recorder's
parent session. Keep the private active-recorder receipt so no process is orphaned.

## Provenance, bounds and failure analysis

Each chunk carries SHA256, remote wall/monotonic time and laptop receipt time. Log
chunks also include file identity, byte offsets, truncation generation and baseline
classification. Keep baseline history separate from newly observed print events.
State objects use content-addressed private storage; the private index retains
original paths, timestamps and a before/after metadata-stability flag. Stability
does not prove atomic application-level consistency.

Current bounds: 12-hour requested duration, 4 GiB per stream session, 512 MiB or
30 minutes per SSH observer connection, 128 MiB D-Bus output per connection,
16 MiB initial log tail per file, 192 open log descriptors. The independent mirror
store is limited to 256 MiB. A connection boundary repeats available baseline bytes;
deduplicate by boot/file identity and offset, not just equal text. Reconnect only
to the same pinned alias. Host-key/credential/invariant failures stop rather than
loosening authentication. A 30-second stream silence triggers bounded reconnect.

Unlinked rotated logs are retained until fully read and quiet for 30 seconds, then
retired with an explicit coverage-boundary record. A later write to such an unlinked
file is outside coverage. Copy-truncate followed by fast regrowth can evade simple
size-based truncation detection. Limits, WLAN outages, shutdown and rotation mean
this is not a promise that every possible firmware event is captured. Overlapping
recorder replacement preserves both segments and records the overlap separately.

For a failure, correlate operator markers, Sauron state/error signals, Palantir UI
events, thermal/level/fan evidence, consumable mirrors and kernel/process changes.
Distinguish an operator cancellation from an autonomous fault. A print-dispatch log
does not prove that the operator pressed Start; queued/remote/automatic dispatch
needs a traced caller or a separate observation. Report clock uncertainty and data
gaps, not an invented root cause. Store raw model/job data and credentials privately;
only reviewed allowlisted findings may enter Git.

**OFFLINE TESTS:** synthetic tests exercise hash/length/truncation rejection,
read-only regular files, symlink/FIFO refusal, append/rotation, bounds, private
session paths, passive signal filters and Python 3.5 grammar. They never connect to
the printer. The measured observer load during the initial live preparation was
approximately 4–5% of one CPU core; that sample is not a universal overhead bound.
