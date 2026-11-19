# Presentation and Rendering

## Preparation and renderer interfaces

Daily-image preparation accepts a committed daily selection record and an explicit sequence of cumulative reveal stages.

Preparation resolves or recovers the canonical presentation, derives and validates each destination's effective presentation before rendering, generates the view-specific background, and uses the shared renderer to produce complete images without accessing physical display hardware.

Neither preparation nor the renderer selects content, modifies selection history, or determines application lifecycle policy.

Rendered output must be testable and inspectable without Raspberry Pi display hardware.

Daily-image preparation separates graphical composition from the shared literary renderer. The renderer owns the typography, fitting, positioning, and drawing of the quotation and its optional source and attribution within the resolved literary rectangle. It does not read application configuration, select content or fonts, access selection history, or determine application lifecycle policy.

Pillow is the preferred image-composition library.

The renderer produces standard images independently of physical display hardware.

Display-specific conversion belongs at the boundary between prepared images and the hardware backend when necessary.

Do not allow the renderer to depend directly on Waveshare-specific objects or APIs.

## Canonical resolution and resource precedence

An omitted resource configuration preserves the plain paper-white, undecorated presentation.

For each committed daily selection, resolve the canonical decoration, font, background, colors, presentation style, and QR policy from the selected content's captured preferences and current configuration, then persist those selections. Before rendering each destination, apply only its supported overrides and resolve its effective presentation and output-dependent layout.

For each selected quotation, Refrain resolves the decoration first:

1. If the content entry specifies a pool reference, select one candidate from that expanded pool. Use an available explicit decoration when available.
2. An explicit decoration value of `"none"` suppresses decoration selection.
3. Otherwise, select from the effective default decoration pool, using the automatic `"none"` fallback if that pool has no usable members. The fallback does not change the pool's membership.

The selected decoration may provide preferred font and background values and a complete literary-inset override.

Exactly one font bundle is selected during image preparation using this precedence:

1. If the content entry specifies a pool reference, select one candidate from that expanded pool. Use an available explicit font when usable.
2. Otherwise, resolve and select one candidate from the selected decoration's preferred font pool when usable.
3. Otherwise, select from the effective default font pool.

Background selection follows this precedence:

1. If the content entry specifies a pool reference, select one candidate from that expanded pool. Use an available explicit background when available.
2. An explicit background value of `"none"` suppresses all background selection, including a decoration's preferred background.
3. Otherwise, resolve and select one candidate from the selected decoration's preferred background pool when specified and available.
4. Otherwise, select from the effective default background pool, using the automatic `"none"` fallback if that pool has no usable members. The fallback does not change the pool's membership.

A decoration may explicitly prefer `"none"` as its background. This suppresses automatic background selection unless the content entry supplies its own background preference.

Each preference pool is resolved at its existing precedence level and is never merged into another level.

An empty explicit pool is unavailable and falls through to the next established preference.

When a requested resource is unavailable, Refrain retains an otherwise valid content entry and proceeds to the next applicable preference, with an appropriate diagnostic.

Only after decoration and background selection are known does preparation resolve text and decoration colors. Background preferences therefore cannot affect background selection and do not create a circular selection dependency.

Invalid decoration registrations must not make unrelated fonts, backgrounds, or decorations unavailable.

Each effective background and decoration default pool has equal-probability selection among its distinct members. Neither pool has repetition history or weighting in Version 0.1.

Canonical font, background, decoration, color, presentation-style, and QR-policy selections are resolved once from current configuration and available resources for the committed daily selection, then persisted with that selection. They do not form part of quotation identity or repetition history. Destination overrides and output-dependent layout, placement, and raster decisions remain derived: apply them to the persisted canonical presentation before rendering, and record the actual effective result with its prepared images. Finalization does not reselect or re-resolve either canonical or effective choices.

After selecting the background, Refrain resolves one literary text color using the first level with usable candidates: the content entry's `text_color`, the selected background's `text_color`, the selected decoration's `text_color`, the effective `text.colors.pools` pool, then built-in `black`. Pool references expand in the text-color namespace. Invalid or unavailable identifiers are diagnosed and excluded at each level. Candidates are not combined across levels, and duplicate identifiers do not add selection weight.

When decoration tinting is required, resolve one decoration color using the first level with usable candidates: the content entry's `decoration_color`, the selected background's `decoration_color`, the selected decoration's `decoration_color`, the effective `decorations.colors.pools` pool, then built-in `black`. Pool references expand in the independent decoration-color namespace. Do not resolve a decoration color when no selected decoration layer is effectively tintable. Background color preferences are presentation preferences only; they do not tint background artwork.

The selected text and decoration colors are resolved for the complete preparation. Color selection is independent of quotation identity and repetition history.

The registries, valid identifiers, image requirements, pool configuration, and content-entry overrides are specified in [asset schema](../schemas/ASSETS.md), [resource and pool configuration](../schemas/CONFIGURATION.md#resources-and-named-pools), and [content presentation preferences](../schemas/CONTENT.md#presentation-preferences).

Canonical presentation choices remain unchanged across destinations and restarts; output-specification-dependent geometry and rendering results are resolved independently for each compatible effective-presentation group.

Automated testing should cover:

- explicit background preferences, `"none"` suppression, and unavailable-preference fallback;

## Destination overrides

Destinations may share a prepared output image only when both their output specifications and effective presentation requirements match; overrides are validated and applied before rendering, and backends own neither artistic overrides nor literary composition.

Test destination override validation and resolution, including unsupported properties and types, suppression-only resources, explicit single-font and single-color identifiers, rejection of pools and fallback lists, and `qr: none` rather than a boolean.

Verify that overrides are applied before rendering, do not mutate canonical state, and do not trigger reselection for another destination or after restart.

Cover decoration suppression restoring global insets and font bounds, background suppression retaining decoration geometry, effective-value validation, and prepared metadata describing actual effective values rather than only override requests.

Test destination visual post-processing independently of backend construction.

These tests establish software behavior only, not physical panel validation.

## Font bundles, role faces and recovery

A content entry may specify a preferred font, inherited by every quotation in that entry.

A decoration may also specify a preferred font.

During image preparation, font selection follows this precedence:

1. Resolve the destination's font preference when one is configured. For a pool reference, try its distinct expanded candidates in random order without replacement until one is usable; for a direct preference, try that font.
2. Only if the destination preference has no usable font, resolve the content-entry font preference the same way.
3. Only if those preferences have no usable font, resolve the selected decoration's preferred font pool the same way, or try its direct preference.
4. Otherwise, select from the effective default font pool.

An unavailable bundle preference does not invalidate an otherwise valid content entry or decoration. Refrain reports an appropriate warning for each unavailable candidate and exhausts that preference level before proceeding to the next bundle-selection preference. Lower-priority preferences are not randomly selected before they are reached.

After selecting the bundle, Refrain independently resolves the `quotation`, `source`, and `attribution` faces within that bundle. For each role, the first defined preference wins in this order: content entry, selected decoration, selected bundle manifest, global `fonts.faces`, then implicit `regular`. An explicit `regular` is defined and overrides lower-priority values. If the winning face is unavailable or unusable, that role falls directly to the selected bundle's `regular` face with an actionable warning; lower-priority face preferences are not consulted. No role selects another bundle. Decoration face preferences apply to the selected bundle even when an entry overrides the decoration's bundle preference.

Each distinct font in an expanded preference or effective default pool has equal selection probability when that preference is used. Repeated identifiers, nested references, and shared subpools do not add weight.

Automatic font selection requires at least one usable member in the effective default font pool. An empty pool is not an error when a usable explicit destination, content-entry, or decoration preference applies. If no usable explicit preference applies and the pool is empty, preparation fails with an actionable diagnostic. Refrain must not silently populate the pool with unrelated bundled fonts or use a separate emergency fallback pool; bundled membership is opt-in through `@builtin`.

Canonical font selection is performed once for each committed daily selection, not independently for destinations or variants. Fonts do not have repetition histories, and a font may be used on consecutive days.

Resolve the canonical decoration and font bundle, then resolve all role faces once and persist them with the daily selection. Destination font overrides may select one explicit bundle; preserve each effective font choice across that destination's output images and reveal stages. Do not select fonts independently for an output specification, destination without a font override, or stage.

Reuse a valid complete cached image set without resolving fonts. When regeneration is required, reuse the persisted canonical bundle and faces; apply a configured explicit destination font override where present and resolve its role faces using the precedence and failure behavior above. Do not reselect the canonical bundle from changed pools or resources. Font identifiers and face choices are persisted as canonical selections; font bytes, paths, and content digests are not.

If the selected effective font or a required face cannot be loaded during preparation, report an actionable preparation error. Font failure must not authorize reselection of the canonical font or literary content, or alter reveal progression.

An existing complete prepared image set is reused during ordinary operation even if font files or preferences subsequently change.

Font registration, default-pool validation, and configuration fallback rules are defined in [font bundles](../schemas/ASSETS.md#font-bundles), [pool validity and effective membership](../schemas/CONFIGURATION.md#pool-validity-and-effective-membership), and [configuration validation](../schemas/CONFIGURATION.md#validation-and-compatibility).

Use Pillow-compatible font files for text rendering.

Font identifiers, paths, and validation rules are defined in [font bundles](../schemas/ASSETS.md#font-bundles) and [resource paths](../schemas/ASSETS.md#resource-paths).

Font-selection and fallback behavior are collected under [Font bundles, role faces and recovery](#font-bundles-role-faces-and-recovery).

Use a controlled random source for deterministic testing of canonical automatic font selection.

Select one canonical font bundle using content-entry, decoration, and default-pool precedence, and persist the resolved bundle and faces with the canonical presentation. Resolve each preference only when reached; try distinct candidates from a pool in random order without replacement, exhausting that level before proceeding. Never merge candidates across levels. Then resolve each literary role within the selected bundle using entry, decoration, bundle, global, and implicit-regular preference precedence. A usable explicit content-entry or decoration font does not require a usable default pool. Automatic selection requires a nonempty effective pool; if no usable explicit content-entry or decoration preference applies and that pool is empty, canonical resolution fails with an actionable diagnostic. A destination `overrides.font` replaces the canonical bundle with exactly one validated registered identifier; it must not use a pool, fallback list, or random selection. Resolve role faces for that effective bundle using the existing face-preference rules. An unavailable winning face warns and resolves directly to the selected bundle's regular face; do not inspect lower-priority role preferences or select another bundle.

Do not store font bytes, filesystem paths, or content digests in authoritative daily-selection state. Persist the canonical resolved bundle and face identifiers as stable selections; record both canonical and effective resolved identifiers in the associated preparation metadata using the publication metadata schema. Reuse the persisted canonical choices across restarts and destinations. Finalization must reuse the prepared metadata's captured effective identifiers.

Do not independently select fonts for individual reveal stages.

Reuse a valid complete prepared-image set without resolving fonts, even when a selected face or font file has changed or become unavailable. If regeneration is needed, reuse the persisted canonical font and face selections; apply any explicit destination font override without consulting the canonical selection pools again. Do not use a separate emergency bundled-font pool. Report an actionable preparation error if the selected effective font or required regular face cannot be loaded.

Font errors during regeneration must not change the committed quotation, content identity, reveal schedule, or reveal progression.

Do not distribute third-party font files without verifying their licenses and redistribution terms.

Do not add font downloading. Keep role-specific face resolution limited to quotation, source, and attribution within the single bundle selected for each preparation.

Test font configuration and selection behavior, including:

- valid registered fonts;
- invalid or unreadable registered fonts;
- empty default font pools;
- default identifiers missing from the registry;
- explicit content-entry font preferences;
- a valid explicit content-entry or decoration preference with an empty effective default pool;
- automatic-selection failure when the effective default pool is empty and no usable explicit preference applies;
- application-level `fonts.faces` parsing and invalid-value handling, plus `font_faces` handling in content entries and resource manifests;
- role-face precedence, explicit-regular overrides, unavailable winning-face fallback without lower-level preference lookup, and decoration preferences applied to an entry-selected bundle;
- consistent face resolution across stages generated together and reuse of complete caches despite later typography configuration or asset changes;
- unregistered content-entry fonts and their warnings;
- randomized selection from the default pool;
- absence of resolved font identifiers and face choices from operational state and global history;
- image regeneration using current font preferences and available assets after cache invalidation;
- preference fallback and diagnostics when a requested font is unavailable, without an emergency bundled-font pool;
- consistent font use across every reveal stage prepared together;
- reuse of valid prepared images independently of subsequent font-file changes;
- actionable failure when no usable font resource can be resolved.

Use deterministic random sources where required.

## Image spaces and raster geometry

The literary presentation pipeline has exactly three primary image spaces: the design canvas, the presentation canvas, and the output image. They have distinct responsibilities and coordinate systems.

The fixed 3840 × 2400 reference envelope defines the maximum design area. The declared presentation aspect selects the corresponding centered design canvas by reducing only the dimension that exceeds the ratio:

| Aspect ratio | Design canvas | Reference-envelope crop |
|---|---:|---|
| 4:3 | 3200 × 2400 | 320 pixels from each horizontal edge |
| 5:3 | 3840 × 2304 | 48 pixels from each vertical edge |
| 16:9 | 3840 × 2160 | 120 pixels from each vertical edge |
| 16:10 | 3840 × 2400 | None |

The design canvas is the high-resolution, aspect-specific graphical composition and authored-layout space. It is independent of requested output resolution. Its operations are creation of the paper-white base; background scaling, cropping, and composition; decoration-layer composition, `contain`, `cover`, `nine-slice`, and `anchor` transformations; decoration tinting; and resolution of configured presentation geometry expressed in design-canvas units. Configured measurements use design-canvas units unless a field explicitly describes source-asset pixels.

Background and decoration layers use the same underlying image-transformation implementation. For `anchor`, the source is first uniformly scaled according to the selected design-canvas dimension, then aligned by its complete scaled rectangle to the declared canvas anchor, clipped at the design-canvas boundary, and alpha-composited. Scaling preserves aspect ratio and uses deterministic nearest-pixel rounding with half-pixel values rounded upward; clipping outside the canvas is normal composition, not a validation failure.

Configured destinations resolve to output specifications, each comprising a declared presentation aspect ratio and requested output resolution. Backend-specific configuration and defaults determine these values; do not infer the declared ratio from requested dimensions. Prepared-image identity also distinguishes the destination's effective presentation requirements. The presentation-canvas dimensions are derived from the output specification and do not form part of artifact identity. When requested dimensions exactly match the declared ratio, the presentation canvas has those dimensions. Otherwise, it is the nearest positive integer-pixel resolution that exactly matches the declared ratio, using the existing deterministic nearest-raster and tie-breaking rules.

For a mismatched request, reduce the declared ratio to integer dimensions `(rw, rh)`, then compute `k = max(1, round_half_up((rw × requested_width + rh × requested_height) / (rw² + rh²)))`. The presentation canvas is `(rw × k, rh × k)`. This projected scale and half-up tie break define the nearest exact-ratio raster deterministically.

Scale the completed graphical composition from the design canvas as one image to the presentation canvas. Scale design-canvas presentation measurements into presentation-canvas coordinates using deterministic nearest-integer rounding, with exact half-pixel values rounded upward. Map rectangle edges independently; resolve shared boundaries once and assign any rounding remainder to an adjoining region to prevent gaps or overlaps. Reject non-finite, negative, out-of-bounds, or degenerate geometry before rendering.

When the requested resolution already matches the declared aspect, the presentation canvas is also the output image and no final resize is required. Otherwise, after all presentation-canvas composition is complete, resize that complete image once to the exact requested dimensions. This may intentionally distort the presentation. No layout, geometry resolution, text fitting or rendering, QR generation or composition, graphical composition, diagnostic annotation, or element-specific scaling or positioning occurs after this resize. Persist the resulting output image as the prepared PNG artifact and deliver it unchanged to the appropriate display backend, except for backend-owned hardware pixel-format or orientation conversion explicitly permitted by the backend contract.

Any transient geometry retained for diagnostics, including literary bounds, is expressed in presentation-canvas coordinates and is not authoritative application state. It does not become output-image geometry merely because the resulting PNG is persisted. When enabled for an aspect-mismatched output, draw diagnostic overlays on the presentation canvas before applying the same final whole-image resize as the displayed content.

For example, a declared 16:9 aspect and requested 1920 × 1080 resolution use a 3840 × 2160 design canvas, a 1920 × 1080 presentation canvas, and a 1920 × 1080 output image, with no final resize. A declared 4:3 aspect and requested 1600 × 1190 resolution use a 3200 × 2400 design canvas and the nearest exact 4:3 presentation canvas, 1596 × 1197. Background and decoration composition occurs on the design canvas; the completed graphical composition is scaled to the presentation canvas, where literary, QR, and diagnostic composition occurs before one complete-image resize. The output image is 1600 × 1190. No element is laid out or rendered in 1600 × 1190 coordinates.

Prepare each literary reveal-stage image in this order:

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

For each output specification, resolve design-space QR placement, map its allocation to the presentation canvas, and determine effective QR availability before selecting conditional decoration layers. This decision accounts for the presentation-level QR policy, selected decoration's `qr_ready` value, valid in-bounds placement, and sufficient presentation-canvas pixels for a complete symbol with at least one pixel per module. Then compose the paper-white base, selected background layers, and conditionally active decoration layers on the design canvas, processing each resource's layers in manifest order. Scale the completed graphical composition to the presentation canvas and map presentation measurements there. Resolve literary geometry and font bounds, fit and render the literary fields, then rasterize and composite QR when effectively available; draw diagnostic/debug overlays on the presentation canvas. If requested dimensions differ, resize the completed presentation canvas once as a whole; otherwise use it unchanged as the output image. Persist complete output images for every required reveal stage and output specification, then publish each destination's matching image through the existing backend architecture.

Every decoration PNG is behind all literary text and QR output. This pipeline does not introduce foreground composition phases, arbitrary z-index values, or a general layer-ordering engine. Each output specification's geometry and graphical composition remain stable across its reveal stages. Other views, including the information view, retain their separate composition and QR behavior while observing the same output-specification model.

The declared aspect ratio is distinct from requested output resolution: it selects the design canvas and determines the exact-ratio presentation-canvas dimensions for each output specification.

Graphical composition and configured presentation measurements move from the design canvas to the presentation canvas before all literary, QR, and diagnostic composition; only an optional final whole-image resize to the exact requested dimensions may follow.

Use Pillow for raster composition and resampling. Follow the three image-space responsibilities and pipeline under [Image spaces and raster geometry](#image-spaces-and-raster-geometry); do not introduce a competing rendering sequence. Validate each resolved output specification and dimensions before allocating images. Keep the design canvas, presentation canvas, and requested output-image dimensions distinct. Resolve design-space geometry and scale it to presentation-canvas coordinates with the architecture's deterministic rounding rules. Render literary content, QR, and diagnostics on the presentation canvas; only the completed image may then be resized once as a whole to the requested output dimensions.

Nine-slice values are source-image pixel distances: partition the original source directly with those values and preserve the same numerical edge and corner thicknesses on the design canvas. Do not map source coordinates through the reference envelope. For example, a 1920 × 1200 source with `20 / 20 / 20 / 20` slices used on a 3840 × 2400 design canvas retains 20-pixel thicknesses, not 40-pixel thicknesses.

Avoid unnecessary upscaling of source raster resources and unnecessary full-canvas copies. Manage Pillow image and font resources explicitly, closing decoded or temporary images when their owners are finished with them. Diagnostic tools must follow their documented output-specification behavior and must not mutate committed presentation state or generated daily artifacts.

Include an aspect-mismatched output specification with declared aspect 4:3 and requested resolution 1600 × 1190. Assert that the design canvas is 3200 × 2400 and background/decorative composition occurs there; literary geometry and font fitting, QR viability and rasterization, and diagnostic overlays resolve on the 1596 × 1197 presentation canvas; and only the completed image is resized to the 1600 × 1190 output image. This case must not be replaced by tests where presentation-canvas and output-image dimensions happen to match. Also exercise exact-aspect supported configurations. Verify deterministic half-up rounding and rejection of degenerate geometry.

Verify that backgrounds and decorations are composed on the design canvas, that the completed graphical composition is scaled to the presentation canvas, and that literary text, QR, and diagnostics are composed there. Verify the optional final whole-image resize for both reduction and enlargement, and no resize when requested and presentation dimensions match. Do not require text or QR pixels to remain individually unchanged through that final resize.

## Literary composition and fitting

Literary insets are design-canvas measurements, each measured inward from the corresponding design-canvas edge for the selected aspect ratio. Resolve the literary rectangle in design-canvas coordinates, then map its edges to the presentation canvas using deterministic nearest-integer, half-up rounding. Do not derive literary geometry from aspect-mismatched output-image dimensions.

Global layout insets and global minimum and maximum literary font sizes provide the defaults. A selected decoration may replace the insets and font-size bounds with its complete constraints. When a destination suppresses the canonical decoration, resolve both insets and font-size bounds from the global defaults; do not retain decoration-specific geometry. Background suppression alone does not reset geometry. The resulting rectangle must have positive width and height and contain the complete literary composition. Resolve and scale the effective rectangle for the presentation canvas, then keep it unchanged across that output specification's reveal stages. Scale the effective font-size bounds to presentation-canvas pixels with deterministic nearest-integer, half-up rounding before fitting and rendering. Quotation fitting and wrapping operate only in presentation-canvas coordinates. This fitting guarantee does not protect text from independently composited artwork or QR output. The renderer follows valid configured geometry without guaranteeing an aesthetically successful composite. The default configuration and bundled artwork must be designed and validated to avoid undesirable overlap; custom configuration and decoration authors are responsible for an acceptable composition.

Presentation insets are independent of decoration slice coordinates, PNG dimensions, and artwork transformations. Neither system determines or modifies the other.

The initial release provides one configurable presentation layout.

Its intended appearance is that of a carefully typeset printed page rather than a conventional electronic interface.

The design prioritizes:

- readable typography;
- generous whitespace;
- restrained visual decoration;
- a predominantly paper-white background;
- dark text with optional color accents.

The effective literary rectangle derived from the four presentation insets contains the complete literary composition: the quotation and its optional source and attribution.

The shared quotation renderer determines the arrangement of all present fields within that region.

The quotation remains visually dominant. Source and attribution use subordinate typography and are presented together as a compact byline beneath the quotation.

When both fields are present, the byline presents the attribution first, followed by the source:

`— Attribution, Source`

The attribution uses a restrained, visually distinct text treatment. The source is preferably italicized where an appropriate resolved font variant is available.

Version 0.1 does not require italic font support or automatic font substitution. The byline must remain legible and correctly arranged when only the regular resolved font is available.

When only attribution is present, the byline uses the form `— Attribution`. When only source is present, it uses `— Source`. Absent fields do not introduce unnecessary separator punctuation.

The complete byline is horizontally centered beneath the quotation for the `centered` presentation style and right-aligned within the presentation region for the `left-aligned` style.

Unrevealed source and attribution fields remain visibly represented within the byline rather than leaving blank space or displaying literal placeholder characters.

Their representation must be sufficiently obscured that the original text is not legible, while preserving the visual footprint and placement of the eventual revealed content.

Suitable treatments include aggressive blurring or dense pixel-level distortion. The initial implementation should select a deterministic treatment appropriate to the target e-paper display rather than expose configurable concealment styles.

The byline retains its applicable leading dash and separator punctuation throughout progressive reveal.

Automatic fitting determines suitable text wrapping and font sizes within the supported bounds. All present fields must fit within the presentation region without overlapping, clipping, truncation, or omission.

Presentation insets are design-canvas pixels, measured inward from each edge of the canvas for the declared aspect ratio. Resolve them on the design canvas, then map their edges to the presentation canvas using deterministic nearest-integer, half-up rounding.

Fitting must preserve the quotation's intended text, including explicit line breaks and paragraph structure.

For quotations with explicit line breaks, fitting prioritizes the largest permitted font size that preserves authored lines without additional wrapping while fitting the complete composition. If authored lines cannot fit at the minimum permitted quotation font size, automatic word wrapping remains available. Quotations without explicit line breaks retain automatic wrapping and largest-fitting-font behavior.

The renderer supports named presentation styles that determine how literary content is arranged within the presentation region.

Version 0.1 provides two built-in styles:

- `centered`: Each rendered quotation line is independently centered horizontally. The quotation block is vertically centered within its allocated space, with the byline centered beneath it.
- `left-aligned`: Rendered quotation lines share a common left edge. The resulting text block remains horizontally centered according to its widest rendered line, rather than anchored to the region's left edge, with the quotation block vertically centered within its allocated space and the byline right-aligned.

The selected presentation style is defined at the content-entry level and applies to every quotation in that entry. The default is `centered`.

The rendering design must accommodate additional built-in presentation styles without changes to content-selection policy, persistence mechanisms, reveal scheduling, or physical display integration.

Future styles may control line positioning, spacing, and the arrangement of source and attribution, provided they preserve required content, respect the presentation region, and maintain stable geometry across reveal stages.

The initial release does not require additional styles, arbitrary layout scripting, externally supplied style implementations, or a general-purpose styling framework.

Use the configurable output dimensions, design-canvas pixel presentation insets, and font-size bounds defined in [destination configuration](../schemas/CONFIGURATION.md#destinations), [literary insets](../schemas/CONFIGURATION.md#literary-insets), and [quotation font-size bounds](../schemas/CONFIGURATION.md#quotation-font-size-bounds).

Resolve configured geometry in design-canvas units and map it to the presentation canvas with deterministic rounding. Follow [Image spaces and raster geometry](#image-spaces-and-raster-geometry) for destination-specific output specifications and the optional final whole-image resize.

The shared quotation renderer is responsible for arranging and drawing the quotation and its optional source and attribution within that region.

Layout calculation must account for all present fields before generating any reveal-stage image.

Use Pillow's font metrics and text-measurement facilities to determine suitable font sizes, line wrapping, and placement.

Text measurement must account for:

- actual glyph dimensions;
- line spacing;
- preserved line breaks;
- paragraph spacing;
- the complete effective literary rectangle;
- space occupied by source and attribution;
- the effective presentation style.

Avoid assumptions based solely on character counts or average character widths.

The fitting implementation must satisfy the presentation behavior described under [Literary composition and fitting](#literary-composition-and-fitting).

Prefer a straightforward deterministic fitting procedure over a general-purpose text-layout framework.

Do not hardcode the initial display resolution into unrelated content, selection, or scheduling logic.

Validate each destination's supported aspect-ratio and resolution specification, including aspect-mismatched requests. Exercise 1080p and 4K presentation/output cases without treating hardware-independent results as physical display validation. Verify that preparation produces the Waveshare's fixed 4:3 @ 1600 × 1200 output and that the backend rejects any image with different dimensions rather than resizing, cropping, or padding it.

Do not introduce a general-purpose layout framework or font-selection optimization engine without a demonstrated requirement.

Use representative quotations of different lengths and combinations of optional metadata.

Test automatic text fitting with:

- short quotations;
- long quotations requiring multiple wrapped lines;
- explicit line breaks and paragraphs;
- quotations that fit at the maximum permitted font size;
- quotations requiring a smaller permitted font size;
- quotations that cannot fit at the minimum permitted size.

Verify that all rendered literary content stays within the effective rectangle mapped from design-canvas insets to the presentation canvas.

## Stable layout and progressive concealment

The renderer resolves the complete literary composition using the quotation and every available source and attribution field, regardless of the current reveal stage. Each role uses its preparation's resolved face while the source and attribution remain components of the existing unified byline.

The effective literary rectangle, resolved from the selected decoration's insets or global insets for the complete preparation, remains unchanged across every stage generated together.

The resolved layout establishes the positions, role-specific typography, wrapping, and spacing of all present fields. Byline measurement and baseline placement account for each face's metrics, advances, and glyph bounds. The prefix and separator use the quotation face, with fixed positions determined from the complete composition.

The byline is laid out using its complete final content, including both attribution and source when available, regardless of which fields are currently revealed.

Its punctuation, alignment, and geometry are determined from the complete composition rather than recalculated for each reveal stage.

The complete byline determines the positions and visual footprints of its individual fields.

An unrevealed field displays a visibly obscured representation within its allocated position. Concealment must prevent the original text from being legible while retaining an apparent visual presence comparable to the revealed field.

Revealing a field replaces its obscured representation with readable text without changing the field's allocated position or the surrounding composition.

The leading dash and applicable separator punctuation remain visible throughout the reveal sequence.

Previously visible quotation text, revealed byline fields, and punctuation must not move, resize, or reflow when another field is revealed.

Absent optional fields do not require reserved space, concealment, or separator punctuation.

The selected presentation style remains fixed throughout the committed selection.

Version 0.1 requires a deterministic visual concealment treatment suitable for the target e-paper display. The choice between techniques such as aggressive blurring and dense pixel distortion is an implementation decision informed by rendered-image inspection and hardware validation.

The treatment must not reveal readable text through insufficient distortion or introduce visual artifacts outside the field's allocated area.

Additional configurable concealment styles are not required.

Each output specification's reveal stages use the same resolved composition layout.

Content that cannot be rendered legibly within the supported literary rectangle must be handled explicitly rather than silently clipped, truncated, or omitted.

For each output specification's preparation, resolve the complete literary composition once, including all present source and attribution fields, using the full composition that will be visible across the reveal sequence.

That specification's resulting layout must contain sufficient information to reproduce stable typography and field positions across every reveal stage. Different output specifications may have different raster dimensions, wrapping, fitted font pixel sizes, and mapped geometry.

Presentation styles determine layout geometry. Image drawing uses the resolved geometry rather than independently interpreting style identifiers.

Keep style-specific layout behavior isolated so additional built-in styles can be introduced without changing content-selection policy, persistence mechanisms, scheduling, or display integration.

The initial implementation needs only the `centered` and `left-aligned` styles.

A small internal dispatch mechanism for selecting built-in layout behavior is sufficient. Do not introduce a public styling plugin interface or generalized layout framework without a demonstrated requirement.

All reveal stages within one output specification must use consistent layout geometry.

Reserved space for future reveals must not cause previously visible content to move when additional information becomes visible.

The renderer must not silently clip, truncate, overlap, or omit required text merely to produce an image.

If the complete composition cannot fit within the supported presentation region, report a meaningful error.

Verify that independently selected quotation, source, and attribution faces use their own metrics and remain consistent across all reveal stages. Include both presentation styles, optional-field combinations, mixed-face baselines and punctuation, fitting, clipping, and unchanged geometry during reveal.

## Graphical layers and transformations

Packaged backgrounds contain an ordered, nonempty sequence of PNG layers. Layers are composited over the paper-white base in declaration order using normal alpha composition. A standalone PNG remains a single centered-cover background. Backgrounds and decorations use the same underlying layer transformation and alpha-composition machinery, so `contain`, `cover`, `nine-slice`, and constrained `anchor` alignment cannot diverge by resource type.

Packaged background layers support `contain`, `cover`, `nine-slice`, and `anchor`; `method` is optional and defaults to `cover`. They do not have decoration conditions, tintability, or other decoration metadata. A standalone PNG background is not a packaged layer and continues to use centered `cover`.

A selected decoration may contain an ordered sequence of PNG layers. Each layer has a source image, an optional rendering method, optional parameters for that method, an optional QR-presence condition, and optional tintability metadata. The decoration-layer default remains `contain`. Layers are composed in manifest order on the design canvas. The shared methods are `contain`, which aspect-preservingly scales the image to fit that canvas; `cover`, which aspect-preservingly scales the source directly to cover that canvas and crops excess artwork symmetrically around its center; `nine-slice`, which adapts an image using four explicit source-image pixel distances; and `anchor`, which scales according to a declared axis and aligns to constrained horizontal and vertical canvas anchors. Cover does not first scale artwork to the reference envelope and has no positioning or alignment parameters; use `anchor` for its explicitly constrained alignment behavior. High-resolution artwork at 3840 × 2400 is preferred for full-canvas layers. Smaller custom PNGs may be enlarged by the selected method, but enlargement cannot restore image detail and may reduce visual sharpness.

The complete manifest fields, method parameters, and category-specific defaults are defined in [Decoration manifests](../schemas/ASSETS.md#decoration-manifests) and [Background assets](../schemas/ASSETS.md#background-assets).

For `nine-slice`, the configured `left`, `right`, `top`, and `bottom` distances partition the source image directly into nine regions in its actual source-pixel coordinates. Reject non-integer, negative, overlapping, or out-of-bounds boundaries. Do not first scale the source into the reference envelope or scale its slice boundaries through that envelope. The configured distances are also the preserved edge thicknesses on the design canvas, numerically 1:1, regardless of the source image's overall dimensions.

Preserve corner widths and heights and horizontal- and vertical-edge thicknesses on the design canvas. Adapt only edge lengths according to their configured `stretch` or `crop` behavior; stretch the center region in both dimensions. `stretch` scales an edge segment along its length to fit. `crop` retains the segment's scale, centers it, and crops equally from both ends; it never crops the complete source image. If the requested crop destination is longer than the available source edge segment, reject the transformation instead of stretching it or leaving a gap. Reject a design canvas smaller than the combined opposing preserved edge thicknesses. Edge tiling is not supported.

For example, applying 20-pixel slices to a 1920 × 1200 source on a 3840 × 2400 design canvas preserves four 20 × 20 corners. The top and bottom center regions are 3800 × 20, the left and right center regions are 20 × 2360, and the center is 3800 × 2360. The source center and edge pixels are transformed to fill their destination regions according to the existing stretch/crop policy. Preserve source alpha through scaling and alpha composition.

Background identifiers, registration requirements, and default-pool validation are defined in [Background assets](../schemas/ASSETS.md#background-assets) and [resource pools](../schemas/CONFIGURATION.md#resources-and-named-pools). Selection precedence and recovery behavior are collected under [Canonical resolution and resource precedence](#canonical-resolution-and-resource-precedence) and [Graphical layers and transformations](#graphical-layers-and-transformations).

Discover bundled and user backgrounds from their category directories, using `importlib.resources` for package-owned assets so installed-package operation does not depend on a source checkout. Preserve stable bundled identifiers. Validate images as readable, single-frame PNGs in RGB or RGBA mode, with positive dimensions, without requiring source dimensions to match the configured output. Apply the declared layer transformation on the design canvas and preserve transparency over the paper-white base.

Use a controlled random source for testing equal-probability selection among distinct usable default-pool members. Resolve the background for a complete image-preparation operation, not during selection commitment or independently for reveal stages.

Keep background composition outside the shared quotation renderer. Compose the resolved background over a paper-white base on the design canvas, preserving RGBA transparency. Scale the completed graphical composition to the presentation canvas as specified under [Image spaces and raster geometry](#image-spaces-and-raster-geometry), then reuse preparation-wide results for every stage where appropriate. Use an appropriate high-quality Pillow resampling filter when dimensions differ, retain deterministic geometry, and close decoded resources promptly.

Canonical resolution selects a background from the captured content preferences or effective pool once and persists its stable identifier. Daily-image preparation reuses that canonical choice for all destinations and applies only configured destination suppression; a supplied empty registry represents unavailable resources and applies the documented paper-white fallback without reselecting a different canonical background.

Treat a standalone PNG background as one centered-cover image. For packaged backgrounds, apply each layer's declared transformation; `method` is optional and its category-specific default is `cover`. Support `contain`, `cover`, `nine-slice`, and `anchor` as defined in [Image layers](../schemas/ASSETS.md#image-layers). Do not require centered cover for a packaged layer that declares another valid method.

When preparation cannot resolve or decode an optional background, report a warning and continue with paper-white according to the established fallback policy. Do not change the committed quotation, captured preferences, selection identity, or reveal progression. Keep resource reads bounded and close decoded images when no longer needed.

Decoration identifiers, the initial ordered-layer manifest schema, and preference metadata are defined in [Decoration manifests](../schemas/ASSETS.md#decoration-manifests). Discover bundled and user decorations through their package manifests and `importlib.resources` where appropriate. Validate every referenced image as a readable, single-frame RGB or RGBA PNG with positive dimensions; retain source alpha and do not alter source files.

Resolve canonical presentation-wide choices such as decoration, font, background, palette, and layer preferences once and persist them before destination preparation. Apply restricted destination overrides to derive and validate an effective presentation before rendering; resolve output-specification-dependent insets, transforms, and raster results for each specification as defined under [Image spaces and raster geometry](#image-spaces-and-raster-geometry). When decoration is suppressed, use global presentation insets and font-size bounds rather than its geometry. Decoration-layer `method` is optional and defaults to `contain`; support the manifest methods and parameters in [Decoration manifests](../schemas/ASSETS.md#decoration-manifests), including constrained anchor alignment. Resolve effective QR availability separately for each output specification before selecting its conditional decoration layers. Keep selection outside rendering; compose each resulting graphical design on the design canvas before scaling it to the presentation canvas. Use deterministic scaling, rounding, and alpha composition. Do not infer presentation insets from slice values or image dimensions.

Test `contain`, centered `cover`, nine-slice, and anchor methods directly on the design canvas, including reference-sized artwork, smaller and differently proportioned RGB/RGBA sources, alpha preservation, odd dimensions, clipping/alignment, and matching-size sources that need no transform. Test nine-slice source boundaries, 1:1 preservation of configured source-pixel thicknesses on the design canvas, edge `stretch` and centered `crop`, center stretching, and exact shared boundaries. For example, a 1920 × 1200 source with 20-pixel slices on a 3840 × 2400 design canvas must retain 20-pixel edge/corner thicknesses. Cover invalid boundaries, opposing corners that do not fit the destination, crop destinations longer than their source edge segments, and rounding cases that would otherwise introduce gaps or overlaps. Do not implement edge tiling.

Decoration-wide and per-layer tintability both default to true; test the logical AND, including an untinted accent layer. When any layer is effectively tintable, select one color using the precedence in [Colors and tinting](#colors-and-tinting); a successful selection activates tinting. Preserve each layer's source alpha when applying that single preparation-wide decoration color. Artwork retaining authored RGB must explicitly be non-tintable. Reuse a complete valid set before resolving resources so later manifest or image changes do not invalidate it.

Image preparation accepts the effective decoration registry independently of the background registry. Reuse a complete valid set before resolving image resources, so registry or file changes do not invalidate it.

Automated testing should cover:

- ordered background-layer composition, centered-cover standalone behavior, and shared `contain`, `cover`, `nine-slice`, and `anchor` transformations across background and decoration layers;

Test ordered multi-layer decoration composition, all QR conditions, RGBA transparency, decoration-wide AND per-layer tintability, color-precedence selection and automatic tint activation, the untinted-accent case, consistent composition across reveal stages, and plain output for `"none"`. Verify diagnostics and established resource fallbacks, and that a valid cached set is reused without checking resource changes. Do not test or implement QR/text collision detection or automatic overlap correction.

Test background cover scaling and centered cropping and decoration `contain` scaling for portrait, landscape, matching, smaller, and larger source images, including alpha, odd dimensions, exact output size, and deterministic results. Test anchor scaling in both directions and at native size, aspect-ratio preservation, every horizontal and vertical alignment including center/center, clipping on each and multiple canvas edges, alpha composition, and shared geometry for backgrounds and decorations across 4:3, 5:3, 16:9, and 16:10 canvases. Test nine-slice corners, preservation of resolved corner dimensions across 4:3, 5:3, 16:9, and 16:10 canvases, edge stretching, centered edge cropping, center stretching, source-pixel bounds, destinations too small for preserved corners, crop destinations longer than available source segments, and deterministic rounding without gaps or overlaps.

## Colors and tinting

Decoration-wide and per-layer `tintable` values both default to `true`. A layer is effectively tintable only when `decoration.tintable AND layer.tintable` is true. If at least one layer is effectively tintable, select one decoration color for the complete preparation using the first level with usable candidates:

1. The content entry's `decoration_color`.
2. The selected background's `decoration_color`.
3. The selected decoration's `decoration_color`.
4. The effective global `decorations.colors.pools` pool.
5. The built-in `black` fallback.

Select uniformly among distinct usable identifiers at the first applicable level; do not combine candidates from different levels. A successful color selection activates tinting; there is no separate activation state or configuration field. Apply the selected color to every effectively tintable layer, replacing RGB while preserving authored alpha, including antialiasing and transparency. When no layer is effectively tintable, do not resolve a decoration color. Artwork intended to retain authored RGB must set `tintable: false` at the decoration or layer level.

Automated testing should cover:

- content, background, and decoration text-color and decoration-color preferences, exact precedence, unavailable members, and duplicate-free selection;

Verify that literary text colors are consistent for the quotation, source, attribution, and punctuation across reveal stages generated together, and that the information view's typography is unchanged.

## QR placement and conditional artwork

The presentation-level QR policy defaults to enabled and may be disabled. Resolve the QR allocation and placement in design-canvas coordinates, then map its four edges independently to presentation-canvas coordinates using deterministic nearest-integer, half-up rounding. This is a deliberate two-phase dependency:

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

Effective QR availability is resolved on the presentation canvas for each output specification before selecting conditional decoration artwork. It is true only when the policy is enabled, the selected decoration's `qr_ready` value (default `true`) permits it, placement metadata is valid and the complete allocation remains within the design canvas, and the mapped allocation is large enough for a complete symbol with at least one pixel per module. A valid `qr_ready: false` or disabled policy suppresses QR without a warning. Invalid placement metadata, conflicting anchors, an allocation outside the design canvas, or insufficient presentation-canvas pixels produce an actionable warning and suppress QR for that output specification without excluding the decoration, changing its other metadata, or failing literary preparation. Never fall back to a different position or clamp the allocation. A layer condition of `always` (the default), `qr`, or `no-qr` selects artwork for both states, available-only, or unavailable-only respectively. Conditions do not change layer order. This availability decision selects artwork but does not rasterize or composite QR pixels; that occurs later on the presentation canvas after literary rendering.

For Version 0.1, an available literary QR code encodes `https://github.com/ControlForgeHQ/refrain`, independently of the selected quotation, entry, display date, or reveal stage. Resolve the destination separately from encoding, rasterization, and placement so a future companion experience can change destination resolution without redesigning those operations. Do not add a configurable destination or depend on the deferred companion experience.

Version 0.1 uses QR version 4, error-correction level M, UTF-8 byte encoding, and a complete four-module quiet zone. The 33 × 33 symbol and eight quiet-zone modules occupy a fixed application-level allocation of 246 × 246 design-canvas pixels. This allocation is independent of aspect ratio, output resolution, decoration, and literary insets; decorations cannot redefine its dimensions. A payload that does not fit the selected version and error-correction level produces an actionable preparation error.

Resolve QR payload independently from encoding, rasterization, and placement. A selected decoration may position the complete allocation with one horizontal method (`qr_from_left`, `qr_from_right`, or `qr_centered: horizontal`) and one vertical method (`qr_from_top`, `qr_from_bottom`, or `qr_centered: vertical`). Directional offsets are nonnegative design-canvas pixels. When an axis has no method, its independent default is 20 pixels from the right or bottom edge. `qr_centered` is one scalar value and cannot center both axes. Positioning fields are mutually exclusive per axis; malformed or conflicting values suppress QR instead of selecting a precedence or silently using defaults. Centering and bounds validation use the design canvas for the variant's declared aspect.

Use the mapped presentation-canvas allocation rectangle as authoritative, including any width or height difference caused by independent edge rounding. Choose the largest fitting module size for each output specification as `min(allocation_width, allocation_height) // 41`. If this is zero, warn and suppress QR for that output specification. Otherwise rasterize square integer-pixel modules and the complete quiet zone without antialiasing. Center the complete square footprint inside the allocation using half-up rounding when unused pixels are odd. Do not generate, position, resize, or rerasterize QR specifically for the output image; if a final resize is required, the complete QR is distorted only as part of the complete-image resize. Resolve the same placement and QR pixels across every reveal stage of one output specification.

QR output is composited after literary text. The literary renderer must fit the complete literary composition within the configured literary rectangle, but this does not protect text from independently composited artwork or QR output. QR placement does not change literary insets, rearrange text, or reserve additional space. Refrain does not detect or correct QR/text overlap. A complete valid prepared-image cache remains reusable without reevaluating QR placement; regeneration uses the persisted canonical QR policy and current output geometry without changing committed selection state or reselecting canonical presentation. The information view remains outside literary QR behavior.

The same quotation renderer serves normal daily presentations, the information view, and potential future diagnostic views.

The renderer does not require a content-library entry or committed daily selection record as its input. Callers supply the resolved content and presentation parameters appropriate to the view. It follows valid configured geometry and does not guarantee that independently composited graphical elements do not overlap.

The architecture does not require a general-purpose layout framework, externally supplied rendering components, a theme engine, or a plugin interface.

Follow the two-phase QR dependency under [QR placement and conditional artwork](#qr-placement-and-conditional-artwork): resolve design-space placement, map the allocation to presentation-canvas pixels, and evaluate effective availability before choosing `always`, `qr`, or `no-qr` decoration layers. Availability includes the canonical presentation-level policy unless the destination's `qr: none` override suppresses it, selected-decoration `qr_ready`, valid in-bounds placement, and at least one presentation pixel per QR module. QR suppression is destination-local and must not mutate canonical policy or affect other destinations. Rasterization and composition happen later on the presentation canvas, after literary rendering. Do not decide availability from policy and `qr_ready` alone or make a second decision in the decoration renderer.

Test default and all directional placements, per-axis defaults, single-axis centering, conflicts, malformed values (including booleans), design-canvas bounds failures, edge-rounding and odd centering cases, and the supported canvases. Verify effective availability under each policy/readiness/placement/raster-viability condition before conditional-layer selection, then verify QR rasterization and composition on the presentation canvas after literary rendering. Cover exact Version 0.1 encoding, a complete four-module quiet zone, opaque black-and-white pixels, and consistent placement across reveal stages. Test intentional policy and `qr_ready` suppression without warnings, invalid-placement and insufficient-raster-size suppression with warnings, and preservation of the selected decoration and literary preparation. Do not perform automatic collision avoidance or alter literary insets or artwork to reserve QR space. The information view remains independent of literary QR behavior.

## Complete stage preparation

Preparation resolves the unique output specifications required by configured destinations and generates a complete prepared output image for every required reveal stage and output specification.

Destinations with identical output specifications share the same prepared output images. Prepared images are persisted independently of the content library.

Preparation does not modify the committed selection or its selection histories.

After selection commitment, Refrain prepares all images required by the effective reveal schedule for every required output specification.

Each image represents one cumulative reveal stage for one output specification.

All variants generated together use the same selected content and consistent presentation-wide choices. Raster-dependent layout and rendering results are resolved independently for each variant.

Normal scheduled reveal progression selects existing prepared images. It does not invoke quotation fitting, text fitting, layout calculation, or image rendering.

The renderer is not invoked separately for each reveal event during ordinary operation.

If preparation fails, Refrain retains the committed selection and retries preparation without selecting different content.

Presentation preparation resolves presentation-wide choices consistently and produces every image requested for the committed selection, each required output specification, and every reveal stage. The caller supplies the cumulative stage sequence; preparation does not calculate reveal times or determine the current stage.

Each image represents a cumulative visibility stage for one output specification. The complete fully revealed literary composition determines that specification's stable geometry for every stage. Raster dimensions, wrapping, fitted font pixel sizes, and mapped geometry may differ across specifications.

Within one output specification, all stage images use identical layout geometry, typography, wrapping, and field positions. Only the visibility of fields changes. Across output specifications, selected presentation resources and other presentation-wide choices remain consistent, while presentation-canvas sizes, geometry, wrapping, fitted font pixel sizes, and QR results are resolved independently.

The renderer does not independently recalculate the composition for each reveal stage.

The same preparation facilities may produce a single fully visible image for views that do not require progressive reveals, including the information view.

Every prepared image must be independently displayable without requiring a previous image to have been presented.

Prepared images are persisted as a disposable cache for reuse throughout the current display day and after application restarts.

The preparation process must not expose incomplete images as a valid complete set. Cache metadata must associate complete variants with the current selection, output specifications, and expected stages, and detect incomplete or damaged files. Do not require a fingerprint of all rendering decisions.

Every required reveal-stage image is generated for each unique combination of output specification and effective destination presentation requirements.

For each required output specification, prepare its complete set of reveal-stage images from the durable daily selection and persisted canonical presentation, applying current destination overrides and output requirements. Use that specification's complete fully revealed literary composition to determine geometry for every stage in its set; do not require different specifications to share raster geometry.

Resolve the complete composition layout once per output specification and reuse it for every required cumulative visibility stage of that specification.

Do not require intermediate stages to have been physically displayed before preparing or presenting a later stage.

The same rendering facilities must support preparation of a single fully visible image for views that do not require progressive reveals.

Test image dimensions, supported output formats, presentation styles, field visibility, layout stability, and significant fitting constraints without physical display hardware.

Tests must verify that all present quotation, source, and attribution text remains within the configured presentation-canvas literary region without overlap or clipping.

Automated testing should cover:

- preparation and recovery of reveal-stage images;

## Cache identity, publication and regeneration

After selection commitment, Refrain resolves the canonical presentation once from the captured content preferences, current presentation configuration, and available resources, then persists it independently of destination-specific prepared artifacts. For each destination it derives an effective presentation from that canonical value and the destination's restricted overrides, resolves any required geometry defaults, validates the result, and only then renders. Overrides do not mutate the canonical presentation or cause artistic reselection. Refrain groups destinations with compatible effective requirements independently of their destination IDs and generates every required reveal-stage image for each output specification in each group.

Canonical choices are shared by every destination. Restricted destination overrides are applied after canonical resolution and change only the corresponding effective values; they cannot invoke artistic selection, affect another destination, or mutate the canonical presentation. Omitted properties retain their canonical values, except that suppressing decoration uses the global default insets and font-size bounds. Background suppression does not reset geometry. Within a preparation group, presentation-wide effective choices remain consistent across its output specifications; raster-dependent layout and rendering results are resolved independently for each variant. QR suppression does not change the canonical QR policy or the availability of QR on other destinations.

For each output specification, the prepared images form an ordered reveal-stage set. Images within that set have the same expected output dimensions and compatible image mode; different output specifications may have different dimensions and raster-dependent results.

Prepared images are persisted on disk and associated with the committed selection revision and canonical presentation, compatible effective-presentation requirements, output specifications, ordered reveal stages, and their resolved publication-schema metadata. Destination identity alone does not partition a group; incompatible requirements cannot share a cached image even when output specifications match.

The existing versioned publication-metadata schema belongs to the exact prepared collection and compatible preparation group; it is not a separate prepared-presentation descriptor or rendering snapshot. It records the canonical presentation independently of each prepared destination presentation, whose values describe the effective result actually used for the images rather than only the override requests. Prepared destination metadata records actual resolved resource and palette identifiers, font bundle and role-specific faces, QR inclusion or suppression, effective insets and font-size bounds, and the output specification. Publication-event fields that do not yet exist during preparation remain unassigned or explicitly nullable as that schema specifies; do not invent publication IDs or timestamps.

They are derived artifacts, not independently authoritative application state.

Prepared images must remain associated with the committed selection revision and expected reveal-stage sequence.

Complete compatible collections are reused throughout ordinary operation and after application restart. Changes to configuration or assets do not by themselves invalidate or regenerate them. A change to effective destination overrides changes that destination's requirements and prevents reuse of an incompatible collection, while compatible groups remain reusable. The canonical selection is recovered unchanged and is not reselected when an override changes. This does not make the cache archival: changes to available resources or rendering behavior may change the result when required images are missing or otherwise unusable.

If required variants are absent, damaged, incomplete, or unusable, prepare the complete stage sets needed for the current output specifications from the durable current selection and its persisted canonical presentation, using currently available configuration and assets, then safely publish complete usable artifacts. A changed output requirement may therefore add variants to an existing committed presentation without changing the canonical selections.

All output variants within one compatible preparation group use one consistent set of presentation-wide choices, including selected font identity, background, decoration, and colors. Each variant independently resolves raster-dependent font pixel sizes, line wrapping, geometry, QR viability and module size, and conditional QR/no-QR decoration behavior. Within one output specification, its complete literary composition determines stable geometry for every reveal stage; this does not require different specifications to share geometry.

When output or effective presentation requirements change, any missing compatible variants are prepared from the existing committed selection and canonical presentation without changing the quotation, canonical selections, or reveal progress. Variants within one preparation group share preparation-wide choices. Regeneration may change visual appearance but must not trigger selection, change repetition history, or move reveal progression backward. Finished transient images already prepared for a destination bypass destination presentation overrides.

The runtime must not require all prepared images to remain decoded in memory.

Preparation recovers the persisted canonical presentation, resolving and recording it once only if it was not yet attached to the committed selection. It applies destination overrides and current output specifications to prepare the complete required variant collection. Canonical resource choices remain unchanged across variants and restarts; output-specification-dependent geometry, QR availability, transformations, and other raster-dependent results are resolved separately for each specification. Unavailable or invalid resources follow the documented fallback and diagnostic policies without changing the committed quotation, canonical selections, or reveal progression.

Background source dimensions and aspect ratios are independent of configured output dimensions. Preparation composites packaged background layers in order using their declared `contain`, `cover`, `nine-slice`, or `anchor` methods; the optional method defaults to `cover`. A standalone PNG uses centered `cover`. All layers composite over the paper-white base while preserving source alpha. A missing or invalid packaged-background layer makes that selected background unusable, and normal fallback behavior uses paper-white without changing the committed quotation, captured preferences, selection identity, or reveal progression. Any derived preparation or publication metadata describes the background actually rendered, including the paper-white fallback. Background and decoration slice coordinates and transformations do not determine the literary insets.

A missing or invalid optional visual resource must not invalidate the committed quotation or its reveal progression. Other preparation errors, including malformed required selection data or an unrenderable literary composition, remain errors.

The daily background and decoration system does not alter the independent composition or recovery policies of the information view.

The durable daily selection record, including its canonical presentation, not the image cache, is authoritative. If required variants are missing, damaged, incomplete, or unusable, regenerate the required complete stage sets using the selected content, effective schedule, persisted canonical choices, current destination overrides, output specifications, and currently available assets. Prepare variants coherently with shared canonical selections, and safely publish complete usable artifacts.

Regeneration preserves the selected quotation, content identity, canonical presentation, schedule, selection revision, and highest reached reveal stage. A changed output or override requirement may add variants prepared from this existing committed selection; it must not trigger canonical or quotation reselection or alter reveal progress. Regeneration does not consult the original content library, modify repetition history, or move reveal progression backward. Visual appearance may differ from the prior cache after output, override, or resource changes; exact pixel reproduction is not required.

If image generation fails, the application must report the error and preserve the existing display image where practical.

Complete prepared-variant sets are disposable caches and are reused rather than regenerated at every scheduled reveal.

Missing or unusable variants can be prepared from the committed selection and persisted canonical presentation without reselection, history changes, or reveal regression.

Persist all images required for the current committed selection.

Prepared files must be associated with the current selection revision and expected reveal stages.

Incomplete or invalid image files must not be treated as valid artifacts.

Use a supported image representation that preserves the required output fidelity.

Avoid recompressing, resizing, or converting images unnecessarily during scheduled display updates.

Generated image files should be managed separately from user-authored content.

Do not accumulate unlimited obsolete prepared images during ordinary operation.

The prepared-image cache is derived output, not authoritative state. Associate the complete required variant collection with the committed selection revision and persisted canonical presentation, effective presentation requirements/compatible preparation groups, output specifications, and ordered reveal stages. Cache the resolved preparation metadata alongside its exact image collection using the existing versioned publication-metadata schema. Do not define a separate prepared-presentation descriptor, rendering snapshot type, or intermediate translation schema. The schema fields and preparation-stage validation contract are defined in [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes). Persist stage metadata and image integrity associations in the same complete-set transaction. The preparation metadata records both the canonical presentation and the actual effective destination presentation used to produce the images, including resolved resource and palette identifiers, font bundle and role-specific faces, effective QR inclusion or suppression, and effective insets and font-size bounds. Publication-event fields that do not yet exist remain explicitly nullable as that schema specifies; do not invent publication IDs or timestamps. Every required stage for every output specification and preparation group must be present with valid associated metadata. Each stage is a complete, independently displayable lossless PNG. Files for one output specification must have its exact expected dimensions and a compatible image mode; dimensions may differ between specifications. Validate image/metadata association, collection completeness, and integrity, detecting missing, damaged, truncated, mismatched, or inconsistent files.

Reuse a complete compatible cached collection and its original resolved choices after restart. Do not repeat random resource selection or infer choices from finished pixels to reconstruct metadata for existing images. Missing, damaged, inconsistent, or incompatible metadata makes a reconstruction-capable collection unusable; regenerate the compatible images and metadata together from the committed selection, without changing its identity, history, or reveal progression. The metadata remains disposable derived presentation data.

Associate variants with effective presentation requirements as well as output specification, selection revision, and the persisted canonical presentation. Destinations with different effective overrides must not reuse one another's cached images, even when their output specifications match. Keep matching requirements in a coherent preparation group so that the canonical artistic selections remain shared across that group's output specifications. A change to destination overrides changes effective requirements and cannot change or reselect the canonical presentation. This distinguishes required override inputs without requiring a fingerprint of every resolved rendering decision or every installed asset.

In the current Version 0.1 model, reuse a complete valid set during ordinary operation without checking whether configuration, fonts, palette, or image assets have changed. If the set is absent, incomplete, damaged, or otherwise unusable, use the persisted canonical selections with current destination overrides, output specifications, and available resources to prepare the complete required variant collection together. Resolve canonical selections only if they were not yet durably attached to the committed selection. Publish the replacement safely only after the complete new collection is ready. A replacement may look different from the prior set.

Changes to effective destination overrides change the required variant identity, so an image prepared for different requirements must not be treated as a cache hit. Changes to installed assets or rendering behavior alone do not promise archival reproduction; only missing or invalid required artifacts trigger regeneration. Regenerate a missing or invalid compatible collection's images and metadata together from the persisted canonical presentation, without changing committed selection, canonical selections, or reveal progression. Preserve and reuse other valid preparation groups when only one group is incompatible or incomplete.

Storage writes every PNG and its small association/integrity manifest into a unique temporary directory, flushing and synchronizing each file. Publish the complete prepared set atomically so an interrupted write leaves the previous complete set or no usable cache, never a partial set presented as valid.

Use atomic file replacement and appropriate synchronization where supported. Cache durability need only protect safe reuse and replacement; loss of a cache is recoverable from current operational state.

Remove obsolete cache files without disturbing active readers or the complete set being published. Keep cleanup simple and bounded; artifact retention must not become a second source of application state.

The cache store must not modify authoritative selection state. Cache errors are reported and handled by regeneration from the valid daily selection; they must never authorize reselection or reveal regression.

Distinguish assertions on the design canvas, presentation canvas, and output image. Verify stage completeness and stable layout geometry. All reveal stages for one output specification and preparation group have identical output dimensions. Destinations share prepared images only when both their output specification and effective presentation requirements match. Do not require variants for different output specifications to have identical dimensions. Verify that different effective overrides produce separate prepared variants at identical output specifications, while matching requirements share coherent presentation-wide choices. Verify that the prepared variant set covers each unique output-specification/effective-requirements combination.

## Cache compatibility constraints

Follow-up implementation work must inspect the existing code and remove responsibilities that only support exact-rendering recovery or obsolete unreleased schemas. This includes artifact identities and fingerprints over every visual decision, cache invalidation when settings or assets change, regeneration rules that preserve old destination-specific pixels, special-case compatibility handling for obsolete prerelease configuration fields, legacy state and single-image manifest readers, and tests for historical-schema recovery or pixel-identical regeneration. Do not remove the required canonical artistic selections from authoritative daily-selection state; persist only their stable identifiers and policy, not a destination-specific rendering plan or raster geometry.

Retain the machinery needed to atomically commit selected content and scheduling state, attach canonical artistic selections once without changing selection identity, protect repetition identity and monotonic reveal progress, associate complete image and publication-metadata collections with the right canonical selection, effective preparation group, output specifications, and stages, detect damaged cache data, safely replace a complete set, reuse it during ordinary operation, and regenerate compatible images and metadata together after cache failure. Canonical artistic selections belong in authoritative daily-selection state; effective destination choices belong in derived preparation metadata. Do not introduce a separate rendering snapshot or metadata translation layer.

## Destination visual conversion

Destination presentation overrides are resolved before rendering and never implemented by post-processing a completed output image. The hardware-independent post-processing contract is limited to backend-specific output conversion, returns destination-final pixels without modifying the caller's image, and does not alter artistic presentation choices; `window` and `image-server` use identity processing. The viewer and configured backend publication paths use this same contract. It does not initialize or require a display backend.

## Information-view composition

Refrain provides an information view presenting application identity and selected runtime information in a format consistent with its quotation-based visual design.

The information view contains:

- a curated, application-owned quotation associated with the running release;
- optional source and attribution identifying the quotation's context;
- the Refrain and ControlForge project identity;
- application version and available build or commit information;
- basic platform and Python runtime
- the configured display backend types;
- an appropriate copyright notice.

The curated quotation is supplied by the application rather than selected from the user content library. It remains consistent for a given release and does not participate in daily selection, priority, repetition history, or global selection history.

The information-view background generator owns branding, runtime information, and other non-literary presentation elements.

The shared quotation renderer presents the curated quotation and its optional source and attribution using the same composition and typography facilities as normal daily quotations.

The literary composition remains visually primary. The initial design favors approximately 70% literary presentation and 30% supporting information, without prescribing rigid layout proportions.

Branding and runtime information must remain visually subordinate and must not compromise readability.

The initial information view uses one application-owned layout. Multiple configurable information-view styles are not required.

Runtime information is a snapshot of available information at the time the view is prepared, not a continuously updated monitoring interface.

Version information should identify the running application release. Build or commit information may be included when available without requiring access to a Git checkout at runtime.

Configured display backend types are reported without attempting to represent their current health or publication status.

Optional runtime details must be omitted gracefully when unavailable. Missing diagnostic information must not prevent preparation of the information view.

The information view is prepared for the required output specifications, with consistent presentation-wide choices and raster-specific rendering. Each configured backend receives the matching complete image through the normal publication facilities.

Prepare the information view using the existing Pillow image-composition facilities.

Keep view-specific background composition separate from the shared quotation renderer. The background generator is responsible for project identity, build information, runtime details, and copyright information. The quotation renderer remains responsible for the literary composition.

Supply the information view's curated quotation from application-owned release resources rather than the user content library.

Render the information view as one complete, fully visible image. Do not introduce reveal stages or daily-selection artifacts for this view.

Keep optional runtime-data collection lightweight and tolerant of unavailable platform facilities. Do not require network connectivity, Git, hardware-specific dependencies, or additional background services merely to prepare the view.

Use the installed application version as the primary version identifier. Include build or commit metadata when reliably available without requiring a Git working tree.

Collect basic environment details through appropriate Python or platform facilities. Avoid unnecessary subprocesses, external service calls, broad network enumeration, or repeated system probing.

Do not include credentials, tokens, private configuration contents, or privileged filesystem information in the rendered view.

Include hardware-independent automated tests covering:

- preparation when optional build, network, or environment information is unavailable;
- correct use of application-owned literary content independently of the content library;

Inspect representative information-view images at the target resolution to evaluate typography, branding, information density, and visual hierarchy.

The initial implementation needs one application-owned information-view layout. Do not introduce an independent styling system, plugin interface, interactive control service, or general-purpose diagnostic framework.

## Rendering validation

Visual inspection remains appropriate for typography and layout quality.

Automated image comparisons may be used where they provide stable, meaningful regression coverage.

Do not rely exclusively on exact pixel comparisons for behavior that is better validated through semantic or geometric assertions.
