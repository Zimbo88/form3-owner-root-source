# Owner Root maintenance panel — 0.5.13-review

An unprivileged panel on **port1328**, with five main navigation areas and related
settings tabs. [Features and limits](../docs/public/LIMITS.md) are the current user-facing
catalog. [Acceptance](../docs/public/LIMITS.md) distinguishes reference-owner
hardware observations, current source/fixture tests and pending installation.

## Runtime and security

Target code deliberately uses Python3.5 standard-library-compatible constructs.
Existing genuine ARM Python3.5.3/glibc2.26/OpenSSL1.0.2o and normal-device results
are documented separately from host/VM fixtures. They do not imply that old
libraries are maintained or that another Linux kernel/firmware is compatible.
No runtime dependency was added for the original SVG logo or transparent sidebar.

Requests, workers, exports, sessions, retries and history are bounded. Host/Origin
checks and CSRF apply to typed mutations. Session idle/absolute expiry, logout
revocation, rate limits, HttpOnly/SameSite cookies and Secure under HTTPS remain.
No access secret in URLs, logs or client persistent storage. Private full-log
export needs explicit confirmation and secret reauthentication even when ordinary
WLAN login is optional. See the executable limits in `server.py`, not inferred
limits from a screenshot.

Primary HTTPS is inherited from the checked launcher. Explicitly configured LAN
HTTP binds the current eligible physical IPv4 address, validates its private
connected subnet and rebinds on change. No wildcard/IPv6/vendor-VPN listener,
UPnP or public relay. The primary socket's validation is preserved. Optional WLAN
login defaults off as an explicitly selected reference configuration; that does not weaken
SSH/HTTPS or make HTTP encrypted. [WLAN design](../docs/public/OWNER_INSTALL.md).

## Data and writes

The Linux provider reads allowlisted proc/sysfs/version/storage sources. CPU
activity is based on bounded samples, GPU activity remains unavailable. Every
field carries a source/state; stale observations cannot remain LIVE. Historical
bundle data uses reviewed parsers for consumables, logs, thermal records and job
metadata. Secret values **and secret map keys** are excluded.

Version 0.5.9 adds an optional **Recorded print attempt** view in Diagnostics:
heater current/setpoint, fan RPM, peripheral temperatures, reported fault fields
and a categorized timeline from a verified saved capture. The source, unit, sample
count and historical timestamps remain visible. Follow [offline log review](../docs/public/LOG_REVIEW.md)
to build a private bundle. Missing evidence stays unavailable; task completion is
not a successful-print or safe-idle verdict. This source change is not installed
on the printer by running the analysis or tests.

Owner preference/alias/refresh and refill ledger writes use bounded typed input
and atomic private state. A display alias does not configure DNS. A refill entry
is not a native counter reset. Privacy selection is a preference/preview, never
an applied green claim. The power endpoint rejects requests; buttons remain
disabled without an authoritative safe-idle predicate. No arbitrary path, shell,
D-Bus or actuator proxy exists.

## Try it locally

From the clone root follow [setup](../docs/public/BUILD.md). The default
browser fixture is disconnected, unprivileged and synthetic:

```sh
# LAPTOP — local DEMO server/browser in a disconnected namespace, no printer.
python3 tools/test_panel_browser.py \
  --private-output research-private/browser-review \
  --report build/browser-review.json
```

Use new output paths. Expected: DEMO screenshot, navigation/preferences/login/
logout success, no mobile overflow. Missing sandbox/browser support fails;
do not remove isolation. A DEMO frame is not proof of a physical sensor reading.

For interactive development, `server.py --help` describes explicit loopback
`--dev-http`, precreated private owner state and secret-file inputs. `--live-host`
reads the computer running the command, not a remotely discovered printer.
Do not expose a development fixture on a real LAN.

## Package, update and recovery

The [signed builder](../tools/build_owner_package.py) creates a `kind=panel`
package; source ZIPs and synthetic packages are not production authority.
Use [the lifecycle tools](../owner-maintenance/README.md) for exact plan/apply/
verify/rollback. This package cannot modify bootstrap, SSH, native display, QSPI,
calibration or firmware. Keep independent SSH available if the panel fails.
The [original artwork](native/signature-mark.svg) is shared by panel/boot/project,
with native rendering and writes separately reviewed.

## Explicit Clear usage adjustment

[The panel workflow and recovery boundary](../docs/public/CARTRIDGE_PANEL_RESET.md) use a separate root UNIX-socket broker. This requires a signed maintenance update, not only a panel archive. The ordinary panel remains unprivileged. Only the reviewed legacy Clear format is supported; already-zero usage is not rewritten.
