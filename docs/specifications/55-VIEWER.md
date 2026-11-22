# Viewer

## Shared construction and state isolation

`refrain-viewer` provides one-shot literary presentation inspection, image export, completed-publication reconstruction, finished-image inspection, destination discovery, and transient publication through the resident runtime.

Runtime and viewer presentation generation must use the same content interpretation, artistic preference resolution, fallback, output geometry, QR viability, graphical composition, literary fitting, and rendering operations. Do not implement independent viewer-side selection or rendering rules.

Viewer-owned presentation choices are typed explicit overrides. Each supplied override has highest precedence for its corresponding property only. Unspecified properties retain normal preference-resolution behavior.

Viewer preparation resolves artistic choices transiently. It does not commit a daily selection or persist a publication checkpoint.

Normal runtime preparation instead recovers or persists the committed selection's destination-independent presentation checkpoint before applying destination overrides. The viewer must not mutate that checkpoint.

An alternate `--config` selects the viewer's normal configuration layer. It does not elevate that configuration above content-entry or decoration preferences.

For local presentation inspection and export, the viewer selects one content entry and quotation directly without eligibility, priority, repetition-history, or daily-selection commitment.

The built-in `@preview` pseudo-entry is viewer-owned fixture content, not part of the effective content library.

The viewer does not read or modify operational state, global history, publication checkpoints, prepared-image caches, or other resident persistence locations. This restriction includes custom and configuration-relative storage locations.

Viewer presentation generation may read the selected configuration, content library, and rendering assets. Finished-image input and destination discovery do not require them.

The viewer never constructs, initializes, closes, or directly accesses a configured display backend in any mode.

Its local window is viewer-owned, display-only UI. It may fit a private image copy to the desktop without modifying the complete rendered or supplied output image.

Transient publication is submitted through the authenticated local resident runtime-control interface. The running normal Refrain process owns backend access and publication.

The viewer must not acquire resident ownership, establish a competing runtime, or modify normal scheduling, repetition history, committed literary content, reveal progression, prepared-image artifacts, or publication checkpoints.

## Inspection, export and output selection

The installed `refrain-viewer` command owns one-shot presentation inspection and image export.

The default invocation selects `@preview:2`, the medium built-in preview quotation, and displays its fully revealed presentation in a simple local window.

The `@preview` fixture provides short, medium, and long quotations with source and attribution. Explicit `--entry @preview` selects quotation 1. Without `--entry`, quotation 2 is selected.

A normal entry selector uses an entry identifier and optional 1-based quotation number. If omitted, the number defaults to 1.

Invalid entry identifiers, malformed selectors, and zero, negative, or out-of-range quotation numbers are errors.

Explicit viewer selection ignores normal eligibility, priority, repetition history, and daily scheduling. It must not create synthetic operational selection records.

### Local output specification

Local presentation inspection and export use one viewer-owned output specification, independently of configured backend output specifications.

The default aspect ratio is `16:10`, with requested dimensions equal to that aspect's full design canvas.

Ordinary local presentation rendering uses the `private` audience unless `--audience` selects `public`. The selected audience determines the effective QR payload.

`--render-as` uses the named destination's configured audience and cannot be combined with an explicit `--audience`.

Explicit `--aspect` and `--resolution` values select the viewer's output specification. They use the normal design-canvas, presentation-canvas, and output-image pipeline in [Image spaces and raster geometry](50-PRESENTATION_AND_RENDERING.md#image-spaces-and-raster-geometry).

Validate the actual requested output specification before allocating an image. Do not reject a viewer request merely because an unused supported aspect would make a decoration's insets or transformation invalid.

Viewer preparation validates the selected aspect and all resources actually needed for its composition.

`--render-as DESTINATION_ID` resolves the named destination from the viewer's effective configuration and uses its declared aspect ratio and requested resolution.

It also applies the destination's defined hardware-independent visual conversion to the completed output image.

`--render-as` is local inspection or export. It does not publish to that destination or require a running resident.

Destination identifiers are resolved exactly; do not infer backend types or output specifications from identifier spelling.

Use the shared destination visual-conversion implementation, including identity conversion for destinations that require no special pixel processing and the shared Waveshare conversion for its fixed panel format.

A configured `publish` destination uses identity visual conversion; it does not require a filesystem publication operation merely to inspect its rendered pixels.

The `--render-as` option selects destination geometry and visual conversion. It does not silently turn viewer inspection into a configured destination publication or grant access to resident backend instances.

`--output PATH` writes the complete final PNG. It does not open a viewer window unless `--window` is also requested.

Without `--output`, ordinary local inspection opens the viewer window by default.

The viewer window may resize only a separate display copy. It must preserve the original rendered output and must not change exported pixels.

For Waveshare visual conversion, export the palette-indexed PNG produced by the shared converter. Create a private RGB copy only when needed for local-window display.

The `--debug-layout` option uses shared presentation diagnostics. Diagnostic overlays are applied on the presentation canvas before any final whole-image resize.

Viewer diagnostics must not enable overlays in normal runtime presentation or alter persisted presentation state.

### Explicit reveal-stage inspection

`--reveal-stage N` selects a zero-based cumulative reveal stage for local one-shot rendering of an explicitly selected quotation.

The option requires explicit `--entry` selection, including an explicitly selected `@preview` quotation. It does not replace normal selection, scheduling, or reveal progression.

When omitted, local viewer rendering presents every available literary field fully revealed.

For explicit reveal-stage inspection, determine the current host-local logical display date once at invocation using the effective configuration's `scheduling.day_start` and the established civil-time rules. Resolve the selected quotation's effective reveal schedule for that date using the shared canonical cumulative reveal-stage rules. Do not consult resident operational state or persist the resulting sequence.

The first stage has index 0. Fields sharing the same resolved reveal instant appear in one stage; absent optional fields create no stages.

A requested stage index must be an integer from 0 through 2, inclusive. Negative values, booleans, malformed values, and indexes greater than 2 are errors.

If a valid requested index exceeds the final stage available in the resolved sequence for the selected quotation and logical display date, emit a warning identifying the requested and final available indexes, then render the final available stage. Do not treat an unavailable but otherwise valid stage index as an error.

The requested stage controls only the visibility of fields in the one locally rendered image. Its layout must use the complete literary composition, preserving final field positions and concealment behavior.

Do not persist viewer reveal-stage selection, commit operational reveal progression, modify publication checkpoint visibility, create selection history, or publish intermediate stages automatically.

`--reveal-stage` is permitted with local presentation inspection, `--output`, and `--render-as`.

It is not a resident scheduling mode and cannot be combined with `--publication`, `--image`, `--push`, or standalone destination discovery.

### Finished-image input

`--image PATH` accepts an already completed, single-frame, 8-bit RGB PNG for local inspection or transient publication.

The supplied image is authoritative finished pixels, downstream of all Refrain presentation construction.

Do not apply literary preparation, resource selection, presentation overrides, graphical composition, QR generation, layout calculation, resizing, cropping, padding, color-mode conversion, or destination artistic overrides to it.

Finished-image input does not load application configuration, content, rendering assets, operational state, or prepared artifacts.

Validate the PNG signature, structure, format, mode, dimensions, and image integrity before use.

Its dimensions must satisfy the finished-image limits: width 1–3840 and height 1–2400 pixels.

Inspect encoded metadata and dimensions before full decoding where possible. Reject unsafe or oversized images without unbounded memory allocation or decompression.

The local viewer may create a private resized copy solely for desktop display. The supplied image and its original pixels remain unchanged.

A finished PNG may be transiently published to multiple selected destinations only when its exact dimensions match every destination's requested output dimensions.

Different declared presentation aspects do not require different finished pixels when their requested dimensions are identical.

Do not infer a declared presentation aspect from an externally supplied PNG.

`--image` cannot be combined with presentation-generation controls, local output geometry, `--render-as`, `--output`, `--publication`, or standalone destination discovery.

Local `--window` inspection is allowed, but `--window` cannot be combined with transient `--push`.

### Resource and state isolation

Local Refrain-presentation generation uses the selected configuration, its valid content and asset registries, and the shared rendering pipeline.

Explicit viewer requests remain strict. An unavailable explicitly selected resource or empty explicitly selected pool must fail rather than silently fall through to another preference level.

Unspecified choices follow the ordinary preference precedence and applicable recovery behavior.

Do not use production persistence paths as temporary viewer storage. Temporary viewer rendering data must be independently owned and cleaned up without changing runtime state or artifacts.

Tests must cover:

- default and explicit `@preview` behavior;
- exact entry and 1-based quotation selection;
- malformed, missing, and out-of-range selectors;
- independence from eligibility, priority, and repetition history;
- explicit zero-based `--reveal-stage` selection, cumulative visibility, simultaneous reveals, and invalid indexes;
- fully revealed default behavior and unchanged field geometry across reveal stages;
- local output defaults, all supported aspects, portrait and square outputs, and mismatched requested resolutions;
- maximum output dimensions and preallocation rejection;
- `--render-as` configured destination lookup, exact geometry, and visual conversion;
- local PNG export, default window behavior, and private desktop fitting;
- `--debug-layout` without mutation of output or persistent runtime state;
- finished RGB PNG validation, safe decoding, and unchanged source pixels;
- strict explicit overrides and ordinary precedence for unspecified values;
- absence of backend construction, resident ownership, operational-state access, and persistence changes.

## Strict overrides and local display conversion

Explicit viewer presentation overrides are strict and apply only to their corresponding artistic or fitting property.

A directly selected identifier must be valid and usable. An explicit pool reference must contain at least one selectable candidate. Invalid, empty, or unavailable explicit requests produce actionable errors rather than silently selecting a lower-priority resource.

Explicit quotation, source, and attribution face overrides must resolve to usable faces in the selected effective font bundle.

An explicit `--font` override may select a registered font bundle or supported named font pool. This viewer behavior is distinct from the restricted single-identifier `destinations[].overrides.font` configuration contract.

Explicit background and decoration `"none"` values suppress those resources.

`--qr-public` and `--qr-private` independently override the corresponding audience's QR payload. The literal `none` suppresses that audience's payload. Explicit invalid payloads are errors.

`--no-qr` suppresses QR unconditionally and cannot be combined with either payload override. The viewer applies the shared [QR payload resolution](20-CONTENT_AND_CONFIGURATION.md#qr-payload-resolution) and [rendering rules](50-PRESENTATION_AND_RENDERING.md#qr-placement-and-conditional-artwork).

Supported minimum and maximum quotation font-size overrides are design-canvas measurements. Each supplied bound overrides only that bound. The resulting effective minimum must not exceed the maximum.

Global quotation font-size bounds remain in effect when decoration is suppressed. Do not infer decoration-specific font-size bounds from artwork or asset metadata.

Viewer presentation overrides are processed by the shared preparation machinery and must not be implemented through post-processing of completed pixels.

Destination visual conversion is a separate operation performed after the complete presentation image has been rendered.

The viewer and runtime must use the same deterministic Waveshare RGB-to-seven-index conversion, including the active palette's duplicate black index and the same selected dithering behavior.

Quantize the image exactly once. Do not perform a second palette conversion in the viewer, backend, or vendor driver.

The converter must not mutate the caller-owned RGB image or require vendor driver, GPIO, or SPI dependencies merely to inspect or export a converted preview.

Hardware-independent tests must compare viewer and backend conversion output using deterministic image sentinels.

Viewer-exported processed previews should be compared with representative physical panel output during separate hardware validation. Monitor colorimetry does not establish physical e-paper pigment correctness.

## Publication reconstruction

`refrain-viewer --publication PATH` reconstructs a presentation from an existing completed scheduled-publication metadata document.

Accept only the completed scheduled form defined by [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes), with `publication.type: "scheduled"`.

Reject content-only checkpoints, content-and-presentation checkpoints, transient publications, incomplete or malformed documents, unsupported schema versions, unexpected fields, and structurally invalid metadata.

The presence of a publication identifier alone does not prove that the document is a completed scheduled publication.

Use the shared metadata parser and validator. The maximum input file size is 16 MiB.

Reject malformed, oversized, or excessively nested JSON with actionable CLI errors. Do not attempt to repair or finalize metadata received for reconstruction.

The document's `content` section supplies the complete quotation, optional source and attribution, and associated visibility and scheduling metadata.

The document's single `presentation` section supplies the resolved effective artistic choices used by the published destination.

The completed `publication` section supplies the publication event and original output specification, but does not constrain the viewer to that original geometry.

Do not require or reconstruct an embedded content entry, authored preference pools, or simultaneous canonical and effective presentation objects.

Use the published resolved choices directly as the rendering baseline.

Do not rerun content-entry, decoration, or global artistic resource selection for choices already recorded in the publication.

Load required resources only through the validated installed registries and effective palette selected by `--config` or its normal default.

Treat identifiers as resource references, never as arbitrary filesystem paths or executable instructions.

If a required published resource, font bundle, font face, or palette identifier is unavailable or unusable, reconstruction fails with an actionable error. Do not substitute unrelated resources, rerandomize choices, or silently fall back to preference pools.

Explicit viewer overrides remain available and replace only their corresponding published choices.

Unspecified properties retain the published values.

When an explicit decoration override introduces effectively tintable layers and the published `presentation.colors.decoration` is null, reconstruction requires an explicit usable `--tint` override. Otherwise, fail with an actionable diagnostic. Do not resolve a new tint through content, decoration, or global preference pools.

When the selected decoration has no effectively tintable layers, no tint is required.

The viewer does not infer the original destination's audience or apply its destination configuration. Actions are validated as metadata but are never interpreted, executed, or used to select rendering behavior.

The original publication's `content.reveal_stage` records visibility at its publication event. By default, reconstruction renders all available literary fields fully revealed; it does not replay the original reveal sequence or modify that recorded event.

Completed `content.qr` supplies the reconstruction QR payload, if present. Preserve its recorded visibility without inferring a destination audience or resolving payloads from current configuration or content entries.

Reevaluate QR rendering viability for the requested output and effective decoration. An empty published QR array must not acquire a payload during reconstruction.

Resolve layout, wrapping, font fitting, graphical transformations, QR placement, and raster-dependent geometry using the shared presentation pipeline.

Published insets and quotation font-size bounds remain design-canvas measurements unless explicitly overridden by supported viewer controls.

`--no-qr` may suppress the published QR payload. `--audience`, `--qr-public`, and `--qr-private` are invalid in publication-reconstruction mode.

`--publication` may be combined with supported local aspect, resolution, output, window, debug, and artistic override controls.

It cannot be combined with `--entry`, `--reveal-stage`, `--image`, `--push`, `--render-as`, or standalone destination discovery.

Reconstruction must obey the same finished-image dimension limits and source-image decoding safeguards as ordinary viewer preparation.

It does not load the original content library or access resident runtime, operational state, repetition or global history, publication checkpoints, or prepared-image caches.

It does not initialize backends or acquire resident ownership.

Close decoded resources and generated images using the shared image-ownership rules.

### Reconstruction validation

Hardware-independent reconstruction tests must use valid completed scheduled metadata produced through the actual shared preparation, publication-finalization, and serialization APIs.

Construct a valid published example by preparing a deterministic presentation, applying a synthetic destination and audience, finalizing a real publication event, and serializing its completed metadata.

Do not hand-author a separate supposedly valid publication schema solely for tests, or create a test-only publication backend.

Use mutations of valid produced documents for negative tests.

Tests must cover:

- accepted completed scheduled publications;
- rejected checkpoint, transient, incomplete, malformed, and unsupported-version documents;
- strict schema validation and bounded JSON input;
- reconstruction independently of the original content library and runtime state;
- preservation of published literary content and effective artistic choices;
- strict unavailable-resource, font, and face failures;
- explicit viewer override precedence;
- fully revealed default presentation;
- changed output geometry and output-size limits;
- QR viability reevaluation;
- reconstruction from recorded QR content without audience inference or current payload defaults;
- suppression of published QR content and rejection of audience or payload overrides;
- local PNG export and window display;
- rejection of incompatible CLI modes;
- absence of action execution, audience inference, backend access, and persistent-state mutation.

Filesystem publication integration tests must also verify reconstruction from a genuinely published, integrity-validated dataset, using its current manifest and completed scheduled metadata.

## Resident push workflow

The viewer submits transient complete-image publication requests through the already-running normal Refrain process.

The viewer accepts `--all-day` only with `--push` and transmits the requested hold behavior as part of the transient request. This option is valid for both generated Refrain presentations and finished-image input. The viewer does not maintain destination holds, persist their lifetime, or retain published images after completion. The resident owns hold establishment, expiration, clearing, and scheduled-publication suppression as defined in [All-day transient holds](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#all-day-transient-holds).

It does not access resident backends, construct backend-specific transport operations, or modify the normal desired scheduled presentation.

The resident runtime is authoritative for configured destination identifiers, audiences, participation, withdrawal, transient-publication capability, declared output aspects, and requested resolutions.

The viewer discovers the required destination specifications before rendering or submitting an image.

A destination identifier is an opaque routing value. Do not infer backend type, hardware, transport, capabilities, or geometry from its spelling.

Push target syntax and user-facing selection behavior are defined in [Push to configured destinations](../CLI.md#push-to-configured-destinations). Resident target-selection semantics are defined in [Transient target selection](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#transient-target-selection).

### Discovery and preflight

Destination discovery does not reserve destinations or guarantee that they remain unchanged before publication.

Before rendering, validate the discovered destination set and all properties that can be checked locally:

- the requested destination exists;
- each selected destination is participating and not intentionally withdrawn;
- every selected destination supports transient publication;
- the number of selected destinations and required image variants is within the transport limits;
- all requested output dimensions are valid and within the finished-image limits;
- required variants can be generated without unsupported or oversized output requirements;
- the selected mode can provide an exact-size image to every target.

A directly selected destination lacking transient capability is rejected before rendering.

If `@all` includes any participating destination lacking transient capability, reject the entire request before rendering. Do not silently omit it.

For finished-image input, reject the complete request if the supplied PNG dimensions differ from any selected destination's requested dimensions.

For Refrain-presentation push, select each destination's QR payload using its discovered audience before rendering. Group destinations by compatible output specifications and effective rendering requirements, including QR content, as defined in [Cache identity, publication and regeneration](50-PRESENTATION_AND_RENDERING.md#cache-identity-publication-and-regeneration).

Each submitted destination association includes the discovered audience for resident validation. The viewer must not substitute another audience after rendering.

Resident revalidation of discovered destinations and submitted image variants is defined in [Complete-request validation](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#complete-request-validation).

### Transport limits and admission

Transient requests must obey the image and request limits defined in [Protocol and limits](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#protocol-and-limits).

Check image dimensions and encoded sizes before expensive decoding or transfer where possible.

Apply safe bounded validation to externally supplied PNGs and generated transfer variants.

Do not decode and retain every transferred image simultaneously. Runtime staging and sequential validation belong to [Transient transfer and staging](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#transient-transfer-and-staging).

Obtain the runtime's metadata preflight response before transferring image payloads. A rejected request must not race image transfer or backend publication.

Resident transient admission, backend execution, and scheduled-presentation independence are governed by [Transient admission and refresh](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#transient-admission-and-refresh) and [Transient and information-view independence](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#transient-and-information-view-independence).

An explicit `refrain --refresh` requests the runtime's currently required scheduled presentation. Refresh admission and stale-identity checks belong to [Transient admission and refresh](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#transient-admission-and-refresh), not the viewer's rendering path.

### Publication results

Push is synchronous from the command user's perspective.

Report useful preparation and preflight diagnostics before transfer. Once publication is admitted, report its accepted publication phase before waiting for potentially slow backend operations.

A complete success result requires successful publication by every admitted destination.

One destination's success does not establish success for another, even if their images or backend instance are shared.

A failure at one destination must be reported without incorrectly marking successful independent destinations as failed.

When any selected destination fails, the overall request is unsuccessful, but already completed publication at other destinations is not rolled back.

Distinguish:

- no configured or participating targets;
- unknown or intentionally withdrawn targets;
- unsupported transient-publication capability;
- invalid or mismatched geometry;
- exceeded transport or image limits;
- busy admission;
- failed publication at one or more destinations;
- unavailable resident runtime;
- unconfirmed outcome after loss of a terminal response.

A lost terminal acknowledgement after admission is not proof of success or failure. Report the outcome as unconfirmed and do not automatically replay the request.

Transient state isolation and finished-image handling are defined in [Transient admission and refresh](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#transient-admission-and-refresh) and [Complete-request validation](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#complete-request-validation). Completed transient metadata must conform to [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes).

### Resident push validation

Hardware-independent tests using controlled runtime discovery, fake backends, and deterministic synchronization must cover:

- audience-specific QR variants and sharing across audiences with compatible rendering requirements;
- rejection when a destination's configured audience changes between discovery and admission;
- generic destination routing without backend-type conditionals;
- exact destination IDs, including literal `all` versus reserved `@all`;
- direct destination selection, withdrawn targets, and no-target results;
- `@all` inclusion of unavailable and failed participating destinations;
- rejection of unsupported transient destinations before rendering;
- preflight image counts, dimensions, encoded sizes, and transport limits;
- exact-size finished-image validation for every destination;
- multiple declared aspects with identical requested dimensions;
- coherent viewer presentation choices across multiple output specifications;
- changed or removed destinations after discovery;
- metadata preflight rejection before payload transfer;
- bounded sequential PNG validation and temporary staging;
- atomic busy rejection without partial admission;
- fixed membership after successful admission;
- independent publications on different backend instances;
- serialization of destinations sharing one backend instance;
- admitted transient work completing before newer scheduled work on the same instance;
- loss of client connection before and after admission;
- unconfirmed outcomes when terminal acknowledgement is lost;
- truthful per-destination success and failure reporting;
- absence of automatic replay or rollback;
- no changes to authoritative state, publication checkpoints, scheduled cache, or scheduled acknowledgement;
- completed transient metadata containing no literary or presentation sections;
- correct resource lifetime and shutdown handling.
- `--all-day` acceptance only with push, including finished-image pushes;
- correct forwarding of the all-day request without viewer-owned persistence or image retention;
- per-destination hold results and truthful reporting of partial publication success.

Physical Waveshare validation must separately confirm that a viewer preview is published through the existing resident backend, cannot overlap another physical refresh, remains displayed after push completion, and can be replaced by `refrain --refresh` without restarting Refrain.