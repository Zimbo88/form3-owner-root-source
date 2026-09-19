# Optional local clock and original boot/panel artwork

These are authored transformation recipes for **your own pinned local inputs**.
No vendor RCC, executable, extracted QML tree or binary delta is redistributed.
The panel is independent source; native changes require existing authorized root
and a separate p6 transaction. Cosmetic changes are not presented as a repair
necessity or proof that the original printer fault is fixed.

## Inputs and results

Reference: selected p6, Form 3, firmware 2.5.6-2773.

| Item | Exact path / SHA256 |
|---|---|
| Original RCC | `/usr/share/Formlabs/Palantir-Form3/Palantir.rcc` — `969cae93da58f0e2be6040b48eea071f678b12e55b592d4fd7298060d2e05150` |
| Previously installed Idle-only clock RCC | `27ed8d7e10d26f4ce9d03888bd69fc2a022a4b88b4a3eb452a7c25e7249f10b4` |
| Current Idle/Ready short-date candidate RCC (not installed) | `b184f0b135dc7752098eba1acef9aa543aeaeabef006e70a38b302917753207d` |
| Original splash executable | `/usr/bin/psplash-default` — `2d51b6ea8ea27612fb5ae6a830a702891c37944f42492ba6ebaaeed319aaac2f` |
| Original Owner Root artwork splash | `9cbb2ed4bf85bacf40a2eadcb1997532f2b6bf0251164272a61d5b0ad11894ce` |

Only the `qml/BaseScreen.qml` clock binding/fragment changes in the RCC; 560 other
members remain identical. The authored `owner-ui/native/idle-clock.qmlinc` displays
`Idle DD.MM.YY HH:mm` or `Ready DD.MM.YY HH:mm`, one space, no dot/UTC suffix.
The original helper classifies Ready separately from Idle; the previous binding
excluded Ready. The revised binding allows both when there is no active atom and
no starting-print flag. Custom subtitles, active/paused prints and print startup
retain their original text. These UI predicates do not prove mechanical safe idle.
The Europe/Berlin rule is
bounded/tested for 2020–2037; invalid dates are unavailable. This is not automatic
international timezone selection. No global NTP/timezone, license time, status
engine or safety decision is changed. I confirmed the local time and normal display
operation on my printer for the previous Idle-only version; the Ready/short-year
candidate has only offline validation so far. It was deliberately not installed
or activated during the live print observation. Real header fit and target Qt
rendering for this revision remain acceptance checks after the print is finished.

The current symbol is original terminal/root geometry with orange `rooted` and
geometric OWNER text. No manufacturer logo is reused. Source:
`owner-ui/native/signature-mark.svg`. `tools/build_signature_brand.py` verifies the
corresponding inline panel, native canvas and repository mark. Native scale is 130%
on an unchanged 1280×720 canvas; panel background remains transparent. The wordmark
font attribution is in [rights and credits](RIGHTS_AND_RELEASE.md).

## LAPTOP: build and validate, without installation

Provide an explicitly extracted, pinned copy. Never operate through a writable
loop device or replay the original filesystem journal. Use the host dependencies
and mandatory namespace isolation in [setup](BUILD.md).

```sh
# LAPTOP — new ignored private output; original input remains untouched.
: "${FORM3_ROOTFS_COPY:?reviewed copied rootfs directory}"
python3 tools/build_signature_brand.py
python3 tools/build_native_display_review.py --rootfs "$FORM3_ROOTFS_COPY" \
  --output research-private/native-display-review-01
```

Expected: `installed=false`, the current short-date candidate and artwork hashes
above, isolated authored
Qt clock/logo render checks, unchanged source hashes and private per-file receipts.
The complete native candidates and rendered raw images remain ignored. Optional
clock-only build:

```sh
# LAPTOP — transformation recipe; no target execution or install.
: "${FORM3_ROOTFS_COPY:?reviewed copied rootfs directory}"
python3 tools/build_native_clock_review.py \
  "$FORM3_ROOTFS_COPY/usr/share/Formlabs/Palantir-Form3/Palantir.rcc" \
  --output research-private/clock-only-review-01
```

A wrong hash, malformed resource, unexpected source binding, allocation overflow,
active/external SVG content or existing output stops. The splash builder preserves
all executable bytes outside its bounded image allocation; it is not a bootloader
patch. Preserve source/candidate hashes and all original bytes privately.

## NORMAL PRINTER: separately reviewed transaction

Read `tools/native_display_transaction.py --help` on LAPTOP first. The current
**separate** profiles are:

- `ready-clock`: previously installed Idle-only local clock → current Idle/Ready
  short-date candidate; no logo change.
- `ready-clock-factory`: original RCC → current Idle/Ready short-date candidate.
- `local-clock-factory`: historical original RCC → previous Idle-only local clock;
  this profile does not accept the current builder's output.
- `owner-root-splash-factory`: original splash → current original project mark.
- `owner-root-splash`: prior pinned Signature splash → current project mark.

Older two-file profiles exist for historical receipts. Do not use the default
`initial-local` with a current clock/splash build: its prior splash pin is different.
Each profile requires the exact existing source; do not change pins to accept an
unknown installed modification.

A future authorized deployment transfers only verified authored transaction source
and the privately built candidate into new `/run/owner-...` staging, using pinned
SSH/SFTP. Clock staging basename is `clock.rcc`; splash is `splash.bin`. Use separate
plans, explicit profiles and a verified current owner installation. Plan path must
be a new JSON under `/run/owner-NAME/`, as required by the tool. Example shape:

```sh
# NORMAL PRINTER — PLAN ONLY; after target/idle context and transferred-file checks.
: "${NATIVE_TOOL:?hash-verified transaction Python source in RAM}"
: "${NATIVE_STAGING:?new verified RAM staging directory}"
: "${NATIVE_PLAN:?new /run/owner-NAME/clock-plan.json path}"
python3 -B -S "$NATIVE_TOOL" plan --profile ready-clock-factory \
  --staging "$NATIVE_STAGING" --plan "$NATIVE_PLAN"
```

Use `ready-clock` instead when the installed file has the exact previous local-clock
hash. Never restart Palantir or activate the replacement during a print, preparation,
filling, homing, or an uncertain state. This transaction tool does not establish
hardware safe idle: fresh observation and the supervised activation gate remain
necessary.

Inspect exact target identity, source/candidate hashes, paths, permissions and the
returned canonical plan digest. Preserve the plan on LAPTOP. The separately gated
apply uses `--profile`, `--plan`, `--plan-sha256`, `--staging` and a new private
`--backup` beneath `/data/owner-maintenance/native-display/`. It writes only after
the supported target, current hashes, ownership and plan match. Filesystem write
state and restart/boot observation are separately reviewed; the tool never mounts,
restarts vendor UI, writes QSPI or reboots. No automatic display update is hidden in
a panel package.

Rollback uses the same profile/plan/digest and the matching backup. It validates
saved bytes and current before/after states, restores original ownership/modes,
retains originals and refuses unrelated edits. A manufacturer upgrade can replace
these p6 files. A p7 backup alone does not make the native modification update-proof.
The current logo was installed/read back in the reference deployment; visual
confirmation of that latest original mark on a later boot is a distinct acceptance
gate. Never fabricate a physical observation from a render or hash match.
