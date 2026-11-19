# Viewer

## Shared construction and state isolation

Runtime and `refrain-viewer` must use the same presentation-construction, preference-resolution, fallback, geometry, QR-viability, image-composition, preparation, and rendering operations. Keep precedence and fallback rules in that shared machinery; do not implement a separate viewer-side resolver. Represent viewer choices with typed explicit overrides, applied there as the highest-precedence layer only for the corresponding properties. Unspecified properties retain normal Refrain precedence and pool selection.

Normal runtime preparation resolves and persists the canonical presentation once, then applies each destination's restricted configuration overrides in shared preparation before rendering. It supplies no viewer overrides or diagnostic overlays. The viewer's `--debug-layout` option uses the shared presentation diagnostics. Optional viewer quotation font-size bounds are design-canvas measurements resolved with configuration values and scaled to the presentation canvas through the shared configured-bound resolution and fitting path. An alternate `--config` selects the normal configuration layer; it does not elevate that layer above entry or decoration preferences.

For local inspection and export, the viewer selects a validated content entry and one 1-based quotation directly, without eligibility, priority, repetition, scheduling, or selection commitment. Its built-in `@preview` fixture belongs only to the viewer. It resolves one viewer-owned output specification, uses the same design/presentation/output pipeline, and writes or displays the final output image without using configured display backends. In push mode, it instead renders against runtime-discovered destination specifications and may produce multiple unique output variants.

Verify `refrain-viewer --debug-layout` uses the shared presentation diagnostics without enabling overlays in normal runtime or demo preparation.

## Inspection, export and output selection

The installed `refrain-viewer` command owns one-shot presentation inspection and image export. It loads the selected application configuration and content/assets, explicitly selects one entry and one 1-based quotation number, constructs presentation data through the same shared operation as the runtime, and uses the authoritative preparation and rendering pipeline. It does not schedule, select, commit, persist, or reveal progressively.

Viewer-owned transient publication accepts either a fully rendered Refrain presentation or an explicitly supplied finished PNG. Finished-image pixels are authoritative and already downstream of the presentation pipeline: do not pass them through presentation construction, preparation, rendering, or output-geometry transformation. Direct finished-image inspection and publication do not load application configuration, content, assets, or persistence.

Refrain-presentation viewer execution loads no operational state, global history, or prepared artifacts, including configuration-relative or custom storage locations. Its only filesystem output in inspection/export modes is an explicitly requested PNG. The viewer never constructs, initializes, or directly accesses configured backend instances in any mode; push asks the resident runtime to publish completed images. The viewer window is display-only, viewer-owned UI. It may scale only a private desktop copy to fit and must not mutate the rendered output image.

The built-in `@preview` pseudo-entry is viewer-owned fixture content, not part of the content library. It supplies short, medium, and long quotations with source and attribution metadata; the default invocation selects `@preview:2`. A normal entry selector ignores eligibility, priority, and repetition history, and does not change ordinary content-entry identifier syntax.

For local Refrain-presentation inspection and export, the viewer creates one viewer-selected output specification independently of configured display-backend specifications. Its default is 16:10 at the full design-canvas dimensions. `--render-as DESTINATION_ID` instead resolves the identifier in the viewer's effective configuration and uses that destination's output specification. Both follow the established design-canvas → presentation-canvas → requested-output pipeline; `--render-as` then applies the shared destination visual post-processing to the complete output image. `--output` writes the final output PNG. The optional simple viewer window displays that same output and may scale only a private desktop copy to fit; it is not a configured display backend. In push mode, output specifications come exclusively from the selected runtime destinations, and the viewer may render one variant for each unique specification. A finished PNG may instead serve every selected specification only when its dimensions exactly match each requested output size; differing declared presentation aspects do not require distinct finished pixels when requested dimensions match.

Push may use either `refrain-viewer [presentation overrides...] --push TARGET` or `refrain-viewer --image PATH --push TARGET`, where `TARGET` is `@all` or one configured destination ID discovered from the running normal runtime. The literal ID `all` selects only that destination. The viewer treats identifiers as opaque and uses runtime discovery for destination topology and output geometry. Public command syntax and mode conflicts are specified in the [CLI reference](../CLI.md#presentation-viewer). The runtime owns destination geometry; the viewer owns the selected content and presentation choices, overrides, and complete output pixels.

Push requires a running normal Refrain instance. The viewer discovers selected destination specifications without reserving them, then either renders each unique specification using coherent presentation-wide choices or submits the supplied finished pixels unchanged after exact-size validation for every selected destination. It does not contain backend-specific routing or geometry logic. The runtime validates the current destinations, specifications, and exact image dimensions before publication. A changed or unavailable destination is rejected rather than adapted.

Push is synchronous: the viewer identifies the selected destination set and reports visible progress before waiting for potentially slow publication. It remains attached until publication to every selected destination has completed or failed, and returns success only if every selected destination succeeds. A busy request is rejected in full without queuing or partial publication.

Test default and explicit `@preview` selection, exact normal-entry selection, omitted and explicit 1-based quotation numbers, malformed/zero/negative/out-of-range selectors, and independence from eligibility, priority, and repetition. Verify that runtime and viewer use the shared preparation/resolution machinery, normal preference precedence remains unchanged, and each explicit override takes precedence only for its property. Cover strict rejection of unavailable requested resources, ordinary pool resolution for unspecified properties, and QR placement/readiness constraints when QR is forced on.

Cover each aspect's full design-canvas default, exact and mismatched requested resolutions, the one-output-specification design/presentation/output pipeline for local inspection/export, final-image PNG export, and the default-window, PNG-only, window-only, and combined destinations. Mock the local window where necessary and verify desktop fitting does not mutate the output image. For local inspection/export, use sentinel persistence locations and backend factories to verify the viewer never accesses configured backends or runtime persistence. For push, verify it never constructs, initializes, or directly accesses configured backends, but does exercise the resident runtime-control publication path using discovered output specifications. Verify that a destination reported as not supporting transient publication is rejected before rendering, both when selected directly and when included by `--push @all`. Verify that a literal destination ID `all` is routed as a named destination and never treated as the all-participating selector. Do not treat mocked window behavior as graphical-session validation.

Cover identity behavior for `window` and `image-server`, deterministic Waveshare palette/dither sentinels, preservation of the caller's image, configured destination lookup and geometry through `refrain-viewer --render-as`, CLI mode conflicts, and post-processed PNG/window output.

## Strict overrides and local display conversion

Explicit viewer overrides remain strict: an empty or unavailable referenced pool is an error rather than a fallback.

For Waveshare output, the palette-indexed raster is also the viewer's PNG output; make only a private RGB copy when local display needs it.

## Publication reconstruction

`refrain-viewer --publication PATH` accepts a complete publication metadata document directly, for example:

```bash
refrain-viewer --publication publication.json \
  --aspect 16:9 --resolution 3840 2160 --no-qr --output custom.png
```

Parse and validate `refrain-viewer --publication` input with the shared completed-stage publication metadata API. Accept only complete scheduled-publication metadata; reject prepared metadata, null or incomplete publication-envelope fields, transient publications, malformed or unsupported-version documents. A non-null publication ID alone does not establish completion. Never finalize preparation metadata in the viewer. Bound publication metadata input to 16 MiB and turn malformed or deeply nested JSON into an actionable CLI error.

Use the embedded single-quotation content entry and captured effective destination presentation as the rendering baseline. Keep the canonical presentation as separate provenance; do not substitute it for the prepared destination values. Pass published choices through the existing shared preparation machinery and apply typed explicit viewer overrides only to their corresponding values. Otherwise do not rerun content-entry, decoration, or global resource selection. Resolve resource identifiers and font faces only through validated installed configuration registries and the palette; preserve explicit published values and fail on missing or unusable requirements rather than selecting substitutes or falling back to preference pools. Treat embedded content and identifiers as structured rendering inputs, never arbitrary paths, executable instructions, or action payloads.

Render all literary fields fully revealed by default. The shared reconstruction path uses the requested output geometry and renders fully revealed. Recalculate text layout, wrapping, QR viability, and raster geometry through the shared preparation pipeline for each requested output specification. Published insets and font-size bounds remain in design-canvas units unless a supported font-size override is supplied. The source publication's QR availability and output specification do not restrict a new output. Close generated images and decoded resources according to the existing image-ownership rules.

Reconstruction does not load the original content library, access resident runtime or operational state, history, or the prepared-image cache, initialize a backend, or acquire the resident ownership lock. `--config` supplies rendering resources only. Do not infer an audience or original destination; never interpret or execute actions.

Hardware-independent `--publication` tests must construct valid completed scheduled documents using the actual shared preparation, finalization, and serialization APIs: capture metadata from deterministic image preparation, finalize it with a synthetic publication event, destination, audience, and actual output specification, then serialize with the required audience. Use mutated documents only for negative tests; do not hand-author a valid completed schema or introduce a test-only publication backend.

Cover strict shared-schema validation of completed, preparation-stage, transient, incomplete, malformed, unsupported, and unexpected-field inputs; transient rejection; reconstruction from committed metadata independently of the content library and runtime state; resolved-choice, resource and font-face preservation; strict missing-resource failures; explicit override precedence; fully revealed rendering; requested geometry, export and window behavior; QR re-evaluation; and absence of content-library, resident-state, cache, backend, and action access. Verify `--publication` conflicts with `--entry`, `--image`, `--push`, `--render-as`, and `--list-destinations`.

End-to-end resident publication tests must additionally verify the current manifest and hashes, destination-specific audiences and reveal stages, reconstruction without the content library, and rendering at both the original and a different supported geometry.

## Resident push workflow

An external preview contains complete output images rendered by the submitting viewer. The viewer remains authoritative for its pixels, using its own selected configuration, content, assets, and presentation overrides. The runtime does not reconstruct the preview from content or semantic presentation parameters. A viewer first discovers destination output specifications, renders one complete image variant for each unique specification, then submits those images and the specifications against which they were rendered. Presentation-wide choices remain coherent across variants generated together. Variants for identical specifications may share one image and transfer.

Hardware-independent tests using fake backends and controlled synchronization cover:

- generic viewer routing without backend-type conditionals.
