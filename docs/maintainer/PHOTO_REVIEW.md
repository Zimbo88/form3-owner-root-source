# Owner photograph review — 2026-10-08

The supplied deployment kit contains six distinct JPEG photographs. Copies in
builds, source archives and old worktrees are duplicates, not additional photos.
The curated source edition previously selected only `img_4040.jpg`. The private
developer guide had already reviewed and embedded three photographs; this update
restores the other two reviewed views to the public-facing clip guide.

| Original filename | Source-edition placement | Purpose / selection decision |
|---|---|---|
| `img_4039.jpg` | [Module and flash location](../public/PI5_CLIP_GUIDE.md#module-and-flash-location) | Processor/flash context before the closeup; not a verified pinout |
| `img_4040.jpg` | [Flash closeup](../public/PI5_CLIP_GUIDE.md#flash-closeup) | Package/leads and the obscured marking; already embedded, retained |
| `img_4044.jpg` | [Heatspreader reference before reassembly](../public/PI5_CLIP_GUIDE.md#heatspreader-reference-before-reassembly) | Contact-side and mounting-hole record beside the reassembly reminder |
| `img_4042.jpg` | Not included | Wider module/Pi/clip view; the retained private review flags potentially individual component/module labels |
| `img_4045.jpg` | Not included | Wider disassembly/thermal-assembly view; same private-review restriction |
| `img_4048.jpg` | Not included | Wider reassembled-electronics view; same private-review restriction |

All six original files were located and checked against the retained kit/manifest.
All six have zero EXIF entries. Absence of metadata alone does not establish that
visible labels are suitable for publication. The three selected images were
visually checked again, decode successfully as JPEG, and match the kit byte for
byte. `img_4039.jpg` and `img_4044.jpg` are 1200 × 1600; `img_4040.jpg` is 334 × 518.
Their exact hashes are in the reviewed allowlist and generated source checksums.
No original was overwritten, cropped or retouched.

The three excluded wider views were not copied into this Git history. Their
exclusion follows the existing private visual review; this check does not certify
them for release. A later selected crop/redaction needs a separate visible-label
review and truthful caption before adding it. Do not infer complete clip wiring
or electrical approval from an unreviewed bench photograph.

Photo credit: **Mathias Zimmermann**. These are historical repair observations,
not new hardware acceptance or compatibility evidence. The unrelated PNG in
`docs/assets/print-diagnostics-DEMO.png` is a labeled synthetic panel screenshot,
not one of the six owner hardware photographs.
