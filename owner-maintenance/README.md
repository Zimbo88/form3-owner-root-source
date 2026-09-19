# Owner maintenance lifecycle — 0.5.9-review source

Current executable source supports the inspected **p6 / 2.5.6-2773** target. Prior
reference-owner hardware acceptance includes normal SSH/SFTP, panel and reboot
return. The [current release receipt](../docs/public/LIMITS.md) separates
new source changes from actual deployment. Start with [readiness](../docs/public/LIMITS.md)
and [first install](../docs/public/OWNER_INSTALL.md), not an old milestone's version.

## Authority and operations

`ownerctl.py` implements preflight, install plan/apply, verify, panel update,
maintenance update, panel enrollment/renewal, rollback and uninstall. Mutations
require explicit apply, exact reviewed plan hash and device fingerprint. The normal
panel update cannot replace root bootstrap or SSH files; a maintenance package
has a separate plan. Initial account/hook installation and complete removal use
reviewed rescue context. Fixture mode requires disposable markers.

No operation mounts a filesystem, clears block read-only flags, flashes QSPI,
writes a raw block device, edits root shadow, starts vendor init or controls an
actuator. The [logical patch map](../docs/public/OWNER_INSTALL.md) distinguishes p6/p7
file changes from journal/metadata effects.

`package_format.py` requires RSA2048–4096/SHA256 and an independently pinned public
PEM before accepting archive contents. Duplicate/unapproved paths, links, devices,
sparse/PAX entries, oversized expansion and trailing data fail. A package-provided
key is not independent authority. Build inputs and signing authority are separate;
test keys are never installation keys. The reference installation's production keys exist
privately; every new owner must enroll their own, preserving vendor identity.

## Runtime and independence

The root SysV hook returns without waiting for networking, keeping S99boot-ok and
vendor startup independent. The supervisor validates owner files/configuration,
manages only owner listeners/rules and uses bounded retries. Separate owner sshd
uses the existing vendor7.5p1 executable with owner host/client-key authorization,
no password login and internal-SFTP. No manufacturer CA or host key is reused.

The primary socket launcher verifies/binds eligible physical IPv4, drops groups,
UID and GID, then executes the panel. Separately configured owner LAN HTTP and SSH
can work without a primary Ethernet address; the primary HTTPS socket validation
is not weakened. DHCP/interface state is rechecked. See [WLAN scope](../docs/public/OWNER_INSTALL.md)
for transport, subnet, optional-login and recovery behavior. No generic privileged
web helper, IPv6 listener, router change, vendor-service stop or assumed mDNS.

An invalid primary certificate still fails closed. TLS enrollment/renewal requires
real current-address/approved-name trust; no browser verification bypass. A failed
panel remains distinct from SSH availability and printer health.

## Transactions and rollback

Changes use fsync, atomic per-file replacement and a private write-ahead record;
the complete filesystem transaction is **not** one atomic operation. Pending state
is significant, not a reason to repeat install. Verify current files against the
plan and preserve all before/after data before proceeding. Rollback refuses
unrelated later edits. Account/TLS/identity backups can be sensitive and remain
private. Owner host keys and user-created state are retained under documented
removal behavior; no other slot or vendor identity is rewritten.

```sh
# LAPTOP — source help only; no device access, mount or install.
python3 tools/build_owner_package.py --help
python3 owner-maintenance/ownerctl.py --help
```

Expected: explicit contexts/arguments and apply gates. The [one test path](../docs/public/BUILD.md)
runs disconnected synthetic corruption, authentication, permission and interruption
cases. Actual ARM and earlier VM results have narrower, separate scopes. Target
Python3.5/OpenSSL compatibility does not mean those old libraries are maintained.

For a future live update preserve an independent pinned SSH session, current
package/config/identity pins, exact plan and rollback copy. Reject unsupported
firmware, pending owner operations, release collisions or retention limits.
[Recovery](../docs/public/OWNER_INSTALL.md) describes failures; routine panel work needs
no QSPI return or full-printer reboot.
