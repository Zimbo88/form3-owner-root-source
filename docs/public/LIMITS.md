# Compatibility, coverage and remaining gates

This candidate is a reproducible **source selection**, not a universal root image or
legal certification. I distinguish personal display observations from captured
measurements, code analysis and automated tests.

| Label | Meaning |
|---|---|
| FILE/CODE | Parsed original or inspected implementation with exact version/hash |
| OFFLINE TEST | Authored fixture/test, not a device observation |
| EMULATION | Selected ARM execution; a different VM kernel is not genuine Linux 4.9 proof |
| OWNER HARDWARE OBSERVATION | My direct observation or a separately identified historical device receipt |
| INFERENCE / UNKNOWN | Reasoned interpretation / insufficient evidence; never green by default |

## Coverage

| Area | Status | Precise limit |
|---|---|---|
| Independent panel/transaction source | Available and fixture-testable without proprietary files | Actual tests/results belong to the source-hash receipt, not a permanent advertised count |
| Reference rescue/acquisition | Historical hardware observation | Factory image hash and boot implementation are reference-specific |
| Another stock Form 3 | Partially specified profile-engineering workflow | No universal importer, stock initial root or completed board-specific electrical review |
| Electrical acquisition/write | Measurement and recovery gates documented | Exact flash suffix, board circuit and safe contact/power plan must be established locally |
| Normal SSH/SFTP/panel | Historical reference-device acceptance | New target needs genuine-kernel, reboot, identity, network and vendor-service acceptance |
| Native clock | My display confirmation plus fixtures | Europe/Berlin 2020–2037; Idle display is not an actuator permission |
| Original project logo | Authored geometry, private build and installed hash/readback | Latest original mark's appearance on a subsequent boot needs separate observation |
| Local status | Proc/sysfs/version/storage adapters, explicit freshness | Five thermal channels are not GPU utilization or all physical heater/fan values |
| Diagnostics | Bounded allowlisted local exports; logs can be plaintext | Missing histories/journals and error mentions do not prove original fault cause |
| Materials | Estimates/history, owner ledger and scoped Clear usage adjustment | No general cartridge support, identity cloning or dispensing override |
| Privacy | Owner preference/model and explicit local-only boundary | Preview is not applied vendor policy; cloud compatibility/queue effects are not fully accepted |
| Licenses | Read-only metadata where present | No manufacturer signing/issuance power and no fabricated activation |
| A/B persistence | p7 owner files persist separately | Vendor upgrade may remove p6 hook, change version or select unsupported slot |
| Safety / printing | Protections retained; unknown writes disabled | Sustained printing and repair success are separate from working owner services |
| Public release | Explicit pinned export and source/rights review | Old private history must not be toggled public; case-specific legal questions remain |

The inspected encrypted support archive has no demonstrated matching decryption
key. Successful decryption of selected firmware releases does not imply FORMLOGS
access. Firmware/key archaeology, raw decompilation, secret inventories, device logs
and private jobs are outside this public selection. No source download of vendor
firmware or credential-hunting utility is required by these reproduction steps.

## Read adapters and daily development

`panel_data.py` labels source, timestamp/freshness and LIVE/CACHED/HISTORICAL/DEMO/
UNAVAILABLE. Proc/sysfs expose load, RAM, uptime, mounts and reference CPU/GPU/core/
DSP-EVE/IVA thermal zones. CPU load is not GPU utilization; a zone temperature is
not measured resin temperature. Imported consumable/history records remain historical
and estimated volume is never presented as a physical level measurement.

`tools/build_diagnostic_bundle.py` and `tools/export_diagnostics.py` operate on
explicit copied inputs. Raw output remains private; inspect allowlisted redaction,
size/record bounds and manifest before sharing. `form3ctl.py` decodes an existing
bounded local stream; it does not advertise live discovery/status support merely
because a protocol method name exists. Do not execute a job or recovered installer.
No generic privileged shell, arbitrary file path or D-Bus proxy is part of the panel.

## Editable figures

Each `.mmd`/`.dot` source and rendered SVG is local, editable and described by an
accessible SVG description. The figures communicate logic, not successful new tests.

| Figure | Purpose / proof boundary |
|---|---|
| 01 boot chain | Reference code + historical rescue boot |
| 02 storage map | Reference storage roles; inspect current slot before writes |
| 03 clip power boundary | Logical domains; no asserted part pinout |
| 04 measurement points | Named unresolved contact requirements, not invented readings |
| 05 acquisition network | Isolated reference rescue defaults |
| 06 rescue/normal transition | Initial root precedes owner SSH installation |
| 07 SSH trust | Owner authorization and host identity are distinct |
| 08 panel privilege | Unprivileged web process, bounded adapters |
| 09 package transaction | Independent signer, plan/readback/rollback |
| 10 API boundaries | Local host API, native protocol, IPC, cloud and owner panel are distinct |
| 11 factory netboot | Experimental code-derived candidate, not a proven stock-root route |
| 12 privacy/cloud | Local logging and optional/required cloud paths are distinct |

## Review quality without pretending gaps are solved

The guides provide purpose, prerequisites, exact source/tool paths, guarded command
contexts, expected results, failure gates, rollback, limitations, diagrams and a
repeatable fixture/export check. Assess those items using the actual exported tree.
The board-specific physical write step, general factory-profile support, legal
clearance and print repair remain unresolved. They must not receive “complete” or
8/10 research-proof scores merely because their documentation is clear.

Run [setup](BUILD.md), review export checksums/manifest and record remaining gaps
before a release. Keep new test receipts separate from historical acceptance;
excluded evidence tests are not passed tests. Re-run relevant physical acceptance
only in a separately authorized supervised session, never from the build path.

## Scoped Clear usage adjustment (0.5.13-review)

[The new reset workflow](CARTRIDGE_PANEL_RESET.md) supersedes earlier blanket statements that no native usage adjustment is available. It is limited to legacy Clear FLGPCL02 and pinned 2.5.6-2773 components. It does not establish physical resin quantity, universal consumable compatibility or a motor inhibit.
