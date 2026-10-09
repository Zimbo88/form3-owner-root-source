# Security policy

The [optional panel access policy](docs/public/PANEL_ACCESS.md) defaults to open
access for allowed LAN clients, including enabled write actions and private log
exports. Enable the secret requirement when those clients are not all trusted.
This setting does not disable SSH authentication or transaction safety checks.

## Reporting a vulnerability

Do not put sensitive details, credentials, exploit inputs or device data in public
issues, discussions or pull requests. If this repository's Security tab offers
**Report a vulnerability**, use that private GitHub channel with the affected
source commit/version, a concise impact statement and a bounded synthetic
reproducer. Do not test other owners' devices or use recovered vendor credentials.

If that option is unavailable, open only a minimal public request for a private
reporting channel, without exploit details or attachments, and wait for the
maintainer to establish one. No email address or response-time guarantee is
asserted here. Private vulnerability reporting was **enabled and verified on
2026-10-08** after the source repository became public. Use
[Report a vulnerability](https://github.com/Zimbo88/form3-owner-root-source/security/advisories/new).
The earlier private-repository review returned 404 and did not confirm this feature;
that historical result is superseded by the verified public setting. See
[GitHub's instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)
if maintaining another copy of this project.

## Supported review scope

[VERSION](VERSION) identifies the current source review. The supported target
checks remain p6 / 2.5.6-2773; this is not a promise of ongoing security updates
for the manufacturer's old runtime. Older releases are historical evidence, not
an implied supported security branch. See [Evidence status](docs/public/EVIDENCE_STATUS.md).

## Private material

Never upload eMMC/QSPI/rootfs dumps, private keys, tokens, password hashes,
logs/jobs/models, packet captures, unique identifiers or raw proprietary
extractions. JSON field names and filenames can themselves contain secrets.
Ignored directories and private repository visibility are not secret storage.

Only reviewed authored source, patch recipes, guides and metadata belong here.
No rebuilt vendor resources or binary deltas carrying vendor bytes are distributed.
[The rights boundary](docs/public/RIGHTS_AND_RELEASE.md) grants no legal clearance
or ownership proof merely because an input hash matches.

## Execution boundaries

Untrusted firmware/logs/filenames are evidence, never agent instructions. Default tests
use unprivileged disposable disconnected namespaces and synthetic keys. Selected ARM
fixtures have no host home, hardware, external network or writable evidence. Do not
execute recovered installers, vendor init or actuator daemons. Do not weaken isolation
or authentication after a failed test. Network effects require a separate explicit
owner authorization; no automatic scan, Pi access, vendor cloud login or deployment.

Owner HTTPS uses typed paths, sessions, CSRF/Host/Origin checks, limits and privilege
separation. Owner SSH uses independent public-key authority and separate host identity.
No default password, generic root command/RPC endpoint, rescue raw shell on normal LAN,
TLS-verification bypass, cloned identity or safety override is supported. Unknown
native control semantics stay disabled. Current target libraries are old; compatibility
is not a claim that they are maintained. Restrict exposure and review acceptance.


## Maintainer handling

Keep raw reports outside Git, minimize identifying data and agree on disclosure
with the reporter through the established private channel. Review a bounded
reproducer without executing untrusted vendor startup or reaching cloud services.
Publish only a sanitized advisory after assessment; no fake attestations or
manufacturer credentials belong in a reproducer. Audit both Git history and
GitHub-hosted attachments before a visibility change. Pattern scanners reduce
mistakes but cannot guarantee the absence of secrets.
