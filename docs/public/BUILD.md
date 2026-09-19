# Build and test without a printer

This is the single setup path for the selected source release. Work on a laptop,
not in Rescue or the normal printer OS. The host tools require Python **3.12+**;
target modules remain Python **3.5** compatible. Python syntax checks and host
fixtures are distinct from execution using the genuine ARM runtime/kernel.

## Dependencies

On a suitable Ubuntu host, review the package transaction first. The fixture suite
uses the system Python inside its sandbox; installing only into a virtualenv does
not supply its dependencies. Package versions are recorded with your test receipt.

```sh
# LAPTOP — optional host setup only; never execute on the printer.
sudo apt-get install python3 python3-cryptography python3-msgpack python3-pil \
  python3-capstone bubblewrap util-linux iproute2 openssl openssh-client dnsmasq-base libsodium23 git nodejs tzdata
python3 --version
openssl version
```

The test runner needs existing noninteractive permission to create a **new network
namespace** using `sudo -n unshare --net`. It sets only synthetic namespace-local
addresses, drops back to the invoking UID and runs bubblewrap with read-only source,
RAM temporary storage and no home/credentials or external network. No host route or
firewall is changed. If these isolation facilities are unavailable, stop and record
that the isolated tests did not run. Do not remove isolation or change sudoers merely
to obtain a green result. A disposable development VM is an alternative host.

```sh
# LAPTOP — clone root, new output path on each run.
python3 tools/developer_check.py --output build/developer-check-01.json
```

Expected: `passed: true`, actual test count and zero errors/failures, plus explicit
scope exclusions. The adjacent test log binds source hashes. This export contains
its selected fixture modules; it does not silently claim the larger private research
suite. `test_rescue.py` depends on acquired binary inputs and is excluded by the
fixture runner, not counted as passed. Missing imports or malformed fixtures fail.
A separate evidence run needs the supplied, authenticated reference evidence and
built BusyBox. See `tools/run_offline_tests.py --help`; do not fetch a vendor rootfs
to make the ordinary fixtures pass.

The optional `tools/test_panel_browser.py` fixture additionally expects Ubuntu's
installed Firefox snap at `/snap/firefox/current/usr/lib/firefox/firefox` and
working unprivileged user/network namespaces. It launches its own disposable
profile with loopback only, never the personal browser profile. A missing browser
or namespace is unavailable coverage, not a reason to weaken the sandbox. See the
[panel README](../../owner-ui/README.md) for its explicit invocation.

## Source structure and runtime boundaries

| Path | Purpose |
|---|---|
| `owner-ui/server.py`, `panel_data.py`, `formule_codec.py` | Unprivileged server, allowlisted read adapters, bounded offline protocol parser |
| `owner-ui/static/` | Local HTML/CSS/JavaScript; no CDN/analytics |
| `owner-maintenance/ownerctl.py`, `package_format.py` | Independent signer pins, target checks and transactional install/update/rollback |
| `owner-maintenance/bootstrap.py`, `socket_launcher.py`, `lan_ipv4.py` | SysV service supervision, privilege drop and current-interface IPv4 handling |
| `rescue/` | Pinned BusyBox configuration/source patch and RAM init scripts |
| `tools/` | Host builders, validators, bounded local exporters and review tools |
| `tests/` | Synthetic, namespace-isolated fixtures; optional explicitly supplied evidence |
| `checksums/` | Runtime path/size/hash metadata only; no runtime binaries |
| `publication/allowlist.json` | Explicit reviewed files, exact hashes, rights category and provenance |

Target constraints: reference ARMv7/armhf, Linux 4.9.65+, Python 3.5.3, glibc 2.26,
OpenSSL 1.0.2o and vendor OpenSSH 7.5p1. Do not upgrade those libraries in place.
Old dependencies are compatibility constraints, not a current security endorsement.
Owner SSH stays independent of a panel crash. Do not expose these services to the
Internet; use an independently authenticated owner VPN for remote access.

## Native display and rescue prerequisites

Rescue compilation additionally needs GNU make/GCC host tools, patch, curl, file,
readelf/binutils and qemu-user. `rescue/sources.lock.json` pins BusyBox 1.37.0 and
Bootlin's ARMv7 musl toolchain, checksums and upstream download locations. No binary
is supplied. Cache the exact two archives under `.cache/downloads/` or explicitly
allow this host builder to download those public pinned inputs. `--offline` forbids
downloads. A build still requires the authenticated reference factory input first.

Optional authored offscreen logo/clock rendering needs host Qt5/PyQt5, QtSvg and
QtQuick software rendering (`python3-pyqt5`, `python3-pyqt5.qtsvg`,
`python3-pyqt5.qtquick`, `qml-module-qtquick2`, `qml-module-qtquick-window2`,
`qml-module-qtquick-controls`). Keep bubblewrap isolation. The RCC is parsed as data;
no full vendor UI, installer or daemon is started by the build procedure.
See [native display](NATIVE_DISPLAY.md) for exact inputs and outputs.

## Review packages are not installation authority

Commit reviewed source, update individual changed entries in the allowlist after
content/rights review, and use a new output directory:

```sh
# LAPTOP — clean committed clone only; no public upload or hardware action.
python3 tools/export_public_source.py --output build/source-review-01
cd build/source-review-01
sha256sum -c SHA256SUMS
cd source
sha256sum -c SOURCE_SHA256SUMS
python3 tools/developer_check.py --output build/exported-fixtures-01.json
```

The exporter selects exact Git blobs and fails on changed pins, uncommitted work,
missing entries, symlinks, path collisions, secrets, prohibited formats or size
limits. It never includes `.git`, unlisted files or ignored research. The normalized
allowlist travels with the export so another developer can review and rebuild it.
`PUBLICATION.json` records the producer commit and provenance; generated checksums
exclude their own checksum file. `tools/package_developer_source.py` is a compatibility
entry to this same exporter, not a second bulk packager.

The tarball is **unsigned source review only**. Create a separate installation package
with your own independent signer only after review, as described in
[installation](OWNER_INSTALL.md). Do not deploy synthetic fixture keys. Preserve the
review package, source commit, tool versions and test receipts privately.
