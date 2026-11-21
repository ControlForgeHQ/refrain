# Command-line usage

This document is the authoritative public reference for command syntax, argument behavior, mode conflicts, results, and user-facing command diagnostics.

## Primary `refrain` application

The primary application has a normal resident mode and the standalone modes below. These modes have distinct ownership and lifecycle behavior; do not combine them in one invocation.

### Normal operation

```text
refrain [--config PATH]
```

With no mode option, `refrain` starts the normal resident runtime. `--config PATH` selects the application configuration; when omitted, the standard Refrain configuration path is used. The selected configuration file must exist. Normal startup does not substitute the packaged default configuration, initialize installation directories, or copy sample content.

The resident owns its configured backends and display resources. A second normal invocation fails immediately with an actionable diagnostic while another backend-owning Refrain process holds the installation. Normal operation continues until shutdown. Startup behavior is defined in [Startup and daily transitions](specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#startup-and-daily-transitions); selection and recovery in [Selection and Persistence](specifications/30-SELECTION_AND_PERSISTENCE.md); and backend failure behavior in [Failure handling and retries](specifications/60-DESTINATIONS_AND_RUNTIME_CONTROL.md#failure-handling-and-retries). `--config` is the only normal-mode option apart from `-h`/`--help`, which displays command help and exits. Orderly shutdown returns exit status `0`; reported startup or runtime errors return `1`. Invalid arguments or conflicting modes return `2`.

### Initialize

```text
refrain --initialize
```

Initialization is noninteractive and repeatable. It creates or reuses the standard per-user installation, including the standard publication root without replacing existing contents, and does not start the resident runtime. It operates on standard installation paths; runtime storage settings do not redirect it. A conflicting resident owner prevents the operation and produces an actionable diagnostic. Successful initialization leaves existing user configuration and content intact according to the [installation contract](specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#initialization); failures report the affected operation and path.

`--config PATH` cannot be combined with `--initialize`. Successful initialization returns `0`; a reported initialization failure returns `1`, and invalid arguments return `2`.

### Reset

```text
refrain --reset
```

Reset is an interactive destructive operation on the standard per-user installation and must be run while Refrain is stopped. Both input and output must be interactive terminals, and the confirmation must be exactly `RESET` (case-sensitive, without extra spaces). There is no noninteractive bypass. Cancellation leaves the installation unchanged. Reset preserves publication storage and does not use configured storage paths or remove custom storage locations. Its deletion scope and ownership protections are defined in [Reset](specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#reset).

`--config PATH` cannot be combined with `--reset`. Successful reset returns `0`; cancellation, a noninteractive terminal, or a reported operation failure returns `1`. Invalid arguments return `2`.

### Purge

```text
refrain --purge
```

Purge is an interactive destructive operation on the standard per-user installation and must be run while Refrain is stopped. Both input and output must be interactive terminals, and the confirmation must be exactly `PURGE REFRAIN` (case-sensitive, with one space between the words and no extra spaces). There is no noninteractive bypass. Cancellation leaves the installation unchanged. Purge includes the standard user assets and publication root but does not follow configured custom paths. Stop any independent consumer that may read publication data before purging it.

`--config PATH` cannot be combined with `--purge`. Successful purge returns `0`; cancellation, a noninteractive terminal, or a reported operation failure returns `1`. Invalid arguments return `2`. See [Purge](specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#purge) for deletion scope and safety.

## Resident runtime control

### Refresh

The primary `refrain --refresh` command requires an already-running normal Refrain instance. It asks that runtime to republish the presentation currently required by scheduling to every configured destination still participating in publication. Intentionally withdrawn destinations are skipped and are not recreated. It does not restore historical pre-preview pixels: if reveal progression advanced, refresh publishes the current reveal stage.

Refresh republishes the runtime's current scheduled presentation and does not require destinations to support transient publication of externally supplied images, such as `refrain-viewer --push`.

Refresh is a synchronous one-shot control request, not another resident runtime. It reports entry into the accepted refresh/publication phase before waiting on backend work and remains attached until publication to all participating destinations completes or fails. Exit status zero means every included destination succeeded. No-target, busy, stale-presentation, failed, unavailable-runtime, and unconfirmed outcomes exit nonzero. A refresh is rejected as stale before publication when its prepared selection, reveal stage, effective presentation, or destination requirements no longer match the resident's currently required presentation. Refresh does not start Refrain or access configured backends independently.

Refresh is a standalone control-client mode and uses the already-running resident's configuration and destinations; it does not select or start a runtime configuration. `--config PATH` cannot be combined with `--refresh`. Refresh failures return `1`; invalid arguments or conflicting modes return `2`. An unconfirmed outcome means publication may have occurred; do not retry automatically.

## Independent image server

```text
refrain-image-server [--config PATH]
```

`refrain-image-server` runs as a standalone HTTP service. `--config PATH` selects the application configuration; when omitted, the standard configuration is used.

Startup requires a valid `image-server` section identifying at least one configured `publish` destination. Missing or invalid required configuration prevents startup with an actionable diagnostic. Invalid optional settings follow the schema's warning-and-default rules.

The service operates independently of the resident and can serve verified filesystem publications while the resident is stopped.

See [Image Server](specifications/75-IMAGE_SERVER.md) for component requirements and [Application Configuration](schemas/CONFIGURATION.md#independent-image-server-settings) for configuration syntax.

## Presentation viewer

`refrain-viewer` renders one Refrain presentation, fully revealed by default. With no arguments it uses the standard configuration, selects `@preview:2` (the medium built-in preview quotation), and opens a simple local window:

```text
refrain-viewer
```

In ordinary inspection, export, and publication-reconstruction modes, the viewer does not use configured display backends or runtime persistence.

### Finished-image input

Use `--image PATH` to inspect a completed output image rather than generating a Refrain presentation:

```text
refrain-viewer --image candidate.png
refrain-viewer --image candidate.png --window
```

Finished-image input accepts only valid, single-frame 8-bit RGB PNG files with width 1–3840 pixels and height 1–2400 pixels, independently. Square and portrait images are valid. The local window uses the existing viewer and may fit a private desktop copy to the screen; the supplied file and its pixels are not changed. This mode does not load application configuration, content, assets, runtime destinations, or persistence.

The finished image may also be published through the existing transient push path:

```text
refrain-viewer --image candidate.png --push TARGET
```

The PNG must exactly match the requested output dimensions of every selected destination. `--push @all` includes every participating destination except intentionally withdrawn destinations, including failed or unavailable destinations, and is rejected as a whole if any selected destination has different dimensions or does not support transient publication. A bare `all` selects only a destination literally named `all`. The declared presentation aspect is not inferred from the image. The viewer never converts color modes, resizes, crops, pads, stretches, decorates, or otherwise transforms a finished image for publication.

With `--image`, presentation-generation controls (`--config`, `--entry`, font and face options, font-size bounds, background, decoration, text color, tint, style, QR options, and `--debug-layout`), local geometry and destination controls (`--aspect`, `--resolution`, and `--render-as`), and `--output` are invalid. `--output` does not copy the supplied file. `--window` may be used for local inspection, but cannot be combined with `--push`. The standalone `--list-destinations` operation cannot be combined with `--image`.

### Configuration selection

```text
--config PATH
```

`--config` selects the application configuration used by the viewer for content, assets, preferences, and presentation rendering. When omitted, the viewer uses the standard Refrain configuration. The selected configuration file must exist and pass validation. Finished-image input and destination discovery do not load it. In push mode, it continues to control these viewer-owned rendering inputs; it never determines or overrides the resident runtime's configured destination topology or output specifications.

### Destination discovery

Use the standalone control-client operation below to discover configured destination IDs before using `--push`:

```text
refrain-viewer --list-destinations
```

This operation requires a running normal Refrain instance and queries its resident runtime-control interface. It displays one entry per configured destination, including its exact configured ID, declared presentation aspect ratio, requested output resolution, transient-publication capability, participation/withdrawal status, external delivery availability, and whether the current scheduled publication was accepted. Destination IDs are runtime-supplied and opaque; the viewer does not infer or expose backend-specific routing behavior.

`--list-destinations` is a standalone mode. `--config` is invalid with this operation; it does not load viewer content, presentation assets, or configuration to discover topology. The operation does not render a presentation, initialize configured backends, or read runtime persistence independently. It does not accept `--push`, `--render-as`, local output geometry, presentation selection, or presentation overrides. The command’s table or whitespace layout is intended for human inspection and is not a machine-readable interface. If no normal resident instance is available, the command exits nonzero with an actionable diagnostic.

### Entry selection

Select an entry and an optional 1-based quotation number with:

```text
--entry ENTRY_ID[:QUOTATION_NUMBER]
```

Quotation numbers are positive integers starting at `1`; if omitted, quotation `1` is selected. The built-in `@preview` pseudo-entry provides its documented short, medium, and long preview quotations: bare `@preview` selects `@preview:1`. Without `--entry`, the viewer selects `@preview:2`.

Malformed selectors, unknown entries, and quotation numbers outside the selected entry are errors. Selecting an entry in the viewer ignores normal eligibility, priority, repetition history, and scheduling.

### Reveal-stage inspection

Use `--reveal-stage N` to render one cumulative reveal stage of an explicitly selected quotation. `N` is a zero-based integer from 0 through 2, inclusive; stage `0` is the first stage. Fields revealing simultaneously share a stage, and absent optional fields create no stages. Negative, malformed, and greater-than-2 indexes are errors. When a valid requested index exceeds the final stage available for the selected quotation on the current logical display date, the viewer warns and renders the final available stage instead.

`--reveal-stage` requires an explicit `--entry`, including for `@preview`. Without this option, viewer presentations are fully revealed. It affects only the locally rendered image and does not advance or persist resident reveal progress.

`--reveal-stage` may be combined with ordinary local inspection, `--output`, or `--render-as`. It cannot be combined with `--publication`, `--image`, `--push`, or `--list-destinations`.

### Presentation overrides

The following options explicitly override a presentation choice:

| Option | Accepted value |
|---|---|
| `--font FONT_ID\|@POOL` | Identifier of a registered font bundle or a named font pool reference. |
| `--quotation-face FACE_ID` | Face identifier available in the selected font bundle for the quotation role. |
| `--source-face FACE_ID` | Face identifier available in the selected font bundle for the source role. |
| `--attribution-face FACE_ID` | Face identifier available in the selected font bundle for the attribution role. |
| `--background BACKGROUND_ID\|none\|@POOL` | Registered background identifier, `none` to suppress the background, or a named background pool reference. |
| `--decoration DECORATION_ID\|none\|@POOL` | Registered decoration identifier, `none` to suppress decoration, or a named decoration pool reference. |
| `--text-color COLOR_ID\|@POOL` | Shared-palette identifier or named text-color pool reference. |
| `--tint COLOR_ID\|@POOL` | Shared-palette identifier or named decoration-color pool reference. |
| `--style centered\|left-aligned` | One of the two supported literary presentation styles. |
| `--qr` | Enable the literary QR code. |
| `--no-qr` | Suppress the literary QR code. |
| `--min-font-size PIXELS` | Positive integer design-canvas pixels; lower bound for quotation fitting. |
| `--max-font-size PIXELS` | Positive integer design-canvas pixels; upper bound for quotation fitting. |
| `--debug-layout` | Enable presentation layout diagnostics. |

`--qr` and `--no-qr` are mutually exclusive. Each supplied font-size bound replaces only that bound; the other remains inherited from configuration, or from publication metadata during reconstruction. The effective minimum may not exceed the effective maximum, even when only one bound is supplied.

An explicit viewer override is strict. A `@POOL` override selects one candidate from that category's expanded pool; if the pool has no selectable candidates, viewer preparation fails with an actionable diagnostic rather than silently falling back. If an explicitly requested registered resource, face, color, style, or other value cannot be used, viewer preparation likewise fails instead of consulting a lower-precedence preference or default pool. Properties not explicitly overridden continue to use normal Refrain preference resolution and pool selection. `none` explicitly suppresses only the background or decoration, as shown above.

For example:

```text
refrain-viewer --entry johnson-maggie:6 --decoration simple-border
refrain-viewer --min-font-size 48 --max-font-size 120
```

### Publication reconstruction

Reconstruct a presentation from one completed scheduled-publication metadata
document with:

```text
refrain-viewer --publication PATH [--config PATH] [presentation overrides...] [local output controls...]
```

For example:

```text
refrain-viewer --publication publication.json \
  --aspect 16:9 --resolution 3840 2160 --no-qr --output custom.png
```

The viewer requires a valid completed publication document and accepts only
`publication.type: "scheduled"`. It rejects preparation-stage, incomplete,
malformed, unsupported-version, transient, or structurally invalid metadata.
The [publication metadata schema](schemas/PUBLICATION.md#metadata-document-shapes) defines the
document contract; the viewer does not finalize or repair metadata.

The committed quotation, source, attribution, presentation style, and resolved
resource identifiers in the document supply the rendering input. The original
content library, audience, destination configuration, actions, operational
state, selection history, prepared-image cache, and resident runtime are not
used. Actions are validated as metadata but never interpreted or executed.
`--config` selects only the installed rendering resources, fonts, and palette;
it does not replace the publication's literary content or resolved artistic
choices.

All presentation overrides in the preceding table remain available and
override only their corresponding published choice. Unspecified choices
remain those recorded by the publication. QR availability is reevaluated for
the requested output and selected decoration; the recorded QR policy is the
baseline, while the original availability flag does not constrain a new
output.

Publication reconstruction accepts `--aspect`, `--resolution`, `--output`,
`--window`, and `--debug-layout`. When omitted, aspect defaults to `16:10` and
resolution uses the full design canvas for that aspect. The normal design-,
presentation-, and output-image geometry rules apply. `--output` writes the
reconstructed PNG without opening a window unless `--window` is also supplied;
without `--output`, the viewer opens its local window by default.

`--publication` is mutually exclusive with `--entry`, `--image`, `--push`,
`--render-as`, and `--list-destinations`. It does not infer or emulate the
publication's original destination. Missing or unreadable files, invalid
metadata, unavailable published resources, unusable published font faces, and
invalid reconstruction geometry produce an actionable nonzero CLI error.
Publication metadata input is limited to 16 MiB.

### Local inspection and export

Local inspection and export accept these controls:

| Option | Behavior |
|---|---|
| `--aspect ASPECT` | Select a supported presentation aspect: `4:3`, `5:3`, `16:9`, or `16:10`. |
| `--resolution WIDTH HEIGHT` | Set requested output width (1–3840) and height (1–2400) in integer pixels. Square and portrait outputs are valid. |
| `--render-as DESTINATION_ID` | Use a destination's configured output specification and apply its visual post-processing. |
| `--output PATH` | Write the completed output PNG to `PATH`. |
| `--window` | Open the simple local viewer window. |

When omitted, the aspect defaults to `16:10` and the resolution uses the full design canvas for the selected aspect. The [Image spaces and raster geometry section](specifications/50-PRESENTATION_AND_RENDERING.md#image-spaces-and-raster-geometry) defines the design-canvas, presentation-canvas, and output-image geometry; the CLI does not redefine that pipeline.

`--render-as` resolves the exact destination ID from the viewer's validated configuration, then uses its declared aspect ratio and requested resolution for the normal viewer rendering pipeline. It applies the destination's visual post-processing to the completed output image before local display or PNG export. For example:

```text
refrain-viewer --render-as waveshare-13in3-e --output panel-preview.png
refrain-viewer --render-as portrait --window
```

This is local inspection/export only: it does not query the resident runtime, read runtime persistence, or construct configured display backends. `window` and `publish` preserve pixels; `waveshare-13in3-e` previews its panel palette quantization and dithering. The Waveshare PNG retains the resolved palette indices; the viewer creates an RGB copy only for local-window display. `--render-as` is mutually exclusive with `--aspect` and `--resolution`; it cannot be combined with `--image`, `--push`, or standalone `--list-destinations`. Presentation selection and overrides, `--config`, `--output`, and `--window` remain valid. An identifier not present in the selected configuration is rejected. Visual post-processing supports `window`, `publish`, and `waveshare-13in3-e`.

`--output` writes the PNG without opening a window unless `--window` is also supplied. Without `--output`, the normal default behavior opens the simple local viewer window.

For example, select a configuration and export a PNG:

```text
refrain-viewer --config ./experimental.yaml --background aged-paper --output preview.png
```

### Push to configured destinations

The push form is:

```text
refrain-viewer [presentation selection and overrides...] --push TARGET
```

`TARGET` is `@all` or one exact configured destination ID returned by `--list-destinations`. Identifiers are supplied by the runtime and are opaque. `@all` means every configured destination still participating in publication; it skips intentionally withdrawn destinations but does not silently omit failed or unavailable destinations. A bare `all` is an ordinary destination ID and has no selector meaning.

If target selection yields no participating destinations, the command fails with an actionable no-target result rather than reporting success.

Push requires a running normal Refrain instance. An unknown or no-longer-configured target is rejected, and an explicitly selected intentionally withdrawn destination is rejected. A directly selected destination that does not support transient publication is rejected before rendering. `--push @all` is likewise rejected before rendering if any participating destination does not support it; it does not omit unsupported or failed destinations, and excludes only those intentionally withdrawn. The viewer renders complete image variants using its selected configuration, content, assets, and presentation overrides, then submits those images to the runtime. `--config` controls the viewer-owned rendering inputs; push obtains all destination topology and output geometry exclusively from the resident runtime.

A transient request supports at most 64 selected destinations and 64 complete image variants. Each variant must be a single-frame RGB PNG, at most 3840 pixels wide and 2400 pixels high, with no more than 9,216,000 decoded pixels or 32 MiB of encoded data. The aggregate encoded image data per request must not exceed 192 MiB.

The resident must accept metadata preflight before image transfer. Invalid destinations, unsupported capabilities, mismatched geometry, exceeded limits, and unavailable immediate admission are rejected before backend publication begins.

`--push` is mutually exclusive with `--window`, `--output`, `--aspect`, `--resolution`, `--render-as`, and `--list-destinations`. Presentation selection and presentation overrides, including `--config` and `--entry`, remain valid with push.

Preparation progress may be reported while images are rendered. After runtime admission, the viewer reports that publication has begun before waiting on potentially slow backend work. It remains attached for the terminal result. Exit status zero means every selected destination succeeded. Busy, rejected, failed, unavailable-runtime, and unconfirmed outcomes return `1`; invalid arguments or conflicting modes return `2`. An unconfirmed outcome means publication may have occurred; do not retry automatically.
