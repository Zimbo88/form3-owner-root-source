# Rights, provenance and future public release

I distribute my authored source, reviewed transformation recipes, independent panel,
instructions, original artwork and compatibility checksums. I keep original and
modified manufacturer binaries, extracted rootfs, private logs/jobs, credentials,
keyrings, calibration and device identities local. The source edition is prepared
separately from the private research history; no statement here guarantees legal clearance.

## File selection, not a blanket repository license

`publication/allowlist.json` explicitly names every selected input/destination,
SHA256, category, license scope and provenance. There are no directory wildcards.
A changed byte requires another review and a new pin. The exporter rejects common
secret/binary formats and unsafe paths, but content review remains necessary: a
text file can contain protected code or an opaque secret. Do not encode a vendor
payload to evade the filter. Do not treat minimal binary deltas as automatically
safe to publish. Hashes of required inputs can be distributed without including
the inputs; they prove compatibility, not ownership or rights.

The clock recipe retains a short target binding expression in
`tools/build_native_clock_review.py` to locate the exact supported change. That
minimal compatibility context is explicitly identified in the allowlist; the MIT
notice does not claim to relicense an underlying manufacturer's expression. Review
this context and the intended transformation before a public release. The QSPI
parser check uses a SHA256 pin instead of shipping the referenced instruction bytes.

The private producer's older branches/history are **not** the public candidate.
Do not simply toggle that repository to Public. Start any future public history
from the inspected `source/` export, with no old `.git`, private archive or deployment
receipt. Preserve the complete private history separately. This tool performs no
GitHub operation, history rewrite or permission change.

## Attribution and license boundaries

| Material | Rights/provenance |
|---|---|
| Authored panel, tools and original documentation | MIT, Mathias Zimmermann; retain earlier contributor notices in LICENSE |
| Original terminal/root icon and geometric OWNER caption | Project artwork; no manufacturer mark is traced or reused |
| Flash closeup in the clip guide | Photograph supplied by Mathias Zimmermann, included with the author's permission; no EXIF/GPS; component markings describe the hardware, not project branding |
| Orange rooted wordmark | Lato Light outlines, Łukasz Dziedzic, copyright 2010–2011; SIL OFL 1.1 font-created artwork, no font software bundled |
| BusyBox 1.37.0 patch/context | GPL-2.0-only; retain upstream rights and this patch's provenance, not relicensed by the root MIT notice |
| BusyBox source/toolchain, Linux/U-Boot, Python/OpenSSL/OpenSSH/Qt | Separately obtained components retain their respective licenses; this export includes no runtime binaries |
| SHA256 pins and runtime inventory | Factual compatibility metadata, not the referenced programs or a transferable device identity |
| Product names | Compatibility identification only; no endorsement or manufacturer affiliation |

I thank **Łukasz Jakóbiec** for the documented route that helped me access my printer:
[wemakerobots part 1](https://wemakerobots.com/en/projects/debricking-form-3-part-1/)
and [part 2](https://wemakerobots.com/en/projects/debricking-form-3-part-2/).
The articles/photos are linked, not redistributed or relicensed. That Form 3+ fault
and method differ from my Form 3. Electrical diagrams here are authored logical
relationships, not copied photographs or proof of a measured pinout.

[Lato](https://www.latofonts.com/lato-free-fonts/),
[OFL 1.1](https://openfontlicense.org/open-font-license-official-text/) and
[BusyBox licensing](https://busybox.net/license.html) provide upstream terms.
A later distributor of a compiled BusyBox rescue must review the corresponding
source/notice obligations; this source-only export does not discharge obligations
for a different binary distribution. The patch, source lock and [GPL v2 license text](../../licenses/GPL-2.0.txt) are included.

## Specific legal review still needed

For Germany, computer-program expression and copying/adaptation/distribution are
addressed by [UrhG §69a](https://www.gesetze-im-internet.de/urhg/__69a.html) and
[§69c](https://www.gesetze-im-internet.de/urhg/__69c.html). Authorized use/error
correction, backups and observation have conditions under
[§69d](https://www.gesetze-im-internet.de/urhg/__69d.html); interoperability
analysis has specific limits under [§69e](https://www.gesetze-im-internet.de/urhg/__69e.html).
These are not blanket permissions to redistribute recovered code.

Review the actual boot-protection mechanism and intended tool distribution against
[§69f](https://www.gesetze-im-internet.de/urhg/__69f.html), including paragraph 2,
rather than assuming every root method has the same legal status. Other laws and
contracts remain relevant under [§69g](https://www.gesetze-im-internet.de/urhg/__69g.html).
Compatibility naming is also conditional under
[MarkenG §23](https://www.gesetze-im-internet.de/markeng/__23.html).
Cosmetic clock/logo work is optional and is not presented as necessary error correction.

These primary sources identify questions for a qualified case-specific review;
they do not decide every jurisdiction, contractual circumstance or implementation.
Removing a manufacturer logo, keeping only scripts or requiring an input hash is
not a legal guarantee. Unclear recovered fragments, rights or protection questions
stay outside a public release until resolved.

## Release checks

1. Inspect every allowlist entry, including textual patch context and rendered assets.
2. Verify license notices, authorship, public documentation and linked primary sources.
3. Build the export from a clean commit; validate its manifest and full selected files.
4. Test a clean exported tree without proprietary evidence. Report evidence exclusions.
5. Audit **all** history and assets of the actual future public repository, not just HEAD.
6. Review remaining legal/electrical/compatibility gaps and obtain any required advice.
7. Make an explicit publication decision. Keeping this candidate private is the default.

The [release checklist](RELEASE_CHECKLIST.md) describes a manual visibility change
of the clean source edition only. No public release, visibility change or
manufacturer disclosure is automated.
