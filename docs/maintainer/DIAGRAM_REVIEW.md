# Diagram rendering review — 2026-10-08

Scope: the curated source edition at version `0.5.13-review`. This review changes
presentation and documentation checks only. It adds no hardware acceptance.

## Reproduced failure and correction

The sequence diagram in [Clear panel reset](../public/CARTRIDGE_PANEL_RESET.md#privilege-and-transaction-boundary)
failed in Mermaid 11.17.2 at the raw semicolons in transaction messages.
Mermaid treats a semicolon as a statement separator; its
[sequence syntax reference](https://mermaid.js.org/syntax/sequenceDiagram.html#entity-codes-to-escape-characters)
requires `#59;` for a literal semicolon. The messages now use explicit line breaks.
Participants and long messages are wrapped without changing the transaction order.

The decoding and material-settings diagrams were excessively wide when scaled
into a documentation column. Their direction is now top-to-bottom. All four inline
Mermaid diagrams have accessible titles and descriptions. No technical values,
checks, authorization rules or evidence claims changed.

## Coverage and results

| Representation | Count | Result |
|---|---:|---|
| Inline Mermaid in Markdown | 4 | All parsed and rendered after correction |
| Editable Mermaid equivalents of numbered DOT figures | 12 | All parsed and rendered |
| Checked-in SVG files, including logos and clip illustrations | 17 | All rendered in Chromium and visually reviewed |
| Authoritative DOT sources → checked-in SVG/Mermaid pairs | 12 | Byte-for-byte regeneration check passed with Graphviz 14.1.2 |

These counts include alternative representations of the same diagrams, not 45
independent illustrations. The 12 numbered SVGs are embedded in their relevant
guides; the public source check verifies links, descriptions and safe SVG content.
No additional broken diagram was found. Rendered screenshots were inspected for
missing text, clipping and layout; outputs remain ignored under `build/`.

Renderer environment: Mermaid **11.17.2**, Puppeteer **25.10.0**, Chromium
**152.0.7977.75**. The browser ran in a disposable user/PID/filesystem sandbox
inside a disconnected network namespace, without the host home or credentials.
Chromium's own sandbox was unavailable under the host AppArmor policy, so the
outer sandbox provided isolation. Browser requests were also rejected. This is
local browser rendering, not a claim about GitHub's exact current renderer version.

## Repeatable checks

Run the [public source checks](../public/BUILD.md#public-source-checks). The
standard-library checker now catches unescaped sequence-message semicolons in
both Markdown and `.mmd` files. Four regression fixtures cover the original failure,
entities/line breaks, the separate flowchart grammar, and repository integration.
This narrow guard is **not a complete Mermaid parser**.

```sh
# LAPTOP — optional host Graphviz dependency, version 14.1.2 for exact output.
python3 tools/render_public_figures.py --check
```

For a complete Mermaid renderer check, use a separately installed, reviewed
Mermaid CLI with its browser dependencies. CLI 11.17.0 and Mermaid 11.17.2 were
available for this review. The CLI accepts Markdown and renders its Mermaid blocks;
keep all resulting Markdown/SVG files in a new ignored output directory. Use a
disposable environment for browser execution, not a personal browser profile.

```sh
# LAPTOP — optional renderer environment; no printer or private inputs.
# Prerequisite: mmdc and a usable browser sandbox in that environment.
mkdir build/mermaid-review
for source in docs/public/CARTRIDGE_PANEL_RESET.md \
  docs/public/CARTRIDGE_DECODING.md docs/public/CARTRIDGE_RECONCILIATION.md \
  docs/public/MATERIAL_SETTINGS_RESEARCH.md; do
  mmdc -i "$source" -o "build/mermaid-review/$(basename "$source")" || exit 1
done
for source in docs/figures/*.mmd; do
  mmdc -i "$source" -o "build/mermaid-review/$(basename "$source" .mmd).svg" || exit 1
done
```

Missing browser dependencies or a failed sandbox launch are **NOT RUN**, not a
passed diagram review. The ordinary source checks do not install Node packages,
fetch browser binaries, start a browser, or depend on external link availability.
