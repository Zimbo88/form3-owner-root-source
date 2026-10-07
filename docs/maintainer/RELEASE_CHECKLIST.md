# Preparing the source edition for a public repository

The project started as private repair research. The source edition deliberately
leaves out private evidence and material whose redistribution is not established.
That history is explained in the README without claiming that an exclusion list
amounts to legal clearance. Publication remains a separate maintainer decision.

## Which repository can be reviewed for a visibility change?

Use a **new repository containing only the reviewed source export and its clean
history**. Keep the older private research repository private. Removing a file from
the latest commit does not remove earlier copies, branches or tags. A source-only
branch in the old repository is therefore insufficient.

`publication/allowlist.json` selects and pins each source file. The export contains
the panel, rescue/installation sources, tutorials, authored diagrams, the reviewed
owner closeup, notices, tests and compatibility checksums. It excludes raw firmware,
rootfs, decrypted archives, private keys, logs, job models, deployment records and
raw decompilation. Original evidence and private history stay preserved locally.

The export is an **unsigned source review**, not a production installer. Owners
acquire compatible device inputs and generate their own keys. Some chip/profile
engineering gates remain; do not imply that publication makes them disappear.

## Review before making it public

1. Confirm the intended repository identity and that it is still PRIVATE. Confirm
   it is not a fork and has no inherited private research history; audit every extra branch and tag.
2. Inspect **every reachable commit and asset**, not just `git status` or HEAD.
   Check the allowlist, licenses, authorship and small transformation contexts.
   The included photo is credited to Mathias Zimmermann; the manufacturer's
   datasheet and third-party articles are linked, not bundled.
3. Build/test a fresh clone with [BUILD](../public/BUILD.md). No firmware archive is needed
   for the disconnected fixtures. Record counts, exclusions, source commit and
   package checksum. Do not mark unperformed hardware checks as passed.
   Activate the prepared CI workflow using an appropriately authorized credential
   and verify its hosted run; see [pending activation](../public/BUILD.md#hosted-ci-activation-pending).
4. Inspect repository data outside Git: releases/assets, issues, pull requests,
   discussions, wiki, Actions logs/artifacts, Pages, integrations and attachments.
   Exported source checks cannot inspect those on a future maintainer's behalf.
5. Read [rights and provenance](../public/RIGHTS_AND_RELEASE.md). Resolve any outstanding
   rights question that affects the intended publication. A notice cannot grant
   rights to third-party code or erase leaked information.
6. Make the visibility change **manually**, only for the reviewed source edition,
   using GitHub's Settings → General → Danger Zone → Change repository visibility.
   Re-read the exact owner/repository name before confirming. This document and
   the build/export tools do not issue a visibility-changing command.
7. Verify the public landing page, license, tutorial links and expected default
   branch. Keep the private research repository and evidence private afterward.

GitHub documents additional consequences, including exposure of Actions history
and logs, in its [repository visibility guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).
Do not treat a later switch back to private as a way to recall copies or forks.

## If an uncertain item is found

Stop publication, preserve the private original and leave that item out of the
source edition. Explain the resulting functional gap rather than concealing it.
If it entered the source edition's history, fix the release preparation before a
visibility change; a new deletion commit alone is not removal from history.
Neither this checklist nor automated scanning is a guarantee that every legal,
privacy or electrical issue has been resolved.

## Source changes and generated metadata

Use the [public review commands](../public/BUILD.md#public-source-checks) during
editing. Do not invent a producer commit or edit generated checksums to pass CI.
After reviewing changed files, update their exact hashes in the allowlist, commit
that source review, and require a clean tree. Run the existing exporter:

```sh
# LAPTOP — clean committed source, NEW ignored export directory, no publication.
python3 tools/export_public_source.py --output build/public-release-review
```

Review the export manifest and differences. `PUBLICATION.json` records the
**producer commit**; it need not equal a later metadata-only commit. Copy only the
exporter's `PUBLICATION.json`, `SOURCE_SHA256SUMS`, normalized
`publication/allowlist.json` and `RESCUE_RUNTIME_SHA256SUMS` into the source edition
when refreshing its generated metadata. All selected authored files must already
match. Commit those generated files, rerun public checks and test a fresh clone.
Never export uncommitted work or substitute a success receipt for failed checks.

Before public visibility, enable and verify private vulnerability reporting if
available, following [SECURITY](../../SECURITY.md). A 404/denied API response is
not proof of absence. Inspect non-Git attachments/settings separately. This
checklist does not authorize automatic visibility changes or history rewriting.
