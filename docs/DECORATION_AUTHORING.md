# Decoration Authoring

This document defines the visual-design and validation guidance for Refrain decoration assets.

It is authoritative for how decorations should be conceived, authored, evaluated, iterated, and delivered.

It does not redefine the public decoration manifest schema, runtime rendering behavior, output geometry, QR semantics, or command-line interface.

- `docs/CONTENT_FORMAT.md` defines decoration manifest fields, layer methods, tinting configuration, QR placement fields, and validation rules.
- `docs/ARCHITECTURE.md` defines image spaces, aspect handling, rendering order, QR composition, and output-image behavior.
- `docs/CLI.md` defines `refrain-viewer` command syntax and override semantics.
- `docs/ENGINEERING.md` defines implementation and testing requirements for Refrain itself.

Decoration authors should use those documents when exact interface or runtime behavior matters rather than reproducing their requirements here.

## Design intent

Refrain is intended to reward attention rather than demand it.

A decoration supports the literary presentation. It should add character, structure, atmosphere, or visual interest without competing with the quotation for attention.

A successful decoration should feel intentional when noticed and unobtrusive when not.

Decorations should generally favor:

- restrained visual weight;
- generous negative space;
- clear literary presentation areas;
- coherent structure rather than unrelated ornaments;
- forms that remain legible after scaling;
- compositions that work across Refrain's supported display environments;
- visual decisions that survive limited-color and e-paper output where practical.

A decoration is not a complete page design. Refrain independently supplies literary content, backgrounds, colors, QR content, and other presentation choices.

## Decoration as an overlay

A decoration must be designed as a foreground overlay over an independently selected background.

Do not assume that transparent regions will reveal white pixels.

The background may be:

- white;
- lightly colored;
- textured;
- patterned;
- user-supplied;
- selected independently of the decoration.

Transparent regions must therefore be intentionally transparent rather than visually dependent on white or near-white pixels underneath.

If part of the design requires an opaque region to remain visually coherent, that opacity must be an intentional property of the decoration.

Do not solve background independence by covering the presentation with unnecessarily large opaque panels. Background artwork is expected to remain visually relevant where the decoration does not have a functional reason to obscure it.

### Alpha quality

Raster artwork must use correct transparency.

Do not create transparency by drawing artwork against white and simply deleting nominally white pixels afterward if that leaves pale anti-aliased edge pixels.

Edges must composite cleanly over non-white and textured backgrounds without visible white halos or unintended matte artifacts.

## Default color model

Decoration artwork should be monochrome and tintable by default.

Unless a design brief explicitly requires authored color:

- use neutral or black source RGB values;
- preserve transparency through alpha;
- allow Refrain to supply the decoration color through tinting;
- avoid embedding decorative color decisions into the source artwork.

Refrain tinting replaces source RGB while preserving alpha. Opaque greyscale values therefore do not retain independent tonal values after tinting.

If tonal variation must survive tinting, express it through techniques such as:

- alpha variation;
- line density;
- stippling;
- hatching;
- texture;
- spatial coverage.

Do not rely on several opaque grey RGB values remaining visually distinct after tinting.

Multi-color artwork is an exception, not the default. A design that intentionally preserves authored colors must be explicitly requested and should isolate non-tintable layers deliberately rather than accidentally bypassing the normal tinting model.

## Visual continuity

A decoration should read as one coherent composition.

Borders, flourishes, frames, botanical elements, geometric structures, or other repeated forms should connect naturally where the design implies continuity.

Avoid collections of individually plausible elements that fail to join into convincing larger structures.

The authoring medium is unrestricted. Decoration authors may use:

- raster drawing;
- vector drawing;
- procedural generation;
- compositing;
- masks;
- image-generation tools;
- texture synthesis;
- combinations of these techniques.

The quality of the final raster assets matters more than the authoring technique used to produce them.

Do not constrain the design to SVG, line art, or another medium unless the individual assignment requires it.

## Composition boundaries

Decorations are intended primarily to occupy the visual perimeter of the presentation rather than the central literary field.

Suitable composition regions include:

- borders;
- corners;
- edges;
- narrow side structures;
- upper or lower thirds;
- localized edge-connected elements occupying less than roughly one third of the canvas.

Artwork may extend inward where the composition requires it, but should preserve a substantial uninterrupted central region for the quotation, source, and attribution.

Avoid designs whose primary visual mass crosses through the middle of the canvas or divides the literary field into multiple competing regions.

A decoration should normally read as something surrounding, framing, supporting, or entering from the perimeter of the presentation rather than as a full-canvas illustration placed behind or around the text.

The exact literary bounds are controlled separately by presentation insets. Decoration authors are still responsible for composing artwork that leaves appropriate visual space around those bounds and does not rely on Refrain to detect graphical overlap.

## QR-aware design

QR placement is part of the decoration design.

Do not assume Refrain's default bottom-right QR position is fixed or preferred. Decoration manifests can position the fixed QR allocation from the left, right, top, or bottom edges, or center it on one supported axis.

The authoritative placement fields and constraints are defined under [`Decoration manifests`](CONTENT_FORMAT.md#decoration-manifests), particularly `qr_from_left`, `qr_from_right`, `qr_from_top`, `qr_from_bottom`, and `qr_centered`.

Choose the QR position deliberately as part of the composition.

Moving the QR is not an escape from integrating it with the artwork. If a different position produces a stronger structural relationship between the QR and the decoration, use it. Do not retain the default position and deform otherwise coherent artwork merely because that is where Refrain places the QR when no decoration-specific placement is supplied.

Conversely, do not move the QR into an empty corner merely to avoid solving its relationship with the artwork. The QR should normally participate in the composition rather than sit beside it as an unrelated element.

A decoration may need to work both when Refrain presents a QR code and when QR is unavailable or suppressed.

QR/no-QR conditional artwork is available when the presence of the QR genuinely changes a local structural region, but conditional variants are not inherently required. A composition that integrates the QR successfully without changing its decoration layers should remain a single shared composition.

When conditional artwork is used, the QR and no-QR states are two states of one decoration, not two separate decorations with a shared theme.

### Shared composition

The QR and no-QR states must preserve the same overall composition.

Most decoration artwork should be shared between both states.

Conditional artwork should be limited to the smallest practical structural region directly affected by the presence or absence of QR.

Examples include:

- alternate versions of one corner when QR occupies that corner;
- alternate versions of a section of one edge when QR is centered along that edge;
- a localized structural continuation that closes a gap when QR is absent.

Do not use QR conditionals as permission to redesign unrelated borders, corners, flourishes, visual mass, or composition.

If the QR and no-QR renders are overlaid, almost all decoration artwork should remain unchanged.

### No placeholder ornaments

The no-QR state must not merely replace the QR code with an unrelated decorative object occupying the same square.

It should restore the natural uninterrupted form of the affected structural region.

The goal is not:

> QR square when enabled, decorative thing in the QR square when disabled.

The goal is:

> one coherent decoration whose affected local structure adapts naturally to whether the QR allocation is present.

### Localized asset strategies

The public decoration layer model may require the localized QR/no-QR difference to be implemented using whole conditional layers.

That is acceptable provided the resulting artwork still follows the design rule above.

For example, two conditional source assets may be almost entirely pixel-identical except for one QR-affected corner.

Prefer the simplest asset/layer arrangement that produces the intended visual result without creating unnecessary duplication or complexity.

Refer to `docs/CONTENT_FORMAT.md` for the supported conditional-layer and nine-slice interfaces.

## QR integration

The QR code should look like it belongs to the decoration rather than appearing as an unrelated white square cut through it.

Prefer compositions that give the QR a structurally meaningful place within the artwork. A naturally geometric surface or object can be particularly effective: for example, a panel, plaque, architectural element, sign, book, birdhouse, or another form whose geometry plausibly accommodates the QR allocation.

The surrounding artwork must still make visual sense independently of the square QR geometry.

Do not create a dedicated frame, pocket, socket, cartouche, or outlined enclosure whose primary purpose is simply to surround the QR. Likewise, do not bend or interrupt otherwise coherent artwork around the QR allocation when moving the QR or redesigning the local composition would produce a more natural result.

QR placement is flexible, but relocation should improve integration rather than merely move the code out of the artwork's way.

Where QR placement requires visual support, the decoration should provide an integrated structural region around or containing the QR allocation.

The supporting form should have a visual purpose within the composition beyond containing the QR. It may be part of a larger object, architectural feature, botanical structure, edge treatment, or other compositional element whose shape remains plausible independently of the QR allocation.

The supporting region should normally be tintable with the rest of the decoration.

Avoid oversized outlined rectangles that leave the independently selected background visible between the decoration and the QR code's white quiet zone.

The QR code itself is composed by Refrain and is not part of the authored decoration asset.

Do not bake QR modules, QR quiet zones, or fake QR graphics into decoration artwork.

## Aspect and scale

Decoration artwork is authored for Refrain's high-resolution design system and must remain coherent when adapted to supported presentation aspects.

The authoritative image-space and aspect behavior is defined in `docs/ARCHITECTURE.md`.

For normal decoration development, use the full 16:10 design canvas at 3840 × 2400 as the primary design and inspection environment.

Designs should not depend on fine detail that disappears when rendered for substantially smaller outputs.

A final 4:3 render at 1600 × 1200 is required as the standard small-output and alternate-aspect check.

Additional aspect or resolution testing is required only when a concrete property of the design makes the standard validation insufficient.

Do not build exhaustive render matrices speculatively.

## Background robustness

Decoration authors must assume that normal Refrain operation may place their artwork over an independently selected background.

The standard full-resolution validation background is:

```text
handmade-paper
```

This background is used because its non-white textured surface exposes:

- accidental white mattes;
- transparent gaps that were visually designed as if they were white;
- weak edge treatment;
- QR support regions that expose unintended background;
- other assumptions that may remain invisible on a white canvas.

The standard background is a design stress test. It is not a statement that the background itself is suitable for every physical display technology.

Physical e-paper validation of a decoration is intentionally performed without a background so that background reproduction quality does not invalidate the decoration test.

## Standard validation presentation

Use a deterministic presentation when judging decoration artwork.

Create or select a temporary working Refrain configuration for the graphics assignment. Its adjacent user-assets tree must contain the decoration package being developed so that Refrain discovers it through the normal public asset interface.

The working configuration is part of the authoring environment, not a final decoration deliverable.

The standard presentation controls are:

```text
--config <working-config>
--entry @preview:2
--font lora
--text-color black
--tint black
--min-font-size 56
--max-font-size 200
```

These settings exist to keep decoration validation focused on the decoration rather than random presentation choices.

They do not imply that a completed decoration should recommend these same presentation resources in its manifest.

## Required validation renders

The normal decoration workflow requires four final validation renders.

Use the same working configuration for all four renders. Replace `<working-config>`, `<decoration-id>`, and output paths as appropriate.

### Full-resolution QR render

```sh
refrain-viewer \
  --config <working-config> \
  --entry @preview:2 \
  --font lora \
  --text-color black \
  --tint black \
  --min-font-size 56 \
  --max-font-size 200 \
  --background handmade-paper \
  --decoration <decoration-id> \
  --qr \
  --aspect 16:10 \
  --resolution 3840 2400 \
  --output validation/final-qr-16x10-3840x2400.png
```

### Full-resolution no-QR render

```sh
refrain-viewer \
  --config <working-config> \
  --entry @preview:2 \
  --font lora \
  --text-color black \
  --tint black \
  --min-font-size 56 \
  --max-font-size 200 \
  --background handmade-paper \
  --decoration <decoration-id> \
  --no-qr \
  --aspect 16:10 \
  --resolution 3840 2400 \
  --output validation/final-noqr-16x10-3840x2400.png
```

### Full-resolution debug render

```sh
refrain-viewer \
  --config <working-config> \
  --entry @preview:2 \
  --font lora \
  --text-color black \
  --tint black \
  --min-font-size 56 \
  --max-font-size 200 \
  --background handmade-paper \
  --decoration <decoration-id> \
  --qr \
  --debug-layout \
  --aspect 16:10 \
  --resolution 3840 2400 \
  --output validation/final-debug-qr-16x10-3840x2400.png
```

### 4:3 small-output render

```sh
refrain-viewer \
  --config <working-config> \
  --entry @preview:2 \
  --font lora \
  --text-color black \
  --tint black \
  --min-font-size 56 \
  --max-font-size 200 \
  --background none \
  --decoration <decoration-id> \
  --qr \
  --aspect 4:3 \
  --resolution 1600 1200 \
  --output validation/final-qr-4x3-1600x1200.png
```

The 4:3 render intentionally uses `background none`.

Its purpose is to evaluate:

- the decoration at a substantially smaller raster size;
- behavior at a different aspect ratio;
- suitability for physical e-paper inspection;
- whether lines, forms, and local structure remain coherent after scaling.

It is not intended to evaluate the physical reproduction of a selected background.

## Iterative authoring workflow

A decoration is not complete when its first valid asset renders successfully.

Use an iterative visual workflow:

1. Create or revise the decoration assets and manifest.
2. Render the relevant standard validation image through Refrain itself.
3. Inspect the completed presentation rather than judging the source artwork in isolation.
4. Identify concrete visual defects.
5. Revise the artwork or metadata.
6. Render again.
7. Repeat until the final validation renders satisfy the design.

During iteration, generate only the renders needed to answer the current design question.

Do not repeatedly regenerate the complete validation set after every minor change when one representative render is sufficient.

Run the complete required validation set once the design is believed to be final.

Additional validation is appropriate when a concrete concern remains, such as:

- unusual edge behavior;
- a complex nine-slice composition;
- a QR placement that interacts with crop behavior;
- particularly fine detail;
- an intentionally unusual presentation region.

Do not expand validation merely for coverage.

## Visual acceptance criteria

A decoration is ready for delivery when:

- the composition supports rather than dominates the literary content;
- transparent regions work over a non-white textured background;
- no unintended white halos or matte artifacts are visible;
- tintable artwork renders coherently using black tint;
- the QR state looks structurally integrated;
- the no-QR state looks complete without acting as a placeholder substitution;
- QR/no-QR differences remain localized to the affected structure;
- the QR support region does not expose an unintended background moat around the QR quiet zone;
- lines, borders, repeated forms, and structural connections are visually coherent;
- the design remains usable at 4:3 @ 1600 × 1200;
- the final manifest and assets load through Refrain without relying on unsupported behavior.

## Final deliverables

Deliver only the finished decoration package and the required final validation renders.

Each submitted version must be stored in its own numbered revision directory.

The first submitted deliverable is:

```text
rev1/
```

If revisions are requested, place each subsequent submitted version in a new directory with the next revision number:

```text
rev2/
rev3/
rev4/
```

Once a revision has been submitted, its contents are immutable.

Never erase, overwrite, rename, replace, or otherwise remove previously submitted deliverables when producing a revision.

A requested revision must preserve every earlier submitted revision exactly as delivered and create a new revision directory containing the updated result.

Working files may be changed or replaced freely while developing the current revision before it is submitted.

Each revision directory must contain the complete deliverable for that revision and must not depend on files stored in an earlier revision directory.

The decoration package must include:

- `decoration.yaml`;
- every image asset referenced by the manifest;
- any QR/no-QR conditional assets;
- any layered or nine-slice assets required by the final design.

The required validation renders for each submitted revision are:

```text
final-qr-16x10-3840x2400.png
final-noqr-16x10-3840x2400.png
final-debug-qr-16x10-3840x2400.png
final-qr-4x3-1600x1200.png
```

For example:

```text
decoration/
├── rev1/
│   ├── <decoration-package>/
│   ├── final-qr-16x10-3840x2400.png
│   ├── final-noqr-16x10-3840x2400.png
│   ├── final-debug-qr-16x10-3840x2400.png
│   └── final-qr-4x3-1600x1200.png
└── rev2/
    ├── <decoration-package>/
    ├── final-qr-16x10-3840x2400.png
    ├── final-noqr-16x10-3840x2400.png
    ├── final-debug-qr-16x10-3840x2400.png
    └── final-qr-4x3-1600x1200.png
```

Do not include an exhaustive matrix of exploratory renders, intermediate attempts, contact sheets, coverage matrices, or redundant examples unless the assignment explicitly requests them.

Intermediate working files may be retained by the author when useful but are not part of the normal submitted deliverable.

## AI-assisted graphics assignments

For an isolated graphics-design assignment using Codex or another implementation agent:

1. Start from a fresh clone of the current Refrain `main` branch.
2. Read `AGENTS.md` and this document.
3. Consult the authoritative Refrain documentation when exact schema, rendering, or CLI behavior is needed.
4. Use the clone as a reference and active validation environment.
5. Run Refrain and `refrain-viewer` as needed to inspect and test generated assets.
6. Do not modify Refrain source code, tests, runtime behavior, or project documentation as part of the graphics assignment.
7. Do not create branches, commits, pull requests, issues, or other GitHub changes.
8. Place final decoration deliverables outside the temporary clone.
9. Produce one deliberately specified finished design unless the assignment explicitly requests alternatives.

The agent should not re-derive Refrain's design system by exhaustively reading implementation source when the authoritative documentation already answers the question.

Inspect implementation only when the documented behavior is insufficient to diagnose a concrete validation problem.

The project documentation is the source of truth; conclusions inferred from source inspection do not supersede it.

## Creative briefs

This document supplies the reusable authoring contract.

An individual decoration assignment should supply only the design-specific requirements that vary between projects, such as:

- visual style or historical influence;
- theme;
- desired visual density;
- preferred QR location;
- reference imagery;
- required motifs;
- deliberate exceptions to the default monochrome/tintable model;
- other composition-specific constraints.

Do not restate the entire Refrain authoring contract in every creative brief.

If an assignment conflicts with this document intentionally, the brief should identify the exception explicitly.
