# Root to secure SSH: the command-by-command walkthrough

I used temporary Rescue V2 root to back up my printer, install separate owner
services, and return to my own original QSPI for normal operation. This is the
normalized, reproducible command sequence, including the transfers between
machines. It is not a replay of failed attempts or a universal unlock script.
Read the complete page once before connecting hardware. Execute one numbered
step at a time; **a failure stops that step, not a reason to paste the next block**.

The demonstrated installation was on Form 3, selected **p6 / 2.5.6-2773**. The
current source is **0.5.9-review**, tested offline but not yet installed on my
printer. It does not make another firmware/board automatically compatible.
The current rescue builder requires the reference factory SHA256; another hash
needs [profile engineering](ROOT_GUIDE.md#4-a-different-factory-hash-profile-engineering-not-pin-removal).
Do not replace my hash with yours merely to suppress a failure.

## 0. Terminals, variables and what changes

| Label | Where to type | Shell / privilege |
|---|---|---|
| LAPTOP A | Ubuntu source checkout | Bash, ordinary user; explicit sudo for host dependencies only |
| PI B | Physical Pi terminal or its already authenticated SSH session | Bash; sudo only at marked Pi operations |
| RESCUE C | `nc` connection from PI to the temporary printer shell | BusyBox ash, root, initially RAM only |
| LAPTOP D | Second laptop terminal for receivers / SSH | Bash, ordinary user |
| NORMAL PRINTER | Later pinned owner SSH session | Existing root account, key authentication |
| PHYSICAL | Bench operation, not a shell command | Printer/programmer power and clip handled deliberately |

Variables do **not** automatically cross terminals. Set them again when instructed.
Do not paste a LAPTOP command into RESCUE. All `read -r -p` prompts below belong to
Bash on LAPTOP/PI; the minimal rescue has no Python until the verified mounted
runtime is available. Do not type prompt prefixes such as `$` or `root#`.

| When | Changed area | Exact logical change / recovery |
|---|---|---|
| Steps 1–5 | Laptop/Pi private files | Reads, manifests, authored build outputs; preserve originals |
| Step 6 | Physical QSPI | Rescue environment/payload only; full-chip programming can erase/rewrite larger sectors, so all 4 MiB must verify |
| Steps 7–12 | Pi networking, printer RAM | Isolated link, `/run` inputs, read-only mounts; no intended eMMC writes |
| Step 13 if approved | Real p6/p7 journals/metadata | Normal kernel journal replay on the working device; never original images |
| Step 14 | Real p6/p7 | [Exact file map](#what-the-installer-writes-exactly); transaction retains before/after data |
| Step 15 | Physical QSPI | Restore this printer's original 4 MiB; retain added owner files on eMMC |
| Steps 16–18 | Pi temporary DHCP, normal OS | Vendor normal boot writes its own state; owner host identity/firewall/runtime start |
| Step 19 | Laptop / printer RAM | Strict SSH profile, negative authentication and SFTP test; no printer firmware replacement |

No stage writes p1/p2/p5, `/etc/shadow`, boot0/boot1, calibration, consumable
memory or manufacturer signing/SSH identity as an owner installation action.
Filesystem metadata, journal blocks and normal vendor activity are separate from
this logical file list. The panel, logo and clock are optional; root does not
require those display modifications.

## 1. LAPTOP — choose the source and private workspace

Use the reviewed source export or its clean source-edition clone. A public copy
must contain the reviewed selection, not the producer's private research history.
**Do not initialize a repository in acquisition data.**

```sh
# LAPTOP — existing source directory; no printer contact.
read -r -p 'Absolute reviewed source directory: ' FORM3_SOURCE
cd -- "$FORM3_SOURCE" || exit 1
test -f owner-maintenance/ownerctl.py || exit 1
cat VERSION
read -r -p 'NEW absolute private deployment directory: ' OWNER_PRIVATE
umask 077
test ! -e "$OWNER_PRIVATE" || exit 1
mkdir -m 700 -- "$OWNER_PRIVATE" || exit 1
export FORM3_SOURCE OWNER_PRIVATE
```

**Expected:** the intended version and a new private directory. Keep it outside
the clone and evidence directory. It will contain private keys/receipts: never
upload it. In a Git clone, inspect `git status --short`, `git remote -v` and
`git rev-parse HEAD`; do not reset somebody else's local work.

```sh
# LAPTOP — install host build/test tools, never in RESCUE.
sudo apt-get install python3 python3-cryptography python3-msgpack python3-pil \
  python3-capstone bubblewrap util-linux iproute2 openssl openssh-client \
  libsodium23 git nodejs tzdata dnsmasq-base make gcc patch curl file binutils qemu-user pv
python3 --version
python3 tools/developer_check.py --output build/tutorial-check-01.json
```

**Expected:** Python 3.12+ on the laptop; the actual fixture count and no errors.
The [build guide](BUILD.md) explains namespace privileges and optional dependencies.
Do not weaken isolation if a test cannot start. Reuse authenticated cached build
archives where available; no downloaded printer firmware is required for fixtures.

## 2. PI — establish the management prerequisite

Use an existing Pi management SSH alias, here **`form3-pi`**. This is a placeholder
alias for **your** Pi, not a discoverable printer name. Configure and verify its
host fingerprint through the physical Pi console before relying on it. A newly
seen host key must be correlated; a changed known key must not be ignored.

```sh
# PI — physical/admin console, public fingerprint only.
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
uname -a
sudo apt-get install flashrom netcat-openbsd dnsmasq-base
flashrom --version
nc -h
```

The package operation changes Pi packages, not printer storage. `dnsmasq-base`
supplies the later manual DHCP binary; this page does not enable a system service.
`nc -h` may return a nonzero help exit; inspect that it identifies OpenBSD netcat.

```sh
# LAPTOP — form3-pi must already be an authenticated alias in ~/.ssh/config.
export FORM3_PI_SSH=form3-pi
ssh -o StrictHostKeyChecking=yes "$FORM3_PI_SSH" 'id; uname -a'
```

**Expected:** the Pi's user and architecture, never the printer's root shell.
The later profile helper's `--jump-alias` uses this same laptop default SSH config.
It does not copy a private laptop key to the Pi.

## 3. PHYSICAL / PI — identify the chip and acquire three reads

Complete the [measurement table](ROOT_GUIDE.md#2-physical-resolve-the-electrical-gate-before-connecting-a-clip)
first. My documented route removed the SOM and clipped the still-soldered flash;
it did not need a soldered UART. That does not establish another board's pinout.
The [illustrated Pi 5 and clip guide](PI5_CLIP_GUIDE.md) explains the recorded
header mapping, chip orientation, cable continuity and voltage checks in order.

**Unresolved reference detail:** available photos did not prove the full flash
suffix/shared-rail arrangement. Therefore the command shapes below have no default
chip, voltage, SPI node or frequency. They are **blocked until those values and
the circuit/power plan are independently established**. The acknowledgements below
record a human decision; they do not measure a voltage or validate wiring.

```sh
# PI — enter the independently identified part/programmer, not guesses.
read -r -p 'Reviewed flashrom programmer string: ' QSPI_PROGRAMMER
read -r -p 'Exact supported flashrom chip name from part identification: ' QSPI_CHIP
test -n "$QSPI_PROGRAMMER" && test -n "$QSPI_CHIP" || exit 1
umask 077
mkdir "$HOME/form3-root-qspi" || exit 1
cd "$HOME/form3-root-qspi" || exit 1
flashrom --help
```

The upstream Linux-SPI syntax is `linux_spi:dev=DEVICE,spispeed=KHZ`; the complete
string is **one quoted argument**, not a shell command. Determine the actual
SPI device from the Pi configuration. Enable the Pi SPI controller using the
appropriate Pi OS procedure *before* attaching the clip; do not guess a header
pin from `/dev/spidev` numbering. [Upstream Pi instructions](https://github.com/flashrom/flashrom/blob/main/doc/user_docs/raspberry_pi.rst).

After confirmed power/orientation/contact checks, run **each** separate read:

```sh
# PI — PHYSICAL QSPI READS. Printer power removed; reviewed programmer supply only.
test ! -e read1.bin && test ! -e read2.bin && test ! -e read3.bin || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" -r read1.bin -o read1.log || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" -r read2.bin -o read2.log || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" -r read3.bin -o read3.log || exit 1
sudo chown "$(id -u):$(id -g)" read1.bin read2.bin read3.bin read1.log read2.log read3.log
chmod 444 read1.bin read2.bin read3.bin
stat -c '%n %s bytes' read1.bin read2.bin read3.bin
sha256sum read1.bin read2.bin read3.bin
cmp read1.bin read2.bin && cmp read1.bin read3.bin || exit 1
```

**Expected:** 4,194,304 bytes each, identical hashes and successful tool logs.
Retain failed reads. Independent reads are not file copies; re-establish contact
only using the approved unpowered procedure if repeatability needs checking.
Equal reads and chip detection alone do not certify electrical safety.

```sh
# LAPTOP — retrieve into a NEW private directory.
mkdir "$OWNER_PRIVATE/qspi-reads" || exit 1
scp -p "$FORM3_PI_SSH:form3-root-qspi/read1.bin" "$OWNER_PRIVATE/qspi-reads/"
scp -p "$FORM3_PI_SSH:form3-root-qspi/read2.bin" "$OWNER_PRIVATE/qspi-reads/"
scp -p "$FORM3_PI_SSH:form3-root-qspi/read3.bin" "$OWNER_PRIVATE/qspi-reads/"
python3 tools/inspect_qspi_reads.py \
  --read "$OWNER_PRIVATE/qspi-reads/read1.bin" \
  --read "$OWNER_PRIVATE/qspi-reads/read2.bin" \
  --read "$OWNER_PRIVATE/qspi-reads/read3.bin" \
  --output "$OWNER_PRIVATE/qspi-read-review.json"
```

Save the Pi logs/measurement notes privately as well. **Expected:** matching
content plus validated boot headers and active environment CRC, not just an FF
image. Protect the retained reads with `chmod 444` and make an independent backup.

## 4. LAPTOP — build the RAM rescue and see the exact patch

```sh
# LAPTOP — reads the local factory copy, never a programmer.
export FACTORY_COPY="$OWNER_PRIVATE/qspi-reads/read1.bin"
sha256sum "$FACTORY_COPY"
python3 tools/build_rescue.py --factory "$FACTORY_COPY" \
  --output-dir build/tutorial-rescue-01
python3 tools/build_qspi_rescue.py --factory "$FACTORY_COPY" \
  --initramfs build/tutorial-rescue-01/form3-rescue.cpio.gz \
  --output-dir build/tutorial-qspi-01
cat build/tutorial-rescue-01/busybox.file.txt
cat build/tutorial-qspi-01/VALIDATION_REPORT.md
cat build/tutorial-qspi-01/diff_ranges.txt
sha256sum build/tutorial-qspi-01/form3_qspi_RESCUE_V2.bin
```

The first build may obtain only the pinned public BusyBox/toolchain archives in
`rescue/sources.lock.json`; add `--offline` once the exact cache is available.
Outputs must be new. **STOP** on an unknown factory hash, CRC, slot/profile or
non-FF reserve. Review generated environment reports privately; they can contain
device data. The authentic reference hash is in [ROOT_GUIDE](ROOT_GUIDE.md).

**What changes in the image:** `0x000000–0x0bffff` remains identical; only the
active environment `0x0c0000–0x0c3fff` and the compressed RAM payload beginning
`0x100000` may differ. `silent` is removed, rescue boot arguments/command and CRC
change. The genuine eMMC kernel/DTB remain the boot inputs. No kernel, vendor
application or eMMC filesystem is patched by this build.

## 5. LAPTOP / PI — stage the reviewed rescue image

```sh
# LAPTOP — public checksum, private device-derived image transfer.
scp -p build/tutorial-qspi-01/form3_qspi_RESCUE_V2.bin \
  "$FORM3_PI_SSH:form3-root-qspi/rescue-reviewed.bin"
sha256sum build/tutorial-qspi-01/form3_qspi_RESCUE_V2.bin
```

```sh
# PI — compare with the independently retained LAPTOP checksum.
cd "$HOME/form3-root-qspi" || exit 1
read -r -p 'Expected rescue SHA256 from the laptop review: ' IMAGE_SHA256
printf '%s  rescue-reviewed.bin\n' "$IMAGE_SHA256" | sha256sum -c - || exit 1
test "$(stat -c %s rescue-reviewed.bin)" = 4194304 || exit 1
```

**Expected:** exact equality. This still only stages a file. Do not use a rescue
image from a different printer or pass the factory hash as the rescue hash.

## 6. PHYSICAL / PI — deliberate rescue programming and complete readback

This block is the **manual write boundary**, not a runnable project installer.
Only after step 3's electrical gate, successful three-read review, image validation
and a recovery plan may it be executed. A full-image flashrom write can erase
sectors containing unchanged bytes; preservation is established by the complete
readback, not a promise that SPL sectors are electrically untouched.

```sh
# PI — HARDWARE WRITE, only after the independent electrical/profile review.
: "${QSPI_PROGRAMMER:?reviewed programmer}"
: "${QSPI_CHIP:?identified part}"
: "${IMAGE_SHA256:?reviewed rescue hash}"
read -r -p 'Type WRITE REVIEWED RESCUE after completing the physical gate: ' APPROVAL
test "$APPROVAL" = 'WRITE REVIEWED RESCUE' || exit 1
printf '%s  rescue-reviewed.bin\n' "$IMAGE_SHA256" | sha256sum -c - || exit 1
test ! -e rescue-readback.bin || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" \
  -w rescue-reviewed.bin -o rescue-write.log || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" \
  -r rescue-readback.bin -o rescue-readback.log || exit 1
sudo chown "$(id -u):$(id -g)" rescue-readback.bin rescue-write.log rescue-readback.log
cmp rescue-reviewed.bin rescue-readback.bin || exit 1
sha256sum rescue-reviewed.bin rescue-readback.bin
```

No `--force`, separate erase, partial-layout shortcut or verification suppression.
[Upstream flashrom operation semantics](https://github.com/flashrom/flashrom/blob/main/doc/classic_cli_manpage.rst).
**Mismatch:** preserve files/logs, keep printer power off, resolve the programming
problem. Do not try normal boot to see whether a mismatch happens to work.

**PHYSICAL:** remove programmer power and every clip/programmer connection before
restoring the SOM, heatspreader and enclosure. Restore only the printer's intended
connections, attach the isolated Ethernet cable, then power on deliberately.

## 7. PI — configure and verify the isolated rescue cable

```sh
# LAPTOP — transfer one authored Pi helper, no automatic execution.
scp -p scripts/pi_rescue_link_setup.sh \
  "$FORM3_PI_SSH:form3-root-qspi/pi_rescue_link_setup.sh"
sha256sum scripts/pi_rescue_link_setup.sh
```

```sh
# PI — compare the helper hash first, then change eth0 only.
sha256sum "$HOME/form3-root-qspi/pi_rescue_link_setup.sh"
ip -br addr
ip -4 route
sudo bash "$HOME/form3-root-qspi/pi_rescue_link_setup.sh" --apply
ip -4 route get 10.0.0.77
ip -4 addr show dev eth0
test ! -e /sys/class/net/eth0/master || exit 1
sysctl net.ipv4.ip_forward net.ipv4.conf.eth0.forwarding
sysctl net.ipv6.conf.eth0.disable_ipv6
sudo nft list ruleset
```

**Expected:** direct route via eth0, source `10.0.0.1`, no bridge, forwarding/NAT
or conflicting route. Review iptables rules too if that firewall is used instead
of nftables. Missing inspection tools are a gap, not evidence of no rules.
The helper temporarily releases eth0 from NetworkManager, replaces eth0 IPv4
addresses/routes, disables its forwarding and IPv6; it does not configure WLAN.
Retain the Pi's before-state for later restoration. These `10.0.0.*` values are
the selected rescue protocol, not the printer's normal home-LAN addressing.

## 8. PI to RESCUE — identify the shell, then back up all three devices

```sh
# PI — open RESCUE C. A visible prompt/local echo is not guaranteed.
nc 10.0.0.77 2324
```

```sh
# RESCUE — these commands must return printer context, not Pi context.
printf '\nFORM3 RESCUE IDENTITY\n'
id
uname -a
cat /proc/device-tree/model
printf '\n'
cat /proc/cmdline
cat /proc/mounts
cat /proc/partitions
cat /sys/class/net/eth0/address
blockdev --getsize64 /dev/mmcblk0
for device in /dev/mmcblk0 /dev/mmcblk0p6 /dev/mmcblk0p7 /dev/mmcblk0boot0 /dev/mmcblk0boot1; do
    printf '%s ' "$device"
    blockdev --getro "$device"
done
/bin/busybox --list
printf '\nFORM3 RESCUE CHECK COMPLETE\n'
```

**Expected:** UID0, armv7l, Formlabs model, `rdinit=/init`, 15,678,308,352-byte
user area, all listed protection flags `1`, and no eMMC mount. Confirm the applets;
there is no rescue `scp`, `tar`, `cp`, `chmod` or Python. A wrong context stops.
Retain the eth0 MAC privately for step16; it is not a public example value.

For the large image, the reference `tee`-based backup was slow. The successful
fast route uses direct block streaming plus a separate source hash while the
device remains read-only. Run these on the printer and retain output privately:

```sh
# RESCUE — READ ONLY; this takes time, keep the session open.
sha256sum /dev/mmcblk0
sha256sum /dev/mmcblk0boot0
sha256sum /dev/mmcblk0boot1
blockdev --getsize64 /dev/mmcblk0boot0
blockdev --getsize64 /dev/mmcblk0boot1
```

Start the receiver **first**, in LAPTOP D from the clone root. Enter the measured
size and the corresponding just-recorded source hash; do not copy my device hash.

```sh
# LAPTOP — receiver 1; leave running until the sender finishes.
FORM3_SOURCE=$PWD
test -f scripts/receive_emmc_via_pi.sh || exit 1
export FORM3_PI_SSH=form3-pi
read -r -p 'Source user-area SHA256: ' SOURCE_SHA256
bash scripts/receive_emmc_via_pi.sh own-mmcblk0-01.img 15678308352 "$SOURCE_SHA256"
```

When it reports the Pi listener, send from the existing RESCUE C shell:

```sh
# RESCUE — source is read; output goes to isolated Pi TCP, not another block device.
dd if=/dev/mmcblk0 bs=1M | nc 10.0.0.1 9000
```

Repeat that receiver/sender pair for the **two additional rows**, one at a time:

| LAPTOP receiver arguments | RESCUE sender |
|---|---|
| `own-boot0-01.img 4194304 "$SOURCE_SHA256"` with boot0's hash | `dd if=/dev/mmcblk0boot0 bs=1M \| nc 10.0.0.1 9000` |
| `own-boot1-01.img 4194304 "$SOURCE_SHA256"` with boot1's hash | `dd if=/dev/mmcblk0boot1 bs=1M \| nc 10.0.0.1 9000` |

The table's displayed pipe is a shell `|`. The exact measured sizes must match
before using these reference numbers. The laptop helper saves images under
`hardware/emmc/original/`, with hashes/receipts and `.incomplete` on failure.
Pi stdout streams straight to the laptop: no 16-GB Pi storage is required.
Retain interrupted images and retry to a new basename. Never acquire RPMB here.

```sh
# LAPTOP — verify receipts/files, then protect successful originals and copy independently.
cd hardware/emmc/original || exit 1
sha256sum -c own-mmcblk0-01.img.sha256
sha256sum -c own-boot0-01.img.sha256
sha256sum -c own-boot1-01.img.sha256
test ! -e own-mmcblk0-01.img.incomplete || exit 1
test ! -e own-boot0-01.img.incomplete || exit 1
test ! -e own-boot1-01.img.incomplete || exit 1
chmod 444 own-mmcblk0-01.img own-boot0-01.img own-boot1-01.img
cd "$FORM3_SOURCE" || exit 1
```

Inspect all three `.receipt.txt` files: source/receiver hashes and byte counts
must agree. A `.sha256` file alone only checks the saved image against itself.

## 9. LAPTOP — create independent owner keys and a signed install package

Use the private directory from step 1; do not recreate or overwrite it. These are
**your new keys**. The SSH client key and package signer have different roles.

```sh
# LAPTOP — new named keys; never ~/.ssh/id_ed25519 and never fixture/vendor keys.
umask 077
test ! -e "$OWNER_PRIVATE/owner-client-ed25519" || exit 1
test ! -e "$OWNER_PRIVATE/owner-package-signing.pem" || exit 1
ssh-keygen -t ed25519 -f "$OWNER_PRIVATE/owner-client-ed25519" -C owner-maintenance
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$OWNER_PRIVATE/owner-package-signing.pem"
openssl pkey -in "$OWNER_PRIVATE/owner-package-signing.pem" -pubout \
  -out "$OWNER_PRIVATE/owner-package-public.pem"
ssh-keygen -lf "$OWNER_PRIVATE/owner-client-ed25519.pub" -E sha256
sha256sum "$OWNER_PRIVATE/owner-package-public.pem"
read -r -p 'Retained signer public PEM SHA256: ' OWNER_SIGNER_PIN
export OWNER_SIGNER_PIN
```

Choose a client-key passphrase; step 19 shows an agent to avoid repeating it.
The package signer is an unencrypted private file protected by the private
directory: preserve it independently and never send it to Pi/printer/Git.

```sh
# LAPTOP — current source version, not an old copied command's version string.
OWNER_VERSION=$(cat VERSION)
INSTALL_PACKAGE="$OWNER_PRIVATE/owner-install.tar.gz"
python3 tools/build_owner_package.py build --kind install --version "$OWNER_VERSION" \
  --signing-key "$OWNER_PRIVATE/owner-package-signing.pem" \
  --public-key "$OWNER_PRIVATE/owner-package-public.pem" \
  --signer-sha256 "$OWNER_SIGNER_PIN" --package "$INSTALL_PACKAGE"
python3 tools/build_owner_package.py verify --package "$INSTALL_PACKAGE" \
  --public-key "$OWNER_PRIVATE/owner-package-public.pem" --signer-sha256 "$OWNER_SIGNER_PIN"
sha256sum "$INSTALL_PACKAGE"
```

**Expected:** verified `kind=install`, current version, package/manifest hash and
the retained signer pin. The ZIP/source archive is not the signed install package.

```sh
# LAPTOP — Pi service-side source is the sole initially authorized SSH client.
(set -C; printf '%s\n' \
  '{"interface":"eth0","client_network":"10.0.0.1/32","panel_enabled":false}' \
  > "$OWNER_PRIVATE/owner-service.json")
```

This config matches the **Pi jump-host topology on this page**. A dedicated laptop
Ethernet topology needs its own actual source address. No ordinary WLAN access
or panel listener is enabled by this initial config. Do not broaden it to conceal
a routing problem.

## 10. LAPTOP / PI / RESCUE — transfer the small public installation inputs

Obtain `RESCUE_RUNTIME_SHA256SUMS` from the reviewed source export. In a clean Git
clone, `python3 tools/export_public_source.py --output build/tutorial-source-01`
creates it under `build/tutorial-source-01/source/`; in an existing export it is
already in its root. This file contains hashes only. Do not substitute a checksum
list generated from unverified live files.

```sh
# LAPTOP — copy only these allowlisted files into a NEW outgoing directory.
read -r -p 'Absolute reviewed RESCUE_RUNTIME_SHA256SUMS path: ' RUNTIME_SUMS
mkdir "$OWNER_PRIVATE/transfer" || exit 1
cp owner-maintenance/ownerctl.py owner-maintenance/package_format.py \
  tools/capture_owner_bootenv.py "$OWNER_PRIVATE/transfer/"
cp "$RUNTIME_SUMS" "$OWNER_PRIVATE/transfer/RESCUE_RUNTIME_SHA256SUMS"
cp "$INSTALL_PACKAGE" "$OWNER_PRIVATE/transfer/owner-install.tar.gz"
cp "$OWNER_PRIVATE/owner-package-public.pem" "$OWNER_PRIVATE/transfer/"
cp "$OWNER_PRIVATE/owner-client-ed25519.pub" "$OWNER_PRIVATE/transfer/owner-client.pub"
cp "$OWNER_PRIVATE/owner-service.json" "$OWNER_PRIVATE/transfer/"
(cd "$OWNER_PRIVATE/transfer" && sha256sum *) > "$OWNER_PRIVATE/TRANSFER_SHA256SUMS"
cat "$OWNER_PRIVATE/TRANSFER_SHA256SUMS"
ssh "$FORM3_PI_SSH" 'test ! -e "$HOME/form3-owner-input"' || exit 1
scp -pr "$OWNER_PRIVATE/transfer" "$FORM3_PI_SSH:form3-owner-input"
```

In RESCUE C receive **one file**, then send it from PI B. Repeat for each of the
eight filenames in the manifest; use the same filename in both terminals.
If a RAM filename already exists, preserve it and investigate instead of truncating.

```sh
# RESCUE — example 1 of 8; destination is RAM, no block-device path.
FILE=ownerctl.py
test ! -e "/run/$FILE" || exit 1
umask 077
timeout 60 nc -l -p 9001 > "/run/$FILE"
wc -c < "/run/$FILE"
sha256sum "/run/$FILE"
```

```sh
# PI — run only while the corresponding RESCUE receive is waiting.
FILE=ownerctl.py
wc -c < "$HOME/form3-owner-input/$FILE"
sha256sum "$HOME/form3-owner-input/$FILE"
nc -w 10 10.0.0.77 9001 < "$HOME/form3-owner-input/$FILE"
```

**Repeat with:** `package_format.py`, `capture_owner_bootenv.py`,
`RESCUE_RUNTIME_SHA256SUMS`, `owner-install.tar.gz`, `owner-package-public.pem`,
`owner-client.pub`, `owner-service.json`. **Every byte count/hash must match the
laptop manifest before execution.** A netcat timeout/closure is not proof of a
complete transfer. This raw listener is unauthenticated: only the isolated peer
may be connected. Check `/proc/meminfo`; do not stream a rootfs into RAM.

## 11. RESCUE — read-only mounts and the genuine runtime

Inspect `/proc/mounts` again. If either device is already mounted or vendor
processes are running, stop and inspect; do not mount over an existing tree.

```sh
# RESCUE — mount only the reviewed p6/p7, no journal replay.
test "$(blockdev --getro /dev/mmcblk0)" = 1 || exit 1
test "$(blockdev --getro /dev/mmcblk0p6)" = 1 || exit 1
test "$(blockdev --getro /dev/mmcblk0p7)" = 1 || exit 1
mkdir -p /mnt/owner-slot /mnt/owner-data
mount -t ext4 -o ro,noload,nodev,nosuid /dev/mmcblk0p6 /mnt/owner-slot || exit 1
mount -t ext4 -o ro,noload,nodev,nosuid,noexec /dev/mmcblk0p7 /mnt/owner-data || exit 1
cat /proc/mounts
cat /mnt/owner-slot/etc/formlabs/version.json
(cd /mnt/owner-slot && sha256sum -c /run/RESCUE_RUNTIME_SHA256SUMS) || exit 1
```

Expected p6 2.5.6-2773, exact sibling ext4 mounts, required runtime checksums
passing. p6 is deliberately executable for the **verified loader/Python/OpenSSL
only**; p7 stays noexec. The library symlinks must resolve inside the mounted p6.
A missing/different runtime is a stop, not permission to launch an unverified one.

```sh
# RESCUE — function affects this shell only; no global PATH, vendor site or init.
owner_python() {
  PYTHONHOME=/mnt/owner-slot/usr \
    /mnt/owner-slot/lib/ld-linux-armhf.so.3 \
    --library-path /mnt/owner-slot/lib:/mnt/owner-slot/usr/lib \
    /mnt/owner-slot/usr/bin/python3.5 -B -S "$@"
}
owner_python -c 'import sys,ssl; print(sys.version); print(ssl.OPENSSL_VERSION)'
owner_python /run/capture_owner_bootenv.py --output /run/owner-active-env-first.bin
owner_python /run/ownerctl.py preflight --context rescue \
  --slot-root /mnt/owner-slot --data-root /mnt/owner-data \
  --boot-env /run/owner-active-env-first.bin --output /run/owner-preflight-first.json
cat /run/owner-preflight-first.json
```

**Expected:** Python 3.5.3 / OpenSSL 1.0.2o, fresh environment CRC, selected slot6,
no flip, correct capacity/partition offsets and device fingerprint. A fresh
capture chooses the MTD device by validated name/geometry; do not hardcode mtd2.
Never run vendor init, Sauron or a vendor updater from this mounted runtime.

## 12. RESCUE — inspect journal flags and produce the read-only plan

This prints only filesystem header flags, not UUIDs or device secrets. The ext4
header is at byte1024; `s_state` is at0x3a and incompatibility flags at0x60.
[Kernel field definitions](https://docs.kernel.org/filesystems/ext4/super.html).
This is **not fsck**, a checksum validation or a whole-filesystem health proof.

```sh
# RESCUE — read-only header inspection; copy the result into the private receipt.
owner_python - <<'PY'
import os, stat, struct, json
def ext_state(raw):
    if len(raw) != 1024 or struct.unpack_from('<H', raw, 0x38)[0] != 0xef53:
        raise ValueError('Invalid/truncated ext4 superblock')
    state = struct.unpack_from('<H', raw, 0x3a)[0]
    incompat = struct.unpack_from('<I', raw, 0x60)[0]
    return {'state_flags': state, 'clean_flag': bool(state & 1),
            'errors_flag': bool(state & 2), 'orphan_recovery_flag': bool(state & 4),
            'needs_journal_recovery': bool(incompat & 4),
            'healthy_filesystem_proven': False}
for path in ('/dev/mmcblk0p6', '/dev/mmcblk0p7'):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISBLK(os.fstat(fd).st_mode): raise ValueError('Not block device')
        os.lseek(fd, 1024, os.SEEK_SET)
        result = ext_state(os.read(fd, 1024))
    finally:
        os.close(fd)
    print(json.dumps(dict(result, partition=path), sort_keys=True))
PY
```

Unexpected flags, errors, an orphan-recovery flag or mount/I/O errors require
case-specific investigation before any writable mount. A dirty journal means
the unreplayed file view and any plan from it are provisional. Do not use
`rw,noload`, automated `fsck -y`, or a repair of the original backup.

```sh
# RESCUE — type the independent public signer pin retained on LAPTOP.
OWNER_SIGNER_PIN='REPLACE_WITH_REVIEWED_64_HEX_PUBLIC_PEM_SHA256'
test "${#OWNER_SIGNER_PIN}" = 64 || exit 1
owner_python /run/ownerctl.py plan --context rescue \
  --slot-root /mnt/owner-slot --data-root /mnt/owner-data \
  --boot-env /run/owner-active-env-first.bin --package /run/owner-install.tar.gz \
  --public-key /run/owner-package-public.pem --signer-sha256 "$OWNER_SIGNER_PIN" \
  --owner-key /run/owner-client.pub --config /run/owner-service.json \
  --output /run/owner-plan-first.json
cat /run/owner-plan-first.json
```

The nonfunctional placeholder must be replaced; it is not a valid fingerprint.
Existing installation/pending transaction/account collision means stop and use
the matching lifecycle, not first-install again. Review `operation=install`,
device/slot/version, signer, package and authorized network. `plan_hash` is a
canonical JSON fingerprint, **not** `sha256sum` of the formatted plan file.

### Copy receipts and affected-file backups before a write

The initial path requires no owner tree at `/mnt/owner-data/owner-maintenance`.
Keep the full acquired images too. A small before-file tar supplements them:

```sh
# RESCUE — creates only a NEW private RAM archive; no shadow/key stores collected.
owner_python - <<'PY'
import os, tarfile
if os.path.lexists('/mnt/owner-data/owner-maintenance'):
    raise ValueError('Existing owner tree: review verify/update, not first install')
paths = ['etc/passwd', 'etc/group', 'etc/init.d/owner-maintenance',
         'etc/rc5.d/S98owner-maintenance', 'usr/local/sbin/ownerctl']
with tarfile.open('/run/owner-before.tar', 'x') as archive:
    for name in paths:
        source = '/mnt/owner-slot/' + name
        if os.path.lexists(source): archive.add(source, arcname='p6/' + name, recursive=False)
    for name in ('owner-preflight-first.json', 'owner-plan-first.json', 'owner-active-env-first.bin'):
        archive.add('/run/' + name, arcname=name, recursive=False)
PY
wc -c < /run/owner-before.tar
sha256sum /run/owner-before.tar
```

**PI B first**, then **RESCUE C sender**, then **LAPTOP retrieval**:

```sh
# PI — new private regular file, listener on isolated Ethernet only.
umask 077
(set -C; timeout 90 nc -4 -l 10.0.0.1 9002 > "$HOME/form3-root-qspi/owner-before.tar")
```

```sh
# RESCUE — RAM archive to the waiting PI, no raw storage destination.
nc -w 10 10.0.0.1 9002 < /run/owner-before.tar
```

```sh
# LAPTOP — compare size/hash with RESCUE; retain privately, never in Git.
scp -p "$FORM3_PI_SSH:form3-root-qspi/owner-before.tar" "$OWNER_PRIVATE/"
wc -c < "$OWNER_PRIVATE/owner-before.tar"
sha256sum "$OWNER_PRIVATE/owner-before.tar"
```

This same three-terminal pattern retrieves later receipts by using a new archive
basename in all three places. Hash/size equality is required each time.

## 13. RESCUE — separate writable-filesystem / recovery decision

This is the first authorized persistent **eMMC** write boundary. The printer must
still be in the identified rescue with no vendor stack. Backups must be valid and
the named real devices must match step11. Do not execute this against loop devices
or backup images. If recovery is required, first investigate a disposable derivative
and approve precisely the real-device recovery; this guide does not classify an
arbitrary damaged journal as recoverable.

For the approved clean-filesystem path, or a **separately approved normal journal
replay only**, use normal ext4 mounts without `noload`. The kernel may replay its
journal and writes mount metadata. That is a persistent operation even before
ownerctl changes a file. [Kernel mount semantics](https://www.kernel.org/doc/html/latest/admin-guide/ext4.html).

```sh
# RESCUE — PERSISTENT STORAGE GATE. Approval string is a human gate, not a health test.
printf 'Type APPROVE REAL P6 P7 WRITE only after backup/recovery review: '
read -r APPROVAL
test "$APPROVAL" = 'APPROVE REAL P6 P7 WRITE' || exit 1
cd /
umount /mnt/owner-data || exit 1
umount /mnt/owner-slot || exit 1
blockdev --setrw /dev/mmcblk0 || exit 1
blockdev --setrw /dev/mmcblk0p6 || exit 1
blockdev --setrw /dev/mmcblk0p7 || exit 1
for untouched in /dev/mmcblk0p1 /dev/mmcblk0p2 /dev/mmcblk0p5 /dev/mmcblk0boot0 /dev/mmcblk0boot1; do
    test "$(blockdev --getro "$untouched")" = 1 || exit 1
done
mount -t ext4 -o rw,nodev,nosuid /dev/mmcblk0p6 /mnt/owner-slot || exit 1
mount -t ext4 -o rw,nodev,nosuid,noexec /dev/mmcblk0p7 /mnt/owner-data || exit 1
cat /proc/mounts
dmesg
```

The parent user area's software RO flag must be cleared to write either partition.
This is **not** permission to write the parent device or p1/p2/p5; their individual
RO flags must remain `1`. Boot areas remain RO. A failed mount/I/O/error stops:
do not apply, force-unmount or run automatic repair. Restore deliberate protection
after safely closing any mounts; preserve diagnostics and the recovery equipment.

**If journal recovery occurred:** `sync`, unmount data then slot, remount both using
step11's `ro,noload` options, repeat runtime/header/preflight inspection and acquire
new before-files. If flags/errors remain unexplained, stop. Discard no old plan;
give the new plan/archive a distinct filename. Only after this review may the
same normal writable mounts above be used for installation.

## 14. RESCUE — fresh exact plan, install, verify and save rollback

After any approved recovery/remount, verify runtime hashes **again before execution**.
The same `owner_python` function still applies in this terminal. Generate a fresh
environment capture and final plan; no first-plan reuse after journal recovery.

```sh
# RESCUE — writable p6/p7 already reviewed; these commands still only plan/read.
(cd /mnt/owner-slot && sha256sum -c /run/RESCUE_RUNTIME_SHA256SUMS) || exit 1
owner_python /run/capture_owner_bootenv.py --output /run/owner-active-env-final.bin
owner_python /run/ownerctl.py plan --context rescue \
  --slot-root /mnt/owner-slot --data-root /mnt/owner-data \
  --boot-env /run/owner-active-env-final.bin --package /run/owner-install.tar.gz \
  --public-key /run/owner-package-public.pem --signer-sha256 "$OWNER_SIGNER_PIN" \
  --owner-key /run/owner-client.pub --config /run/owner-service.json \
  --output /run/owner-plan-final.json
cat /run/owner-plan-final.json
```

Copy the **final** plan and fresh before-files back to the laptop with step12's
pattern and a new archive name. Compare it to the package and target before apply.
The installer checks it again and refuses a stale baseline.

```sh
# RESCUE — exact owner file transaction, no service startup or reboot.
printf 'Reviewed final plan_hash: '
read -r PLAN_HASH
printf 'Reviewed final target.device_id: '
read -r DEVICE_ID
test "${#PLAN_HASH}" = 64 && test "${#DEVICE_ID}" = 64 || exit 1
owner_python /run/ownerctl.py install --context rescue \
  --slot-root /mnt/owner-slot --data-root /mnt/owner-data \
  --boot-env /run/owner-active-env-final.bin --package /run/owner-install.tar.gz \
  --public-key /run/owner-package-public.pem --owner-key /run/owner-client.pub \
  --plan /run/owner-plan-final.json --plan-hash "$PLAN_HASH" --device-id "$DEVICE_ID" \
  --apply --output /run/owner-install-result.json || exit 1
owner_python /run/ownerctl.py verify --context rescue \
  --slot-root /mnt/owner-slot --data-root /mnt/owner-data \
  --boot-env /run/owner-active-env-final.bin --output /run/owner-verify-result.json || exit 1
cat /run/owner-install-result.json
cat /run/owner-verify-result.json
test ! -e /mnt/owner-data/owner-maintenance/pending.json || exit 1
```

**Expected:** committed transaction, matching readback, current source version,
`started_services=false`. If interrupted, keep rescue running and inspect the
exact pending transaction; do not rerun first-install or restore the entire eMMC.

### What the installer writes exactly

The following is derived from `owner-maintenance/ownerctl.py::apply_install` and
`execute_transaction`; the package manifest lists the exact source bytes/hashes.

| Partition/path | Action and reason |
|---|---|
| p6 `/etc/passwd` | Append `owner-maint` non-login account, free UID/GID in64900–65000, `/bin/false`; preserve existing root entry |
| p6 `/etc/group` | Append matching group; no password/shadow modification |
| p6 `/etc/init.d/owner-maintenance` | New executable hash-pinned nonblocking supervisor hook |
| p6 `/etc/rc5.d/S98owner-maintenance` | New relative symlink to the hook; does not replace S99boot-ok |
| p6 `/usr/local/sbin/ownerctl` | New fixed wrapper invoking authored Python lifecycle code |
| p7 `/data/owner-maintenance/bootstrap/` | Authored bootstrap.py, socket_launcher.py, lan_ipv4.py, ownerctl.py, package_format.py, owner-maintenance.init |
| p7 `/data/owner-maintenance/releases/VERSION/` | `panel/` Python/static files, manifest.json and manifest.sig from signed package |
| p7 `/data/owner-maintenance/config/signing-public.pem` | Your pinned public signer, never private signing authority |
| p7 `/data/owner-maintenance/config/service.json` | Reviewed interface/client network/panel=false plus selected UID/GID/slot/firmware/signer |
| p7 `/data/owner-maintenance/ssh/authorized_keys` | Your validated client **public** key; no vendor key replacement |
| p7 `/data/owner-maintenance/current.json` | Active release/manifest pointer |
| p7 `/data/owner-maintenance/pending.json` | Write-ahead before/after transaction; removed only after committed verification |
| p7 `/data/owner-maintenance/transactions/PLAN_HASH.json` | Retained committed transaction and rollback data |
| p7 `/data/owner-maintenance/installed.json`, `.transaction-lock` | Installation state and scoped transaction serialization |

Parent directories and ext4 metadata are also created/changed. On **first normal
startup**, the supervisor separately creates its host key under `ssh/host_ed25519`,
owner state/identity directories as needed, `/run/owner-maintenance` runtime files
and narrowly scoped firewall rules. The host private key belongs to this printer.
It is not a vendor key, package signer or laptop login private key. Root's existing
account is reused by separate sshd; the non-login owner account is for the panel.

```sh
# RESCUE — private rollback archive in RAM; the bounded new installation only.
owner_python - <<'PY'
import tarfile, os
base = '/mnt/owner-data/owner-maintenance'
if os.path.exists(base + '/pending.json'): raise ValueError('Pending transaction')
with tarfile.open('/run/owner-after.tar', 'x') as archive:
    for name in ('transactions', 'installed.json', 'current.json', 'config'):
        archive.add(base + '/' + name, arcname='owner-maintenance/' + name)
    for name in ('owner-plan-final.json', 'owner-install-result.json', 'owner-verify-result.json'):
        archive.add('/run/' + name, arcname=name, recursive=False)
PY
wc -c < /run/owner-after.tar
sha256sum /run/owner-after.tar
```

Retrieve `owner-after.tar` using the exact PI-listener → RESCUE-sender → LAPTOP
pattern from step12, changing **every** `owner-before.tar` to `owner-after.tar`.
Compare byte count/hash and retain both archives independently before powering off.

### Close the installation cleanly

```sh
# RESCUE — after successful verify AND saved rollback; do not force unmount.
cd /
sync
umount /mnt/owner-data || exit 1
umount /mnt/owner-slot || exit 1
blockdev --setro /dev/mmcblk0p6 || exit 1
blockdev --setro /dev/mmcblk0p7 || exit 1
blockdev --setro /dev/mmcblk0 || exit 1
cat /proc/mounts
blockdev --getro /dev/mmcblk0
printf 'INSTALLATION CLOSED; independently review power-off before continuing.\n'
```

If rollback is required **before normal startup**, use the original installation
plan/device hash, the same validated runtime and approved writable p6/p7 mounts:

```sh
# RESCUE — CONDITIONAL ROLLBACK, not the next step on a successful installation.
: "${PLAN_HASH:?matching installation transaction hash}"
: "${DEVICE_ID:?matching device fingerprint}"
owner_python /run/ownerctl.py rollback --context rescue \
  --slot-root /mnt/owner-slot --data-root /mnt/owner-data \
  --boot-env /run/owner-active-env-final.bin --plan-hash "$PLAN_HASH" \
  --device-id "$DEVICE_ID" --apply --output /run/owner-rollback-result.json
```

The mounted runtime is unavailable after unmount: re-establish the reviewed mount
context before that conditional command. Rollback checks current against expected
bytes; it must refuse unrelated later edits. No blanket deletion or shadow restore.

## 15. PHYSICAL / PI — return once to this printer's own original QSPI

Prepare step16's independent network isolation **before the next normal boot**.
After closing rescue mounts and confirming no active printer action, issue `poweroff`
in RESCUE. Wait for halt and physically remove printer power; OS poweroff is not
electrical isolation. Re-enter the same approved clip/SOM/power arrangement.

On PI, use the retained original `read1.bin`, **not a downloaded factory image**.
The following is deliberately separate from the rescue write in step6.

```sh
# PI — HARDWARE RESTORE; re-enter reviewed part/programmer variables if the shell changed.
cd "$HOME/form3-root-qspi" || exit 1
: "${QSPI_PROGRAMMER:?reviewed programmer}"
: "${QSPI_CHIP:?identified part}"
read -r -p 'Original SHA256 independently retained on LAPTOP: ' FACTORY_SHA256
printf '%s  read1.bin\n' "$FACTORY_SHA256" | sha256sum -c - || exit 1
test "$(stat -c %s read1.bin)" = 4194304 || exit 1
test ! -e before-factory-return.bin && test ! -e factory-return-readback.bin || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" \
  -r before-factory-return.bin -o before-factory-return.log || exit 1
sudo chown "$(id -u):$(id -g)" before-factory-return.bin before-factory-return.log
sha256sum before-factory-return.bin
```

Compare the pre-read with the saved installed-rescue image/hash. Unexpected content
needs explanation before proceeding; don't mask it by overwriting first.

```sh
# PI — manual restore after original pin, pre-read, electrical and recovery review.
cmp before-factory-return.bin rescue-reviewed.bin || exit 1
read -r -p 'Type RESTORE MY VERIFIED FACTORY QSPI to continue: ' APPROVAL
test "$APPROVAL" = 'RESTORE MY VERIFIED FACTORY QSPI' || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" -w read1.bin -o factory-return-write.log || exit 1
sudo flashrom -p "$QSPI_PROGRAMMER" -c "$QSPI_CHIP" \
  -r factory-return-readback.bin -o factory-return-readback.log || exit 1
sudo chown "$(id -u):$(id -g)" factory-return-readback.bin factory-return-write.log factory-return-readback.log
cmp read1.bin factory-return-readback.bin || exit 1
printf '%s  factory-return-readback.bin\n' "$FACTORY_SHA256" | sha256sum -c - || exit 1
```

Save those receipts on LAPTOP. Remove all programmer wiring/power, reassemble and
check mechanically before printer power. **Why root survives:** normal vendor boot
loads the selected genuine rootfs; its added S98 hook starts the separate owner
sshd. No rescue boot environment is needed for ordinary owner SSH afterward.

## 16. PI — DHCP on the isolated cable for the first normal boot

Normal ConnMan needs a lease; it does not inherit rescue's static address. This
example keeps Pi eth0 at10.0.0.1/24, matching the initial owner client allowlist.
Printer WLAN must be independently prevented from joining an upstream network;
include other Ethernet, USB, IPv6, bridges, routing and host relays in that check.
If this cannot be established, **do not use first-use host trust on that setup**.

The Pi WLAN management path may remain only with forwarding/bridging disabled
and independently verified. No router change or printer Wi-Fi secret is required
by these commands. Check that management routes do not overlap10.0.0.0/24.
Retain the printer eth0 MAC privately from the already identified rescue's
`cat /sys/class/net/eth0/address` **before shutting rescue down**; do not publish it.

```sh
# PI — create a NEW local configuration; no daemon starts yet.
read -r -p 'Previously verified printer eth0 MAC: ' PRINTER_ETH0_MAC
[[ "$PRINTER_ETH0_MAC" =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]] || exit 1
umask 077
test ! -e "$HOME/form3-root-qspi/owner-dhcp.conf" || exit 1
cat > "$HOME/form3-root-qspi/owner-dhcp.conf" <<EOF
port=0
interface=eth0
except-interface=lo
bind-interfaces
no-hosts
no-resolv
dhcp-range=10.0.0.80,10.0.0.90,255.255.255.0,1h
dhcp-host=$PRINTER_ETH0_MAC,set:owner
dhcp-ignore=tag:!owner
dhcp-option=option:router
dhcp-option=option:dns-server
dhcp-leasefile=/run/form3-owner-dhcp/leases
log-facility=-
user=nobody
group=nogroup
EOF
sudo dnsmasq --test --conf-file="$HOME/form3-root-qspi/owner-dhcp.conf"
sudo ss -lunp
```

Expected syntaxOK and no competing DHCP process on eth0/UDP67. `port=0` disables
DNS, the empty router/DNS options advertise neither, no TFTP/RA/NAT is configured.
Only the retained MAC is served; MAC matching is not cryptographic authentication.
[Upstream dnsmasq options](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html).
The config's syntax can be tested offline; actual lease/isolation acceptance is
physical work. Do not stop an unrelated DHCP service just to free its port.

```sh
# PI — TEMPORARY LIVE DHCP, only after isolation/port review; foreground, at most 1 hour.
sudo install -d -m 700 -o nobody -g nogroup /run/form3-owner-dhcp
sudo timeout --signal=TERM 3600 dnsmasq --keep-in-foreground \
  --conf-file="$HOME/form3-root-qspi/owner-dhcp.conf" --pid-file=
```

Leave this terminal running, then power on the assembled printer. In another PI
terminal read `sudo cat /run/form3-owner-dhcp/leases`; use the actual matching lease,
not the old rescue address. A normal boot writes vendor logs/state. Do not start
a print merely to test login. Ctrl-C stops this dedicated foreground DHCP; lease
renewal will need it or an explicitly reviewed replacement network later.

## 17. LAPTOP — acquire the normal owner SSH host key through the Pi

```sh
# LAPTOP — actual isolated lease; validate before embedding it in a remote command.
read -r -p 'Verified isolated normal-printer IPv4 from the Pi lease: ' PRINTER_HOST
export PRINTER_HOST
python3 - <<'PY'
import os, ipaddress
a = ipaddress.IPv4Address(os.environ['PRINTER_HOST'])
if a not in ipaddress.IPv4Network('10.0.0.0/24') or a in (
        ipaddress.IPv4Address('10.0.0.0'), ipaddress.IPv4Address('10.0.0.1'),
        ipaddress.IPv4Address('10.0.0.255')):
    raise SystemExit('STOP: not the expected isolated peer address')
PY
test "$?" = 0 || exit 1
OWNER_PIN_CANDIDATE="$OWNER_PRIVATE/host-key-candidate.txt"
(umask 077; set -C; ssh -o StrictHostKeyChecking=yes "$FORM3_PI_SSH" \
  "ssh-keyscan -T 5 -p 2222 -t ed25519 '$PRINTER_HOST'" > "$OWNER_PIN_CANDIDATE")
ssh-keygen -lf "$OWNER_PIN_CANDIDATE" -E sha256
```

The raw host key is obtained on the independently isolated cable. `ssh-keyscan`
does not authenticate it by itself. Require exactly one Ed25519 record and the
same physically identified printer. For an already enrolled installation, require
the existing fingerprint instead of performing new TOFU. No scan of the home LAN.

## 18. LAPTOP — create the strict profile, then log in

```sh
# LAPTOP — local profile creation only; never overwrites known-hosts/default keys.
read -r -p 'Independently accepted SHA256:... owner host fingerprint: ' OWNER_HOST_FINGERPRINT
OWNER_KEY="$OWNER_PRIVATE/owner-client-ed25519"
python3 tools/create_owner_ssh_profile.py \
  --directory "$OWNER_PRIVATE" --host "$PRINTER_HOST" --key "$OWNER_KEY" \
  --candidate "$OWNER_PIN_CANDIDATE" --expected-host-fingerprint "$OWNER_HOST_FINGERPRINT" \
  --jump-alias "$FORM3_PI_SSH" || exit 1
export OWNER_SSH_PROFILE="$OWNER_PRIVATE/owner-ssh.conf"
ssh -G -F "$OWNER_SSH_PROFILE" form3-owner
ssh -F "$OWNER_SSH_PROFILE" form3-owner
```

The helper validates the public-key encoding/fingerprint and creates only
`owner-known-hosts` and `owner-ssh.conf`, mode0600. The profile selects root:2222,
your named key, strict stable host-key alias, no passwords/agent forwarding and
the independently pinned Pi jump. It does not connect or configure the printer.

Inside the resulting **NORMAL PRINTER** session:

```sh
# NORMAL PRINTER — identity and installed-file verification, no printing commands.
id
uname -a
cat /proc/cmdline
cat /etc/formlabs/version.json
/usr/local/sbin/ownerctl verify --context normal --slot-root / --data-root /data
/usr/bin/ssh-keygen -lf /data/owner-maintenance/ssh/host_ed25519.pub -E sha256
```

**Expected:** UID0, genuine4.9.65+, `root=/dev/mmcblk0p6`, no `rdinit=/init`,
firmware2.5.6-2773, valid installation and the retained host fingerprint. This is
normal root access. Open a second pinned SSH session and keep both functioning.
It is not proof the printer's original mechanical/printing fault was repaired.

## 19. LAPTOP — complete acceptance and make daily use simple

Perform the [wrong-key rejection and RAM-only SFTP roundtrip](SECURE_SSH.md#6-acceptance-reject-wrong-credentials-and-test-sftp)
before declaring installation complete. For the Pi topology, the wrong-key test
must also include the same reviewed ProxyCommand; otherwise a connection failure
only tests routing, not authentication. No unknown/wrong host pin may be accepted.

```sh
# LAPTOP — one wrong-key attempt, same pinned host and Pi route, no correct agent key.
REJECTION_DIR=$(mktemp -d "$OWNER_PRIVATE/ssh-rejection.XXXXXX")
ssh-keygen -q -t ed25519 -N '' -f "$REJECTION_DIR/wrong-key"
ssh -F /dev/null -p 2222 -i "$REJECTION_DIR/wrong-key" \
  -o BatchMode=yes -o IdentityAgent=none -o IdentitiesOnly=yes \
  -o HostKeyAlias=form3-owner -o HostKeyAlgorithms=ssh-ed25519 \
  -o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null \
  -o UserKnownHostsFile="$OWNER_PRIVATE/owner-known-hosts" \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o ConnectTimeout=8 \
  -o "ProxyCommand=/usr/bin/ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ForwardAgent=no -W %h:%p $FORM3_PI_SSH" \
  "root@$PRINTER_HOST" true
```

Expected **authentication rejection**, `Permission denied (publickey)`, while the
ordinary profile still logs in. This deliberately failing command must not be
placed in a success-only `set -e` script. Timeout, refused port or wrong host pin
is **not** the intended result. Never enroll the wrong key on the printer.

```sh
# LAPTOP — harmless SFTP test, new laptop directory and printer RAM directory only.
ROUNDTRIP=$(mktemp -d "$OWNER_PRIVATE/sftp-roundtrip.XXXXXX")
printf 'OWNER SFTP ROUNDTRIP\n' > "$ROUNDTRIP/sent.txt"
REMOTE_TEST=$(ssh -F "$OWNER_SSH_PROFILE" form3-owner 'umask 077; mktemp -d /run/owner-sftp.XXXXXX')
[[ "$REMOTE_TEST" =~ ^/run/owner-sftp\.[A-Za-z0-9]{6}$ ]] || exit 1
sftp -F "$OWNER_SSH_PROFILE" -b - form3-owner <<EOF
put "$ROUNDTRIP/sent.txt" "$REMOTE_TEST/probe.txt"
get "$REMOTE_TEST/probe.txt" "$ROUNDTRIP/received.txt"
EOF
test "$?" = 0 || exit 1
cmp "$ROUNDTRIP/sent.txt" "$ROUNDTRIP/received.txt" || exit 1
sha256sum "$ROUNDTRIP/sent.txt" "$ROUNDTRIP/received.txt"
```

Expected identical hashes and bytes. `sftp -b` is noninteractive: unlock the named
client key into your laptop SSH agent first if it has a passphrase. The following
agent commands can be run before this test. The tiny RAM test directory may remain
until normal shutdown; no broad `rm` or eMMC cleanup is necessary.

```sh
# LAPTOP — ordinary daily use, after acceptance; passphrase stays local.
eval "$(ssh-agent -s)"
ssh-add -t 8h "$OWNER_PRIVATE/owner-client-ed25519"
ssh -F "$OWNER_SSH_PROFILE" form3-owner
sftp -F "$OWNER_SSH_PROFILE" form3-owner
```

This gives root without repeatedly entering an account password, using your own
key. Do not unlock root with an empty network password. SSH and SFTP use the same
pin and identity. Keep signing keys, complete rollback receipts and acquisition
backups outside Git. Never share them as a ready-made identity for another printer.

For a later approved direct WLAN path, retain the wired recovery route, use the
reviewed signed maintenance transaction, verify actual current addressing and
the **same host key**, then create a new direct profile without `--jump-alias` in
a separate private directory. Do not just move service.json or expose ports at
the router. Panel TLS enrollment, current-IP certificate handling, updates and
uninstall are in [OWNER_INSTALL](OWNER_INSTALL.md); native clock/logo changes are
separate [optional transactions](NATIVE_DISPLAY.md).

## Command review and proof limits

Shell blocks are parsed in offline tests; local profile generation, fingerprint
rejection, ext4-field interpretation and DHCP config syntax have synthetic tests.
They **do not execute** flashrom, mount, blockdev, poweroff, SSH connections or DHCP
listeners. The underlying owner installer has separate transaction/rollback tests
and historical hardware observations. Current source tests do not turn unresolved
electrical measurements, another factory hash or a dirty filesystem into approved
hardware steps. Those stop conditions are part of a reproducible procedure.
