# Presentation and Rendering

## Preparation and renderer interfaces

Daily-image preparation accepts a committed daily selection record, its validated publication checkpoint, and an explicit sequence of cumulative reveal stages.

Preparation resolves or recovers destination-independent artistic choices, applies destination overrides, derives effective presentation requirements, and generates complete images without accessing physical display hardware.

Neither preparation nor the renderer selects literary content, modifies selection or repetition history, advances reveal progress, or determines application lifecycle policy.

The shared literary renderer owns typography, fitting, positioning, and drawing of quotations and optional source and attribution within the resolved literary rectangle. It does not read application configuration, resolve resource pools, access persistent selection state, or operate display backends.

Graphical composition, literary rendering, QR composition, and destination visual conversion are separate responsibilities.

Use Pillow for image composition and rendering. Rendered output must be testable and inspectable without physical Raspberry Pi display hardware.

Display-specific conversion is permitted only at the defined destination visual-conversion boundary. The literary renderer must not depend on Waveshare APIs, GPIO, SPI, or vendor driver objects.

## Canonical resolution and resource precedence

For each committed daily selection, resolve destination-independent artistic choices from the captured content preferences, effective configuration, and available resources. Persist those choices in the complete content-and-presentation checkpoint in `publication.json` before destination-specific preparation.

Operational state does not contain resolved artistic choices. The completed publication checkpoint is their sole durable authority, as specified in [Selection and Persistence](30-SELECTION_AND_PERSISTENCE.md#authoritative-and-derived-state).

A valid matching presentation checkpoint must be reused without reselecting artistic choices. Changes to resource pools, configuration, or destination overrides do not independently authorize canonical reselection. Recovery after checkpoint loss follows [Recovery and state compatibility](30-SELECTION_AND_PERSISTENCE.md#recovery-and-state-compatibility).

Resolve canonical decoration first:

1. Use the content entry's explicit decoration preference when valid and available, or select from its referenced pool.
2. An explicit `"none"` suppresses decoration.
3. Otherwise, select from the effective default decoration pool, using the automatic `"none"` fallback when no usable candidates remain.

The selected decoration may provide preferred font and background values, role-face preferences, color preferences, and complete literary-inset overrides.

Resolve the canonical font bundle using this precedence:

1. The content entry's font preference.
2. The selected decoration's font preference.
3. The effective default font pool.
4. The unconditional bundled `source-sans-3/regular` recovery font when no other usable font can be resolved.

Resolve one bundle, then resolve its quotation, source, and attribution faces independently according to [Font bundles, role faces and recovery](#font-bundles-role-faces-and-recovery).

Resolve canonical background using this precedence:

1. The content entry's background preference.
2. The selected decoration's preferred background.
3. The effective default background pool.
4. The automatic `"none"` fallback.

An explicit background `"none"` suppresses all lower-priority background selection. A decoration preference of `"none"` suppresses automatic background selection unless the content entry supplies a higher-priority preference.

Each preference level is considered independently. Pool candidates are not merged across levels. An empty explicit pool falls through to the next applicable preference. Automatic fallback does not modify named pool membership.

For a pool with multiple distinct usable candidates, select uniformly at random without replacement when testing candidates for usability. Repeated identifiers and nested references do not increase selection probability.

Invalid or unavailable optional resource preferences must be diagnosed without invalidating otherwise valid selected literary content.

After decoration and background selection, resolve canonical text color using the first level with usable candidates:

1. Content entry `text_color`.
2. Selected background `text_color`.
3. Selected decoration `text_color`.
4. Effective `text.colors.pools` default pool.
5. Built-in `black`.

When the selected decoration contains at least one effectively tintable layer, resolve its canonical decoration color using:

1. Content entry `decoration_color`.
2. Selected background `decoration_color`.
3. Selected decoration `decoration_color`.
4. Effective `decorations.colors.pools` default pool.
5. Built-in `black`.

Text-color and decoration-color pools are independent namespaces. Do not merge their candidates.

The canonical presentation also records the resolved presentation style, QR policy, and applicable design-space presentation configuration. Its fields follow the stage-appropriate [Publication schema](../schemas/PUBLICATION.md#presentation).

The shared presentation checkpoint records destination-independent resolved choices. Output-dependent QR availability is unresolved at this stage: record canonical `presentation.qr.enabled` but omit `presentation.qr.available` until destination preparation. Completed scheduled publication metadata records the actual effective values, including QR availability.

Do not persist destination-specific overrides, raster-layout calculations, output dimensions, fitted font pixel sizes, or rendered pixels in the shared publication checkpoint.

Canonical resolution is performed once for the committed selection while the complete checkpoint remains valid. Destination processing must use independent copies of that checkpoint and must not mutate its persisted artistic choices.

Resource registries, identifier validity, pool membership, and authored preferences are defined in [Assets](../schemas/ASSETS.md), [Application Configuration](../schemas/CONFIGURATION.md), and [Content Entries](../schemas/CONTENT.md).

Tests must verify canonical resource precedence, deterministic randomized selection, empty-pool fallthrough, fallback behavior, persistence across restart, and preservation of valid artistic choices despite subsequent configuration and asset changes.

## Destination overrides

Destinations derive their effective presentations from the persisted canonical presentation.

Apply only the six supported `destinations[].overrides` properties defined in [Application Configuration](../schemas/CONFIGURATION.md#destination-overrides):

- `background: "none"` suppresses the canonical background.
- `decoration: "none"` suppresses the canonical decoration.
- `font` selects exactly one registered font-bundle identifier.
- `text_color` selects exactly one effective palette identifier.
- `decoration_color` selects exactly one effective palette identifier.
- `qr: "none"` suppresses literary QR.

Omitted properties retain their canonical values, except for dependent effective requirements that must be recalculated after decoration suppression or resource recovery.

Overrides do not accept pools, fallback lists, arbitrary resource alternatives, direct RGB values, booleans, nested QR mappings, or unsupported properties. Configuration validation is strict.

Destination font overrides replace the canonical bundle with the registered identifier supplied. They do not trigger random font selection or change the persisted canonical font. Resolve role faces for the effective bundle using the existing role-preference rules.

Suppressing decoration restores global presentation insets. It does not change global quotation font-size bounds.

Suppressing background does not reset literary geometry.

Decoration-color overrides have no rendering effect when no effective decoration layer is tintable.

Destination QR suppression changes only that destination's effective QR policy and availability. It must not modify canonical QR policy or affect another destination.

For each destination, derive and validate the effective presentation before rendering. Record the actual effective values used, including resource fallbacks, suppression, resolved font and faces, colors, insets, font bounds, and QR availability, in its completed publication metadata.

Do not serialize override requests as substitutes for resolved effective presentation values.

Destinations may share prepared images only when their output specifications and effective presentation requirements are compatible. Different effective overrides, including QR suppression, must not incorrectly share pixels.

Tests must cover every supported override, strict rejection of unsupported forms, canonical preservation, effective-value accuracy, decoration suppression, QR reevaluation, and compatible versus incompatible preparation groups.

## Font bundles, role faces and recovery

A content entry may specify a preferred font bundle, inherited by every quotation in that entry. A decoration may specify a preferred font bundle. These preferences participate in canonical selection before destination overrides.

Font selection has no repetition history. The same font may be selected for consecutive daily presentations.

Resolve the canonical bundle according to [Canonical resolution and resource precedence](#canonical-resolution-and-resource-precedence).

For each preference level, try distinct expanded pool candidates in randomized order without replacement. Exhaust that level before proceeding to the next. Explicit registered identifiers are attempted directly.

A usable explicit content-entry or decoration preference does not require a nonempty default font pool.

An empty effective default font pool does not implicitly gain bundled resources, and `@builtin` remains opt-in for normal pool membership. The unconditional emergency font is a separate recovery guarantee, not a member inserted into any pool.

After selecting a bundle, resolve `quotation`, `source`, and `attribution` faces independently.

For each role, use the first defined preference in this order:

1. Content-entry `font_faces`.
2. Selected decoration `font_faces`.
3. Selected bundle manifest `font_faces`.
4. Global `fonts.faces`.
5. Implicit `regular`.

An explicit `regular` is a defined preference and overrides lower-priority values.

If the selected role face cannot be loaded, warn and use the same bundle's usable `regular` face. Do not consult lower-priority role preferences after a winning preference has been selected.

If the selected effective bundle or its required regular face is unusable during ordinary scheduled preparation, attempt recovery using usable bundles from the configured default font pool. If none is usable, use the unconditional packaged `source-sans-3/regular` font.

A runtime font fallback must preserve the persisted canonical font identifier and face choices. Record the actual effective bundle and faces used for the prepared image and completed publication metadata.

Do not replace the canonical choice merely because the original resource has become unavailable.

Fail ordinary font preparation only when no usable font remains after the established recovery sequence.

The packaged `source-sans-3/regular` recovery resource must remain available independently of normal default-pool membership. Missing or unusable emergency font resources are packaging or installation failures and must produce actionable diagnostics.

An explicit viewer override or publication reconstruction request remains strict. It must fail when its required explicitly selected font or face cannot be resolved, rather than silently substituting an unrelated font.

Destination font overrides are strict configuration syntax, but ordinary runtime resource failure after successful configuration acceptance follows the readability-first preparation recovery policy.

Role-face resolution is limited to the quotation, source, and attribution within the selected effective bundle. Do not independently select unrelated bundles for individual roles.

Use Pillow-compatible `.ttf` and `.otf` font resources. File and identifier validation belong to [Font bundles](../schemas/ASSETS.md#font-bundles).

Reuse complete compatible cached images without reloading fonts or checking whether font resources have changed.

When regeneration is required, use persisted canonical artistic choices and current applicable resources. Do not rerandomize canonical font selection unless the authoritative presentation checkpoint has been lost and is being reconstructed under the approved recovery policy.

Do not persist font bytes, filesystem paths, or content digests solely to reproduce pixels.

Do not download fonts during rendering. Verify licenses and redistribution terms for bundled resources.

Automated tests must cover:

- valid and invalid registered font bundles and faces;
- unavailable explicit font preferences;
- empty default pools without mutation of their membership;
- usable content-entry and decoration preferences with empty default pools;
- canonical preference precedence and deterministic randomized pool selection;
- role-face precedence, explicit regular preferences, and fallback without lower-priority lookup;
- distinct quotation, source, and attribution faces within one bundle;
- destination single-font overrides and rejection of pool/list values;
- unavailable selected bundles during ordinary preparation;
- same-bundle regular recovery, default-pool recovery, and unconditional `source-sans-3/regular` recovery;
- failure only when no usable font remains;
- strict explicit viewer and publication reconstruction behavior;
- preservation of canonical font identity after runtime fallback;
- metadata recording the actual effective font and faces;
- consistent font choices across reveal stages;
- reuse of valid caches despite subsequent resource changes;
- regeneration using persisted canonical selections without literary reselection.

Use deterministic random sources and controlled font-loading failures for recovery tests.

## Image spaces and raster geometry

The literary presentation pipeline has exactly three primary image spaces: the design canvas, the presentation canvas, and the output image.

The fixed 3840 × 2400 reference envelope defines the maximum design area. The declared presentation aspect selects the corresponding centered design canvas by reducing only the dimension that exceeds the ratio:

| Aspect ratio | Design canvas | Reference-envelope crop |
|---|---:|---|
| 4:3 | 3200 × 2400 | 320 pixels from each horizontal edge |
| 5:3 | 3840 × 2304 | 48 pixels from each vertical edge |
| 16:9 | 3840 × 2160 | 120 pixels from each vertical edge |
| 16:10 | 3840 × 2400 | None |

The design canvas is the high-resolution, aspect-specific graphical composition and authored-layout space, independent of requested output resolution.

Design-canvas operations include:

- creating the paper-white base;
- background composition;
- decoration-layer composition;
- `contain`, `cover`, `nine-slice`, and `anchor` transformations;
- decoration tinting;
- resolution of configured presentation measurements expressed in design-canvas units.

Configured presentation measurements use design-canvas units unless a field explicitly specifies source-image pixels.

Background and decoration layers share one image-transformation implementation.

For `anchor`, uniformly scale the source according to its selected design-canvas dimension, align its complete scaled rectangle to the declared horizontal and vertical canvas anchors, clip outside the design canvas, and alpha-composite. Scaling preserves aspect ratio and uses deterministic nearest-pixel rounding, with half-pixel values rounded upward. Clipping outside the canvas is normal composition, not a validation failure.

Each configured destination resolves to an output specification containing its declared aspect ratio and requested resolution. Do not infer the declared ratio from requested dimensions.

Every finished rendering output must have integer dimensions satisfying:

- width: 1–3840 pixels;
- height: 1–2400 pixels.

Width and height are validated independently. Portrait, square, and landscape outputs are valid. Requested dimensions need not match the declared aspect ratio mathematically.

Apply these limits to scheduled preparation, viewer inspection and export, and other finished-image rendering or reconstruction operations. Preserve the Waveshare backend's separately fixed 1600 × 1200 requirement.

Validate output dimensions and preflight required image allocations before allocating or decoding large raster buffers. Reject invalid or unsupported finished-image requirements without attempting unbounded allocation.

The presentation-canvas dimensions are derived from the output specification. They do not independently identify prepared artifacts.

When requested dimensions exactly match the declared aspect ratio, the presentation canvas has the requested dimensions.

Otherwise, reduce the declared ratio to integer dimensions `(rw, rh)` and compute:

`k = max(1, round_half_up((rw × requested_width + rh × requested_height) / (rw² + rh²)))`

The presentation canvas is `(rw × k, rh × k)`.

This projected scale and half-up tie break define the nearest exact-ratio raster deterministically.

Scale the completed graphical composition from the design canvas to the presentation canvas as one image.

Scale design-canvas presentation measurements to presentation-canvas coordinates using deterministic nearest-integer rounding, with half-pixel values rounded upward. Map rectangle edges independently; resolve shared boundaries once and assign any rounding remainder to an adjoining region to prevent gaps or overlaps.

Reject non-finite, negative, out-of-bounds, or degenerate geometry before rendering.

The presentation canvas owns:

- literary-region geometry;
- text measurement, fitting, and drawing;
- QR rasterization and composition;
- diagnostic overlays.

If the requested resolution matches the declared aspect, the presentation canvas is also the output image, and no final resize is required.

Otherwise, after all presentation-canvas composition is complete, resize that entire image once to the exact requested dimensions. This may intentionally distort the presentation.

No layout, geometry calculation, text fitting, QR generation, graphical composition, diagnostic annotation, or individual-element scaling occurs after this resize.

Persist the resulting complete output image as the prepared artifact.

Transient diagnostic geometry, including literary bounds, remains expressed in presentation-canvas coordinates. When enabled, diagnostic overlays are rendered on the presentation canvas before any final whole-image resize.

For example:

- A 16:9 output requested at 1920 × 1080 uses a 3840 × 2160 design canvas and a 1920 × 1080 presentation canvas, with no final resize.
- A 4:3 output requested at 1600 × 1190 uses a 3200 × 2400 design canvas and a 1596 × 1197 presentation canvas, followed by one whole-image resize to 1600 × 1190.

The rendering order is:

```text
source assets
    ↓
DESIGN CANVAS
    paper-white base
    background composition
    decoration composition
    authored/configured presentation geometry
    ↓
scale complete graphical composition
scale design-space presentation measurements
    ↓
PRESENTATION CANVAS
    literary-region geometry resolution
    literary fitting and rendering
    QR generation and composition
    diagnostic overlays
    ↓
optional whole-image resize only
    ↓
OUTPUT IMAGE
    persisted/published image
    no further presentation operations
```

For each output specification, resolve QR design-space placement, map its allocation to the presentation canvas, and determine effective QR availability before selecting conditional decoration layers.

Then compose the paper-white base, selected background layers, and eligible decoration layers on the design canvas in their established order.

Scale the graphical composition to the presentation canvas, resolve literary geometry, fit and render the literary fields, composite QR when available, and draw diagnostic overlays.

The output image is then either used unchanged or resized once as a whole.

Every decoration PNG remains behind literary text and QR output. Do not introduce arbitrary z-index values, foreground composition phases, or independent per-element output-space rendering.

Each output specification's geometry and graphical composition remain stable across its reveal stages.

Nine-slice values are source-image pixel distances. Partition the original source directly and preserve the same numerical edge and corner thicknesses on the design canvas. Do not scale slice coordinates through the reference envelope.

For example, 20-pixel slices in a 1920 × 1200 source retain 20-pixel thickness on a 3840 × 2400 design canvas, not 40 pixels.

Use Pillow for raster composition and resampling. Manage decoded images and fonts explicitly, closing temporary resources when their owners are finished.

Avoid unnecessary source-image upscaling and full-canvas copies without weakening rendering correctness or the specified coordinate transformations.

Source background and decoration PNGs may exceed the dimensions of the finished output, but each source image is limited to 36,864,000 decoded pixels.

Inspect source dimensions and enforce the decoded-pixel limit before full decoding or large allocation. Invalid, oversized, or unsafe resources must fail their affected resource or preparation group under the established recovery rules, without invalidating unrelated usable resources.

Tests must distinguish the design canvas, presentation canvas, and output image. Include exact-aspect and mismatched-aspect outputs, portrait and square outputs, minimum and maximum dimensions, and rejection of oversized outputs before allocation.

Specifically test 4:3 at requested 1600 × 1190, asserting design-canvas composition at 3200 × 2400, literary and QR composition at 1596 × 1197, and one final whole-image resize.

Verify deterministic half-up rounding, shared boundaries, invalid geometry rejection, and absence of element-specific operations after the final resize.

## Literary composition and fitting

Literary insets are design-canvas measurements, each measured inward from its corresponding canvas edge for the selected aspect ratio.

Resolve the literary rectangle in design-canvas coordinates, then map its edges to the presentation canvas using deterministic nearest-integer, half-up rounding.

Do not derive literary geometry from aspect-mismatched output-image dimensions.

Global presentation insets and global minimum and maximum quotation font sizes provide the applicable configuration defaults.

A selected decoration may replace the complete global inset mapping with its `presentation_insets`. Decoration manifests do not define quotation font-size bounds.

Suppressing or discarding a decoration restores the global insets. Global quotation font-size bounds remain in effect.

Background suppression does not reset geometry.

Insets are independent of decoration slice coordinates, PNG dimensions, and artwork transformations.

The resulting literary rectangle must have positive width and height and contain the complete literary composition.

The renderer fits and positions text in presentation-canvas coordinates using the effective rectangle and globally configured quotation font-size bounds scaled to that canvas.

The fitting guarantee does not protect literary text from separately composited artwork or QR output. Refrain does not automatically detect or correct those overlaps.

Bundled artwork and defaults must be designed and validated for acceptable composition. Custom decoration and configuration authors remain responsible for their visual results.

The intended appearance is that of a carefully typeset printed page rather than a conventional electronic interface.

The design prioritizes readable typography, generous whitespace, restrained decoration, a predominantly paper-white background, and dark text with optional color accents.

The effective literary rectangle contains the complete quotation and optional source and attribution.

The quotation remains visually dominant. Source and attribution use subordinate typography and form a compact byline beneath the quotation.

When both fields are present, display attribution first, followed by source:

`— Attribution, Source`

The attribution uses a restrained, visually distinct treatment. The source is preferably italicized when an appropriate resolved face is available.

Italic font support or automatic font substitution is not required. The byline must remain legible with the regular resolved face.

When only attribution is present, display `— Attribution`. When only source is present, display `— Source`.

Absent fields do not introduce unnecessary separator punctuation.

The byline is centered beneath the quotation for the `centered` style and right-aligned within the presentation region for the `left-aligned` style.

Unrevealed source and attribution fields retain visibly obscured representations within their final positions, rather than blank space or literal placeholder characters.

Concealment must make the original text illegible while retaining the field's visual footprint and eventual placement.

Suitable implementations include aggressive blurring or dense pixel-level distortion. Use one deterministic treatment appropriate to the target e-paper display rather than a configurable concealment system.

The applicable leading dash and separator punctuation remain visible throughout reveal progression.

Automatic fitting determines text wrapping and font sizes within supported bounds. Every present field must fit within the literary region without overlapping, clipping, truncation, or omission.

Preserve intended quotation text, explicit line breaks, and paragraph structure.

When explicit line breaks are present, prioritize the largest permitted font size that preserves authored lines without additional wrapping while fitting the complete composition.

If those lines cannot fit at the minimum permitted size, automatic word wrapping remains available.

Quotations without explicit line breaks use automatic wrapping and largest-fitting-font behavior.

The supported presentation styles are:

- `centered`: Each quotation line is independently centered horizontally. The quotation block is vertically centered in its allocated space, with the byline centered beneath it.
- `left-aligned`: Quotation lines share a left edge. The resulting quotation block remains horizontally centered according to its widest line, rather than being anchored to the literary region's left edge. The block is vertically centered, and the byline is right-aligned.

The content entry selects the presentation style for all quotations it contains. The default is `centered`.

Additional built-in styles may be added without changing content-selection, persistence, scheduling, or physical display contracts. Do not introduce arbitrary layout scripting, externally supplied styles, a styling plugin interface, or a general-purpose layout framework without a demonstrated requirement.

Use Pillow font metrics and text-measurement facilities.

Measurement must account for actual glyph dimensions, line spacing, authored line breaks, paragraph spacing, source and attribution, role-specific face metrics, the complete effective literary rectangle, and the selected presentation style.

Do not fit text using character counts or average character-width assumptions alone.

The initial fitting mechanism should remain deterministic and straightforward rather than becoming a general-purpose text-layout engine.

Content that cannot fit at the minimum supported font size must produce a meaningful rendering error rather than silently clipping or omitting text.

Tests must cover short and long quotations, explicit lines and paragraphs, all optional metadata combinations, both styles, maximum-size fitting, reduced-size fitting, and unrenderable compositions.

Verify presentation-canvas bounds, byline punctuation, role-face metrics, and correct alignment. Exercise 1080p, 4K-class, portrait, square, mismatched-aspect, and fixed Waveshare outputs within the supported maximum finished dimensions.

Hardware-independent rendering tests do not establish physical display compatibility.

## Stable layout and progressive concealment

Resolve the complete literary composition using the quotation and every present source and attribution field before generating reveal-stage images.

The resolved layout includes the typography, wrapping, positions, spacing, and visual footprints of all fields regardless of their current visibility.

Use each role's resolved font face and metrics. Byline measurement and baseline placement must account for face-specific advances and glyph bounds.

The leading dash and separators use the quotation face, with fixed positions derived from the complete composition.

The complete final byline determines the position and footprint of its individual fields, even when some are unrevealed.

An unrevealed field displays an obscured representation within its final position.

Revealing a field replaces that representation with readable text without changing its position or the surrounding composition.

Previously visible quotation text, byline fields, and punctuation must not move, resize, or reflow when another field becomes visible.

Leading punctuation and applicable separators remain visible throughout progression.

Absent fields require no reserved space, concealment, or separator punctuation.

The selected presentation style remains fixed for the committed selection.

All reveal stages for one output specification and compatible preparation group use identical literary geometry, typography, line wrapping, and field positions.

Different output specifications may have different raster dimensions, fitted font pixel sizes, line wrapping, and mapped geometry.

The concealment treatment must prevent readable text from appearing through insufficient distortion or produce artifacts outside a field's allocated area.

Additional configurable concealment styles are not required.

Presentation styles determine geometry. Image drawing consumes resolved layout geometry rather than independently interpreting style names.

Keep style-specific layout behavior isolated so additional built-in styles do not require changes to selection, persistence, scheduling, or display integration.

If the complete composition cannot fit within its supported presentation region, report a meaningful error. Do not clip, truncate, overlap, or omit required text merely to produce an image.

Tests must verify stable positions, role-specific face metrics, punctuation, concealment, and visibility across every reveal stage and both presentation styles.

## Graphical layers and transformations

All graphical composition occurs on the aspect-specific design canvas over a paper-white base.

Packaged backgrounds contain an ordered, nonempty sequence of PNG layers. Layers are composited in declaration order using normal alpha composition.

Standalone PNG backgrounds remain single centered-cover layers.

Packaged background layers support `contain`, `cover`, `nine-slice`, and `anchor`. Their omitted `method` defaults to `cover`.

Background layers do not have decoration conditions, tintability, or other decoration-specific metadata.

Decorations contain an ordered sequence of PNG layers. Each layer has its source image, optional method, method-specific parameters, optional QR-presence condition, and optional tintability metadata.

The omitted decoration-layer `method` defaults to `contain`.

Backgrounds and decorations must share the same transformation and alpha-composition implementation.

The supported transformation methods are:

- `contain`: Aspect-preservingly scale the source to fit within the design canvas.
- `cover`: Aspect-preservingly scale the source directly to cover the canvas, cropping excess symmetrically around its center.
- `nine-slice`: Partition and adapt an image using explicit source-pixel slice distances.
- `anchor`: Scale according to the declared horizontal or vertical axis, or retain native size, then align to the specified constrained horizontal and vertical canvas anchors.

`cover` does not first scale to the reference envelope and has no arbitrary alignment parameters. Use `anchor` for its supported constrained positioning behavior.

For `nine-slice`, the configured `left`, `right`, `top`, and `bottom` values partition the original source image into nine regions in source-pixel coordinates.

Reject non-integer, negative, overlapping, or out-of-bounds boundaries.

Do not first scale the source or its slice coordinates through the reference envelope.

Preserve source edge and corner thicknesses numerically 1:1 on the design canvas.

Adapt horizontal and vertical edge lengths according to their configured `stretch` or `crop` behavior:

- `stretch` scales an edge segment along its length to fill the destination.
- `crop` retains the edge segment's scale, centers it, and crops equal excess lengths from both ends.

A `crop` destination longer than its available source segment is invalid. Do not stretch or leave gaps as a fallback.

The center region stretches in both dimensions.

Reject design canvases too small for the combined preserved opposing edge thicknesses.

Edge tiling is unsupported.

For example, 20-pixel slices on a 1920 × 1200 source applied to a 3840 × 2400 design canvas preserve four 20 × 20 corners, top and bottom edge destinations of 3800 × 20, left and right edge destinations of 20 × 2360, and a 3800 × 2360 center.

Preserve source alpha through scaling and composition.

Source image dimensions need not match the design canvas or finished output. High-resolution artwork at 3840 × 2400 is preferred for full-canvas layers, but smaller sources may be enlarged at the cost of visual sharpness.

Each source PNG must be a readable, single-frame RGB or RGBA image with positive dimensions and no more than 36,864,000 decoded pixels.

Inspect dimensions and resource safety before full decoding. Do not permit oversized or malformed source images to trigger uncontrolled allocation.

Resource registration validates intrinsic manifest and resource requirements. Preparation validates actual transformations and composition for the requested configured or viewer-selected aspect.

Do not reject a resource solely because it would be unusable for an aspect ratio that is not configured or requested.

Decoration authoring quality requirements for all established aspects are separate from runtime validity.

For an ordinary scheduled presentation, a failure to prepare any eligible layer of the selected decoration invalidates the entire effective decoration composition.

Discard all successfully prepared layers belonging to that failed decoration. Do not publish a partial decoration as though it were complete.

Use the normal no-decoration fallback, including global presentation insets, without changing the global quotation font-size bounds.

Recompute affected effective presentation requirements, including QR readiness and availability, after decoration fallback. Record the actual resulting effective presentation in completed metadata.

Preserve the canonical decoration identifier in the shared publication checkpoint.

Strict viewer or publication reconstruction requests must report unusable explicitly required resources instead of silently applying ordinary recovery.

A failed selected background or background layer uses the paper-white fallback during ordinary preparation. The effective metadata must describe the background actually rendered.

The underlying committed quotation, selection revision, repetition history, and reveal progress remain unchanged by resource failure.

A valid complete prepared cache remains reusable without checking current assets or manifests.

Decorations may contain conditional layers selected according to effective QR availability:

- `always`: Always eligible.
- `qr`: Eligible only when QR is available.
- `no-qr`: Eligible only when QR is unavailable.

These conditions do not change declaration order.

Decoration-wide and per-layer tintability are both considered. A layer is effectively tintable only when both permit tinting.

When tinting is active, apply the single resolved decoration color to each effectively tintable layer, replacing RGB while preserving alpha.

Non-tintable layers retain their authored RGB values.

Background artwork is not tinted by decoration-color preferences.

Keep background composition and decoration composition outside the shared literary renderer. Scale the completed graphical composition to the presentation canvas as one image.

The manifest schemas, field defaults, registration requirements, and shape constraints are owned by [Assets](../schemas/ASSETS.md). Do not duplicate their complete field definitions in the rendering implementation.

Tests must cover:

- ordered background and decoration composition;
- standalone centered-cover backgrounds;
- `contain`, `cover`, `nine-slice`, and `anchor` across background and decoration layers;
- source images larger and smaller than the canvas, odd dimensions, transparency, and deterministic scaling;
- source-pixel slice preservation, exact boundaries, edge stretching, centered edge cropping, and invalid crop destinations;
- every anchor alignment, scaling axis, native-size placement, clipping, and aspect preservation;
- supported configured and viewer-selected aspects without requiring unused-aspect runtime acceptance;
- decoded source-image pixel limits and rejection before full decoding;
- conditional QR/no-QR layers;
- decoration-wide and per-layer tintability, including untinted accents;
- all-or-nothing decoration fallback after any eligible layer fails;
- global-inset restoration without changing font-size bounds;
- recomputation of QR viability after decoration failure;
- preservation of canonical choices and accurate effective metadata;
- strict viewer and publication reconstruction errors;
- cache reuse despite later asset changes.

Do not implement automatic QR/text collision avoidance or alter literary insets to reserve QR space.

## Colors and tinting

Text and decoration colors are resolved as palette identifiers, not embedded RGB values.

Resolve one literary text color using the precedence in [Canonical resolution and resource precedence](#canonical-resolution-and-resource-precedence).

The resulting text color applies consistently to quotation, source, attribution, and associated punctuation across all reveal stages in a preparation group.

If a selected text color becomes unusable during ordinary preparation, use the built-in `black` fallback for readability, with an actionable warning. Preserve the persisted canonical choice.

Decoration-wide and per-layer `tintable` values default to `true`.

A layer is effectively tintable only when both its decoration and the layer permit tinting.

When at least one layer is effectively tintable, resolve one decoration color using:

1. Content-entry `decoration_color`.
2. Selected background `decoration_color`.
3. Selected decoration `decoration_color`.
4. Effective global `decorations.colors.pools` pool.
5. Built-in `black`.

Select uniformly among distinct usable identifiers at the first applicable preference level.

A successful color selection activates tinting; there is no independent tint-activation configuration field.

Apply the color to every effectively tintable layer, replacing RGB while preserving authored alpha, antialiasing, and transparency.

Artwork intended to retain its original RGB must set `tintable: false` at the applicable level.

When no layer is effectively tintable, do not resolve or apply a decoration tint.

If decoration preparation fails and the decoration is discarded, effective decoration tinting is suppressed. Do not apply a decoration color to nonexistent artwork.

Color fallback must not mutate the shared canonical presentation checkpoint. Completed publication metadata records the actual effective palette identifiers or the absence of an effective decoration color.

Strict viewer and publication reconstruction remain subject to their explicit resource-validation requirements.

Tests must verify color precedence, unavailable candidates, pool membership, duplicate-free selection, RGB replacement with alpha preservation, non-tintable layers, failed-decoration recovery, and effective metadata fidelity.

## QR placement and conditional artwork

The presentation-level literary QR policy defaults to enabled and may be disabled. Destination `overrides.qr: "none"` suppresses QR for that destination.

The shared presentation checkpoint persists canonical QR policy without computing output-dependent QR availability. Its `presentation.qr.enabled` records the canonical policy; `presentation.qr.available` remains omitted until destination-specific preparation.

Completed scheduled publication metadata records both effective `qr.enabled` and actual `qr.available`, using the established field meanings.

Resolve QR allocation and placement in design-canvas coordinates, then map the allocation's four edges independently to presentation-canvas coordinates using deterministic nearest-integer, half-up rounding.

The two-phase dependency is:

```text
resolve design-space placement
        ↓
map allocation to presentation canvas
        ↓
evaluate effective QR availability
        ↓
select qr/no-qr conditional decoration layers
        ↓
compose graphical design on design canvas
        ↓
scale complete graphical composition to presentation canvas
        ↓
render literary content
        ↓
rasterize and composite QR
```

Effective QR availability is resolved separately for every output specification before selecting conditional decoration artwork.

QR is available only when:

- the effective policy permits rendering;
- the effective decoration's `qr_ready` value permits QR;
- placement metadata is valid;
- the complete allocation remains within the design canvas;
- the mapped presentation-canvas allocation can contain the complete QR symbol with at least one pixel per module.

Disabled policy, destination suppression, or valid `qr_ready: false` suppress QR without warning.

Invalid placement metadata, conflicting anchors, out-of-bounds allocation, or insufficient presentation-canvas pixels produce an actionable warning and suppress QR for that output specification.

Do not clamp allocation, infer an alternate position, or change the selected decoration solely because QR is unavailable.

If an unusable decoration is discarded during ordinary preparation, reevaluate QR availability using the resulting no-decoration effective presentation. This may change QR readiness or placement behavior. Do not preserve a QR decision computed from the failed decoration.

Conditional `always`, `qr`, and `no-qr` artwork is selected from the final effective QR availability state.

An available literary QR code encodes:

`https://github.com/ControlForgeHQ/refrain`

The payload is independent of the selected quotation, content entry, display date, and reveal stage.

Do not add a configurable QR destination or depend on a deferred companion service.

The literary QR code uses:

- QR version 4;
- error-correction level M;
- UTF-8 byte encoding;
- a complete four-module quiet zone.

The 33 × 33 symbol and eight total quiet-zone modules occupy a fixed 246 × 246 design-canvas pixel allocation.

This allocation is independent of declared aspect, output resolution, decoration, and literary insets. Decorations cannot redefine its dimensions.

A payload that does not fit the selected QR version and correction level produces an actionable preparation error.

A decoration may position the allocation using one horizontal and one vertical method:

- horizontal: `qr_from_left`, `qr_from_right`, or `qr_centered: horizontal`;
- vertical: `qr_from_top`, `qr_from_bottom`, or `qr_centered: vertical`.

Directional offsets are nonnegative design-canvas pixels.

When an axis has no specified method, its default is 20 pixels inward from the right or bottom edge.

`qr_centered` is one scalar value and cannot center both axes.

Positioning fields are mutually exclusive per axis. Malformed or conflicting values suppress QR rather than establishing precedence or silently using defaults.

Centering and bounds validation use the design canvas for the declared aspect.

Use the mapped presentation-canvas allocation as authoritative, including differences caused by independent edge rounding.

Choose the largest fitting QR module size as:

`min(allocation_width, allocation_height) // 41`

If the result is zero, warn and suppress QR.

Otherwise rasterize integer-pixel square modules and the complete quiet zone without antialiasing.

Center the complete QR footprint within its allocation using half-up rounding when unused pixels are odd.

Do not generate, position, resize, or rerasterize QR specifically for the finished output image.

If a final whole-image resize is required, the complete QR is resized and may be distorted only as part of that operation.

Within one output specification, use identical QR placement and pixels across every reveal stage.

Composite QR after literary text.

QR placement does not alter literary insets, reserve additional text space, rearrange quotation layout, or introduce QR/text collision detection.

A complete valid prepared-image cache remains reusable without reevaluating QR placement. Regeneration uses the persisted canonical QR policy and current output geometry without changing committed selection state.

The information view remains independent of literary QR behavior.

The shared quotation renderer must not depend on a content-library entry or committed selection record. Callers supply resolved content and presentation parameters appropriate to their view.

Do not introduce a general-purpose theme engine, rendering plugin system, or externally supplied renderer framework.

Tests must cover:

- default and directional placement;
- independently defaulted axes and single-axis centering;
- conflicts, malformed values, and booleans;
- allocation bounds on all supported design canvases;
- edge rounding and odd centering;
- exact QR version, correction level, encoding, and quiet zone;
- insufficient presentation-canvas raster size;
- policy and decoration-readiness suppression;
- conditional decoration-layer selection before graphical composition;
- QR rasterization after literary rendering;
- destination-specific QR suppression without canonical mutation;
- QR reevaluation after all-or-nothing decoration fallback;
- stable QR results across reveal stages;
- output-dependent availability in completed metadata;
- absence of output-dependent `qr.available` from the shared checkpoint.

Do not implement automatic collision avoidance, modify literary insets to accommodate QR, or introduce new QR configuration fields.

## Complete stage preparation

After successful selection commitment and persistence of the complete presentation checkpoint, prepare the reveal-stage images required by participating destinations.

The caller supplies the committed selection, validated checkpoint, output specifications, effective presentation requirements, and cumulative reveal-stage sequence.

Preparation does not determine reveal times or advance persistent reveal progress.

Group destinations by compatible effective presentation requirements and output specifications, independently of their destination identifiers.

Destinations with identical output specifications and effective presentation requirements may share images. Destinations with incompatible requirements must not share pixels.

For each unique compatible preparation group and output specification, generate a complete ordered reveal-stage set.

Each image represents one cumulative reveal stage and is independently displayable without requiring a previous image to have been presented.

Resolve the fully revealed literary composition once per output specification and reuse its geometry, typography, wrapping, spacing, and field positions for every stage in that set.

Only field visibility changes between stages within the same set.

Different output specifications may have different presentation-canvas dimensions, fitted font sizes, wrapping, QR availability, and raster geometry.

All stages generated together must use consistent preparation-wide artistic choices.

Normal scheduled progression selects existing prepared images and does not rerender at every reveal event.

Missing intermediate reveal events need not be presented sequentially. The currently required later stage may be published directly.

Preparation failures do not invalidate committed literary selection or authorize reselection.

A failure in one preparation group must not invalidate otherwise healthy independent groups.

Persist every complete required stage set as disposable cache data using the independent atomic publication requirements under [Cache identity, publication and regeneration](#cache-identity-publication-and-regeneration).

Do not expose incomplete stage sets as valid cached preparations.

The same rendering facilities must support single fully visible images for views without progressive reveals, including the information view and the no-eligible-content fallback.

Tests must verify complete stage generation, stable layout, independent image usability, compatible group sharing, incompatible override separation, failure isolation, and recovery from missing stage images without literary reselection.

## Cache identity, publication and regeneration

The prepared-image cache is derived output, not authoritative operational state or the authoritative publication checkpoint.

A complete stage set is associated with:

- the committed selection revision;
- the applicable resolved presentation choices;
- compatible effective destination preparation requirements;
- the output specification;
- the ordered reveal-stage sequence;
- its complete images and integrity associations.

Destination identity alone does not partition a preparation group.

Different effective presentation requirements must not share prepared images merely because their output dimensions match.

A changed QR override, decoration suppression, font override, color override, or other effective requirement changes compatibility when it affects rendered pixels.

Do not require a fingerprint of every asset, rendering decision, configuration field, or source file merely to permit cache reuse.

Each output specification and compatible preparation group owns an independently committed complete reveal-stage set.

A failure to prepare or persist one set must not invalidate or remove another healthy compatible set. Do not require a single global transaction spanning all destinations, output specifications, or preparation groups.

For each stage set:

1. Generate every required reveal-stage image and its internal integrity associations.
2. Write the complete proposed set in a unique temporary location.
3. Flush and synchronize the files as supported.
4. Publish the complete set atomically.
5. Make it available for reuse only after the complete set is valid.

An interruption must leave the preceding complete set or no usable set, never a partial collection accepted as complete.

All images in one set must have the expected output dimensions and compatible image mode.

Each prepared image is a complete independently displayable lossless PNG.

Validate image completeness, decoding integrity, output dimensions, stage association, selection association, and compatibility with the required effective presentation.

Missing, damaged, truncated, mismatched, or inconsistent files make the affected set unusable.

Internal cache integrity and association metadata must not invent another public publication-document form. The public [Publication schema](../schemas/PUBLICATION.md#metadata-document-shapes) defines the shared checkpoints and completed publication documents.

Completed scheduled publication metadata is constructed from the committed content, the validated shared presentation checkpoint, and the actual effective choices and output specification associated with the prepared image.

Do not infer resource choices, colors, fonts, QR availability, or geometry from finished pixels.

The completed publication contains one resolved effective presentation, not simultaneous canonical and effective presentation objects or an embedded authored content entry.

Publication-event identity, destination, timestamp, output specification, and destination-filtered actions are populated at finalization. Do not invent completed publication values while preparing the shared checkpoint.

Finalization must not mutate the shared checkpoint, alter cached image pixels, rerandomize canonical choices, or reinterpret the actions.

A valid complete compatible stage set remains reusable throughout ordinary operation and after restart without checking for changes to configuration files, fonts, palette definitions, backgrounds, decorations, or rendering code.

A changed output or effective presentation requirement prevents reuse of an incompatible set but does not invalidate unrelated compatible sets.

If a required set is missing, damaged, incomplete, or incompatible, regenerate only the required complete set using:

- authoritative committed literary content and reveal schedule;
- the valid complete presentation checkpoint;
- current applicable destination overrides;
- current requested output specifications;
- currently available rendering resources.

Regeneration must not reread the original content entry, choose a different quotation, modify repetition history, or regress reveal progress.

If the presentation checkpoint is lost, recover it according to [Recovery and state compatibility](30-SELECTION_AND_PERSISTENCE.md#recovery-and-state-compatibility) before preparing affected images.

Previously cached images must not be considered compatible with newly re-resolved artistic choices solely because their selection revision and dimensions match.

After checkpoint recovery, compatible image sets must correspond to the artistic choices now authoritative for the committed selection.

If the original presentation checkpoint remains valid, reuse its resolved artistic choices across regeneration and destination changes. Current resource availability may require ordinary effective fallbacks without modifying the checkpoint.

Do not guarantee pixel-identical regeneration after resources, renderer behavior, or output requirements have changed.

Preserve healthy prepared sets when regenerating a missing or invalid set. Safely replace an affected set only after its complete replacement is ready.

Cache cleanup must not remove images referenced by active or pending backend operations.

Avoid unnecessary image duplication, recompression, or decoding. The runtime must not keep all prepared images decoded simultaneously.

Keep cache storage separate from user-authored content and bounded against accumulation of obsolete artifacts.

Finished transient images bypass scheduled cache identity and destination artistic overrides. They are published using their supplied pixels and separate completed transient metadata.

Tests must cover:

- independent complete-set atomicity and failure isolation;
- missing, damaged, truncated, or inconsistent images;
- selection, stage, output, and effective-requirement association;
- independent compatible sets for differing output requirements;
- shared pixels for identical geometry and effective presentation;
- separate pixels for differing QR or other effective overrides;
- cache reuse after configuration or asset changes;
- regeneration from a valid completed checkpoint;
- checkpoint loss and new artistic resolution invalidating incompatible old cache associations;
- preservation of healthy sets when another preparation group fails;
- metadata describing actual effective rendered choices;
- absence of duplicate canonical/effective public presentation objects;
- safe cache cleanup while backend operations retain images;
- independence from transient image publication.

## Cache compatibility constraints

Prepared-image compatibility must preserve the committed selection, valid checkpoint artistic identity, effective presentation requirements, output specification, and expected reveal stages.

Do not retain legacy prerelease cache readers, obsolete rendering snapshots, or compatibility branches solely to reproduce old development artifacts.

Do not make normal cache reuse depend on detecting changes to every configuration or asset file.

Do not persist raster geometry, font bytes, source assets, or rendered-image fingerprints in operational state or the shared publication checkpoint solely for exact visual reproduction.

Keep the atomic operational-state commitment and progressive publication checkpoint independent of disposable cache publication.

The implementation must preserve correct associations, detect unusable cache data, safely publish independent complete stage sets, and regenerate affected sets without selection or reveal regression.

The shared presentation checkpoint is the durable artistic authority. Derived effective presentation and cache associations must not be promoted into competing authoritative state.

## Destination visual conversion

Destination artistic overrides are resolved before rendering. They are never applied by post-processing a completed output image.

Hardware-independent destination visual conversion is limited to explicitly supported destination pixel-format or orientation requirements. It must not alter artistic choices or geometrically resize, crop, pad, or otherwise adapt an image without an explicit backend contract.

The conversion operation returns destination-final pixels without mutating the caller's original RGB output image.

`window` and `publish` use identity visual processing.

The Waveshare conversion uses the same shared hardware-independent RGB-to-seven-index palette implementation for runtime publication and viewer inspection/export.

The active seven-index palette order is:

1. Black
2. White
3. Yellow
4. Red
5. Black
6. Blue
7. Green

Preserve the duplicate black entry and its index identity. Do not substitute the vendored driver's commented alternative palette order.

Conversion must be deterministic for identical input pixels and settings.

Quantize each complete RGB image exactly once. The specific dithering algorithm remains an implementation choice; do not introduce different viewer and backend algorithms or independently quantize the same image at multiple stages.

The Waveshare backend receives the resulting palette indices. Its driver may rotate and pack those indices for controller transport but must not requantize or recolor them.

Keep the shared converter independent of vendor driver, GPIO, and SPI dependencies. The viewer must be able to exercise it without physical display hardware.

The fixed Waveshare output geometry is 1600 × 1200. Conversion does not authorize resizing an incorrectly dimensioned image.

Tests must verify:

- deterministic palette conversion;
- correct active palette ordering, including duplicate black;
- unchanged caller-owned RGB pixels;
- one quantization pass;
- identical viewer and backend conversion results;
- transport rotation and packing without a second quantization;
- import and software execution without hardware dependencies;
- rejection of incorrect Waveshare dimensions.

Physical validation must compare representative viewer-processed previews with the supported panel, accounting for differences between monitor colorimetry and physical e-paper pigments.

Hardware-independent conversion tests do not establish physical panel correctness.

## Information-view composition

Refrain provides an information view presenting application identity and selected runtime information in a format consistent with its quotation-based visual design.

The information view contains:

- a curated, application-owned quotation associated with the running release;
- optional source and attribution identifying the quotation's context;
- the Refrain and ControlForge project identity;
- application version and available build or commit information;
- basic platform and Python runtime information;
- configured display backend types;
- an appropriate copyright notice.

The curated quotation is supplied by the application rather than selected from user content.

It remains consistent for a given release and does not participate in daily selection, priority, repetition history, or global selection history.

The same exact curated quotation is used for the no-eligible-content fallback defined in [Startup and daily transitions](40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#no-eligible-content-fallback). That fallback attributes the quotation to `Forge, Refrain Development Team` and uses ordinary fully revealed literary rendering rather than the information-view layout.

The information-view background generator owns branding, runtime information, and other non-literary elements.

The shared literary renderer presents the quotation and optional source and attribution using the normal composition and typography facilities.

The literary composition remains visually primary. The initial design favors approximately 70% literary presentation and 30% supporting information, without enforcing rigid layout proportions.

Branding and runtime information must remain subordinate and must not compromise readability.

The information view uses one application-owned layout.

Runtime information is a snapshot of information available when the view is prepared, not a continuously updated monitoring interface.

Use the installed application version as the primary version identifier. Build or commit information may be included when reliably available without requiring a Git working tree.

Report configured backend types without implying current backend health or publication status.

Optional runtime information must be omitted gracefully when unavailable. Missing diagnostics must not prevent preparation.

Prepare the information view for the required output specifications using consistent presentation-wide choices and output-dependent rendering.

Each destination receives its matching complete image through normal publication facilities.

Use the existing Pillow composition pipeline. Keep view-specific background generation separate from the shared quotation renderer.

Render the information view as one complete fully visible image. Do not create reveal stages, committed selections, repetition records, or daily-selection cache artifacts for it.

Keep runtime-data collection lightweight and tolerant of unavailable platform facilities.

Do not require network connectivity, Git, hardware-specific dependencies, external monitoring services, or unnecessary subprocesses.

Do not include credentials, tokens, private configuration contents, or privileged filesystem information in the rendered view.

Automated tests must cover:

- preparation with unavailable optional build and environment information;
- application-owned quotation independent of the content library;
- absence of selection, repetition-history, reveal-progress, and publication-checkpoint changes;
- correct output specifications and backend-independent image preparation;
- exclusion of sensitive runtime information;
- use of the same exact quotation for the no-eligible-content fallback without using the branded information layout.

Inspect representative information-view images at target resolutions to evaluate typography, branding, information density, and visual hierarchy.

Do not introduce a separate styling framework, plugin interface, interactive control service, or general-purpose diagnostic subsystem.

## Rendering validation

Rendering tests must distinguish literary semantics, resolved artistic choices, effective destination presentation, raster geometry, image integrity, and physical display behavior.

Automated validation should use deterministic random sources, controlled resource registries, fault injection, geometric assertions, and representative image inspection where appropriate.

Visual inspection remains appropriate for typography and layout quality.

Automated image comparisons may be used when they provide stable, meaningful regression coverage.

Do not rely exclusively on exact pixel comparisons for behavior better validated through semantic or geometric assertions.

Test the established rendering pipeline on hardware-independent supported development platforms. Physical Waveshare validation must be separately identified and performed on the supported panel before claiming hardware correctness.

Do not treat temporary failure fallbacks, incompatible cache artifacts, malformed explicit viewer requests, or invalid resource files as successful canonical artistic reselection.

Validate complete stage sets, effective-value metadata, independent failure isolation, bounded image allocations, and preservation of committed literary selection and reveal progress.