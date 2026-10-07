# Contributing

Start at [setup](docs/public/BUILD.md). Use one branch and one canonical source
copy; keep original acquisitions and other worktrees untouched. Before a change,
record source/version and the narrow question it answers. Preserve an existing test
receipt as historical rather than rewriting it to imply new acceptance.

Use English documentation and explicit FILE/CODE, OFFLINE TEST, EMULATION,
OWNER HARDWARE OBSERVATION, INFERENCE or UNKNOWN labels. Static binary claims need
path, hash/build ID and address convention/function. Strings are leads, not proof
of side effects, availability or transmission. Report conflicting evidence.

Add meaningful malformed-input, redaction, resource, stale-state or transaction
regression cases when behavior changes. Use synthetic fixtures; never checked-in
private keys, device logs or proprietary binaries. Keep Python 3.5 target modules
compatible while host analysis tools may use modern Python. Test those separately.

Never add an actuator write or generic privileged proxy to make a dashboard look
complete. A disabled control should explain the missing backend/approval/safety gate.
Never infer update-hook survival merely from files persisting on p7. Review current
links, figures, secret scans and the complete staged diff before a push.

## Documentation voice

Write permanent documentation in English. Use first person only for the actual
author’s personal motivation or observations.
Use impersonal technical prose for instructions, measurements and automated test
results; do not attribute your observations to the maintainer. Avoid third-person
maintainer narration. Copyright and attribution lines
retain full names. Do not turn a fixture, inference or agent-run test into an
assertion of personal hardware observation. Preserve third-party quotations and credits.

## Checks and reports

Run [public source checks](docs/public/BUILD.md#public-source-checks) for every
change. Runtime changes also need the separately documented isolated fixture suite;
hardware acceptance is never implied by either. Keep historical versions/receipts
unchanged and add new observations with their own scope. The PR template requests
exact commands and NOT RUN dependencies. For sensitive reports, follow
[SECURITY](SECURITY.md); never attach raw device evidence to an issue.

Distribution uses individually reviewed [allowlist entries](publication/allowlist.json).
Changes to source hashes require the [clean-commit export process](docs/maintainer/RELEASE_CHECKLIST.md#source-changes-and-generated-metadata).
Do not edit old acceptance results to make a new source checkout appear tested.
