# Contributing to the private developer tree

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
private keys, device logs or proprietary binaries. Keep Python3.5 target modules
compatible while host analysis tools may use modern Python. Test those separately.

Never add an actuator write or generic privileged proxy to make a dashboard look
complete. A disabled control should explain the missing backend/approval/safety gate.
Never infer update-hook survival merely from files persisting on p7. Review current
links, figures, secret scans and the complete staged diff before a private push.

## Documentation voice

Write permanent documentation in English. Use my first-person voice for project
motivation and personally confirmed observations, or an impersonal technical voice
for instructions, measurements and automated test results. Do not refer to me as
“Mathias”, “he” or “the owner” in narrative prose. Copyright and attribution lines
retain full names. Do not turn a fixture, inference or agent-run test into an
assertion that I personally observed it. Preserve third-party quotations and credits.
