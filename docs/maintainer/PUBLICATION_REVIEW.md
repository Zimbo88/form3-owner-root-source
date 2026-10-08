# Public source review — October 2026

Historical preparation review. The later [public release record](PUBLIC_RELEASE.md)
records the 2026-10-08 visibility decision, checks and security-reporting setting.
The results and then-open gates below are retained as historical evidence.

## Scope and provenance

Review baseline: curated source commit
`a49b2ed358ee70fb14a885aa44d4517adc9854b0`, `VERSION=0.5.13-review`.
Inventory and initial changes: 2026-10-05; resumed after an explicit pause on
2026-10-07. The private acquisition/developer trees were not reorganized. No printer,
Pi, firmware installer, cloud credential or hardware operation was used.

The 198 baseline tracked files were inventoried with hashes, versions, AST symbols
and claim locations; the source, guides and evidence relationships were reviewed.
The private inventory and claim working matrix remain outside Git. This is a
maintainer/source review, not independent certification, legal advice or new
hardware acceptance. Runtime source under `owner-maintenance/` and `owner-ui/`
is unchanged; their README files are updated. VERSION therefore remains unchanged.

## Findings and resolutions

| Finding | Resolution / evidence |
|---|---|
| Walkthrough said current 0.5.9 source was not installed; maintenance README named 0.5.9 | Current version now points to VERSION; historical 0.5.8/0.5.9 capture/feature statements retained. [Version check](../../tools/check_public_source.py) tests current wording, including wrapped lines |
| Rescue receipt appeared to deny later normal access | Added a phase-local scope field without changing its result arrays; [evidence index](../public/EVIDENCE_STATUS.md) separates later receipt and narrative observations |
| Earlier decoder/writeback reports said no writer existed | Explicit historical banner; later [panel chapter](../public/CARTRIDGE_PANEL_RESET.md) and its existing receipt retain their different scope |
| Panel write acceptance could be confused with preview | Explicit implemented / fixture / historical explicit write / live panel read-only preview distinction; no claim of browser-triggered physical write acceptance |
| “Signed source packages” | Replaced with owner-signed installation/update packages. Exported review tarballs remain unsigned |
| Several overlapping first-install command paths | [Walkthrough](../public/COMMAND_WALKTHROUGH.md) is canonical; references explain invariants and link to exact phases |
| Missing global modification audit | [Modification map](../public/MODIFICATION_MAP.md) covers QSPI, first eMMC writes, hooks, identities, package trust, reset extension and recovery |
| Hard to see current boot/storage state | Phase map and 20 phase summaries name state/change/expected/stop/recovery. Added explicit no-Rescue-boot failure path without bypassing original readback gates |
| Claimed setup details could be mistaken for universal support | [Reference matrix](../public/REFERENCE_SETUP.md) marks missing exact Pi OS/flashrom version and unresolved chip suffix/shared rail |
| Private-review policy text on public entry pages | Public CONTRIBUTING/SECURITY; internal release process moved to `docs/maintainer/`, old checklist URL retained |
| Existing grammar hint missed f-strings on this Python 3.14.4 host | [Explicit AST guard](../../tools/python35_grammar.py) complements the Python 3.5 parser hint; negative regression catches the observed gap |
| File-only link checks missed fragments | [Public checker](../../tools/check_public_source.py) checks headings, duplicate suffixes, local paths, generated metadata, shell snippets and SVGs; standard-library fixtures cover failures |

## Figures and asset review

All 12 numbered DOT sources now regenerate both SVG and equivalent Mermaid through
[render_public_figures.py](../../tools/render_public_figures.py). Graphviz used for
this review: **14.1.2**. Different Graphviz versions can lay out the same source
differently; public CI checks content/safety/accessibility, not byte equality with
an arbitrary renderer version. `--check` reproduces the committed results using
the recorded renderer.

| Figures | Placement / changes |
|---|---|
| 01, 02, 03, 05 | Root concept/acquisition guide; reference proof labels retained, wrapped labels |
| 04 | Clip guide: measurement relationships, not invented physical probe coordinates |
| 06 | Installation reference: non-circular Rescue-to-normal route; port spacing fixed |
| 07 | SSH reference: independent client/server/package identities |
| 08 | Panel README: now includes the narrow root UNIX-socket reset broker; “settings only” was outdated |
| 09 | Modification map: signed package/transaction/rollback stages |
| 10, 11, 12 | Named research appendix: API, unproved stock netboot, privacy/cloud boundaries. API/privacy diagrams reflowed to avoid excessive width |

Rendered figures were visually inspected as a contact sheet; no clipped labels
were observed. Source descriptions and captions explain scope/solid/dashed arrows.
All numbered SVGs are embedded; the directory is not an unused gallery. On small
screens, use the linked vector or adjacent tables for dense details. The two
existing raster assets were inspected: the hardware closeup has no EXIF/GPS and
obscured part marking remains explicitly unresolved; the diagnostics image is
labeled DEMO and has no embedded metadata. No new third-party image was copied.

## Checks and what they prove

The [public check commands](../public/BUILD.md#public-source-checks) are the single
CI path. The full developer fixture suite is separate and retains mandatory
network/mount isolation. Initial resumed run: **485 fixtures, 0 failures, 0 errors,
0 skipped**; the wrapper correctly remained failed while two report links and a
prose-style issue were unfinished. That incomplete run is not a release PASS.

The selected standard-library tests also passed: public checker (23), exporter
(12), documentation voice (3). Tutorial tests (11) passed on this host, including
Bash syntax, synthetic ext4 fields, SSH profile generation and dnsmasq syntax only.
No DHCP service was started. Final source/fixture/export results are recorded in
the final verification section below after execution.

NOT RUN in this review: private-evidence Rescue suite, genuine target ARM execution,
full-system VM, physical electrical/flash/install/print tests and a new physical
cartridge write. Their historical receipts remain separate. Python grammar and
host fixtures are not proof of old-kernel runtime compatibility.

## Sources and external availability

Flashrom in-system, Pi and CLI links now consistently use upstream commit
`8e36840a2894f73187e225d9da51bbdfff582a6c` (v1.6.0 documentation). This is not an
invented historical tool version. Upstream generic powered-board/reset-line advice
is not adopted as a Form 3 procedure. The old Winbond product-selection PDF was
removed in favor of the already linked Winbond-authored **W25Q32JV Rev I,
2021-05-04**, with exact-part lookup on the manufacturer site. Candidate JV data
still does not identify a covered suffix. No voltage or pin mapping was changed.

The ext4 mount documentation is pinned to Linux documentation v6.12; it documents
the no-replay caveat, not compatibility of a 6.12 kernel with this printer. The
superblock reference stays an official unversioned page because the attempted
version-specific URL could not be verified. Pi documentation and OpenSSH manuals
remain official live references; they must be rechecked when tools change.

Availability review on 2026-10-07: 29 distinct linked documentation URLs, 26 HTTP
200 results and 3 Pi documentation variants returning HTTP 403 to the host client.
The browser research tool had retrieved the Pi hardware page earlier; a host 403
is recorded as UNVERIFIED, not evidence that the documentation is absent. External
availability does not block CI and does not validate every remote fragment.
No discovered device/vendor service endpoint was probed.

## History and repository review

Baseline reachable-history audit: **8 commits, 259 blobs**, across all locally
reachable branches/remote refs; no tags. Existing format/secret patterns and local
network/path patterns produced no findings. This is a bounded scan, not proof
that every opaque credential or personal datum is absent. The only raster files
are the reviewed owner closeup and DEMO screenshot. Runtime manifests contain
paths/sizes/hashes, not executable firmware. No history was rewritten.

GitHub API review confirmed repository ID **1377379732**, private visibility,
four branches, zero tags/releases/issues/PRs/Actions runs/artifacts/hooks/deploy
keys in the paginated responses. Wiki and discussions were disabled. Pages and
private-vulnerability-reporting returned 404, which is not treated as proof of
absence or enabled reporting. Actions was disabled at the initial review; the
workflow file does not by itself prove a hosted CI run.

Final upload attempt: GitHub refused the active workflow because the existing
OAuth credential lacks `workflow` scope; existing GitHub SSH authentication was
also unavailable. The complete active-workflow candidate is preserved on the
local `docs/publication-readiness-20261005` branch at
`4b436911570e1a7752c1411f4c53e5d0d3d1bdcc`. No history was rewritten.
The publishable follow-up starts from the original review baseline and contains
the same reviewed source, with CI as an inactive
[template](ci/public-source.yml.example) and this explicit limitation. Repository
Actions was restored to disabled after the blocked upload. The preparation briefly
configured a pinned-action allowlist and read-only token permissions; no hosted
workflow ran. The remaining activation steps are in [BUILD](../public/BUILD.md#hosted-ci-activation-pending).

## Remaining release and engineering gates

| Gate / exact path | Why it remains |
|---|---|
| [RIGHTS_AND_RELEASE](../public/RIGHTS_AND_RELEASE.md#specific-legal-review-still-needed) and `tools/build_native_clock_review.py` | Maintainer/legal review of intended distribution and minimal vendor binding context remains explicit. A source-only filter cannot provide legal clearance |
| [SECURITY](../../SECURITY.md#reporting-a-vulnerability) | Establish and verify a private reporting channel before public release; no invented contact or “enabled” claim |
| [Release checklist](RELEASE_CHECKLIST.md) | Final visibility decision and review of provider-only attachments/settings, including inaccessible data, remain maintainer actions; no automatic public toggle |
| [CI template](ci/public-source.yml.example), [BUILD](../public/BUILD.md#hosted-ci-activation-pending) | Hosted CI awaits a credential authorized to upload workflows and an observed successful run. Local checks are complete; this is not a source/test failure |
| [PI5_CLIP_GUIDE](../public/PI5_CLIP_GUIDE.md), [ROOT_GUIDE section 4](../public/ROOT_GUIDE.md#4-a-different-factory-hash-profile-engineering-not-pin-removal) | Actual part suffix, electrical checks and unknown-device profile engineering are prerequisites for another device, not documentation defects to hide |
| [Evidence status](../public/EVIDENCE_STATUS.md) | No single completely hardware-accepted current version; no new live browser-to-device reset, primary HTTPS or full reboot acceptance inferred from preview |

Publication readiness is split: a source tree can pass reproducible technical
checks while the actual visibility release remains **HOLD pending maintainer
rights/reporting/provider review**. This review does not promise legal safety,
universal compatibility or hardware completeness.

## Final verification

On 2026-10-07 the complete disconnected curated fixture run passed **490 tests,
0 failures, 0 errors, 0 skipped**. Its private source-bound log SHA256 is
`69ec21cae59f1c17b3bcd39b75e6cf41057122111c384c4510e42eb55113ec18`.
This count includes the 23 new public-source fixtures; do not add overlapping
selected runs to claim a larger total. The wrapper's source checks also passed.

The canonical walkthrough's **49 shell blocks are byte-identical to baseline**.
All runtime Python/frontend files are unchanged. The editing source review passed
252 local references, 56 heading fragments, 84 shell checks, all 17 SVGs and
12 target-module grammar checks. Generated publication metadata was intentionally
excluded from that editing result; the release command requires it. The clean-commit
export and final-clone results are recorded separately with their actual hashes,
not retroactively claimed by the editing run.

Documentation audit: entry/state navigation, reference limits, identity/port
scope, write/rollback maps and unknown-hardware stops now have explicit links.
Remaining hardware/rights/reporting gaps are visible in the gate table above;
clarity of an UNKNOWN is not evidence that it was solved. No self-assigned score
or test count is a substitute for those gates.
