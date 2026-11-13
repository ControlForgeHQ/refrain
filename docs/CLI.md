# Command-line usage

This document is the authoritative public reference for command syntax, argument behavior, mode conflicts, results, and user-facing command diagnostics. Runtime behavior behind these commands is defined in [the architecture](ARCHITECTURE.md); implementation and testing guidance is in [Engineering](ENGINEERING.md).

## Resident runtime control

### Refresh

The primary `refrain --refresh` command requires an already-running normal Refrain instance. It asks that runtime to republish the presentation currently required by scheduling to every configured destination still participating in publication. Intentionally withdrawn destinations are skipped and are not recreated. It does not restore historical pre-preview pixels: if reveal progression advanced, refresh publishes the current reveal stage.

Refresh republishes the runtime's current scheduled presentation and does not require destinations to support transient publication of externally supplied images, such as `refrain-viewer --push`.

Refresh is a synchronous one-shot control request, not another resident runtime. It reports entry into the accepted refresh/publication phase before waiting on backend work and remains attached until publication to all participating destinations completes or fails. Exit status zero means every included destination succeeded. Busy, failed, unavailable-runtime, and unconfirmed outcomes exit nonzero. Refresh does not start Refrain or access configured backends independently.

## Presentation viewer

`refrain-viewer` renders one fully revealed Refrain presentation. With no arguments it uses the standard configuration, selects `@preview:2` (the medium built-in preview quotation), and opens a simple local window:

```text
refrain-viewer
```

In ordinary inspection and export modes, the viewer does not use configured display backends or runtime persistence.

### Finished-image input

Use `--image PATH` to inspect a completed output image rather than generating a Refrain presentation:

```text
refrain-viewer --image candidate.png
refrain-viewer --image candidate.png --window
```

Version 0.1 accepts only a valid, single-frame 8-bit RGB PNG with positive dimensions. The local window uses the existing viewer and may fit a private desktop copy to the screen; the supplied file and its pixels are not changed. This mode does not load application configuration, content, assets, runtime destinations, or persistence.

The finished image may also be published through the existing transient push path:

```text
refrain-viewer --image candidate.png --push TARGET
```

The PNG must exactly match the requested output dimensions of every selected destination. `--push all` includes every participating destination except intentionally withdrawn destinations, including failed or unavailable destinations, and is rejected as a whole if any selected destination has different dimensions or does not support transient publication. The declared presentation aspect is not inferred from the image. The viewer never converts color modes, resizes, crops, pads, stretches, decorates, or otherwise transforms a finished image for publication.

With `--image`, presentation-generation controls (`--config`, `--entry`, font and face options, font-size bounds, background, decoration, text color, tint, style, QR options, and `--debug-layout`), local geometry and destination controls (`--aspect`, `--resolution`, and `--render-as`), and `--output` are invalid. `--output` does not copy the supplied file. `--window` may be used for local inspection, but cannot be combined with `--push`. The standalone `--list-destinations` operation cannot be combined with `--image`.

### Configuration selection

```text
--config PATH
```

`--config` selects the application configuration used by the viewer for content, assets, preferences, and presentation rendering. When omitted, the viewer uses the standard Refrain configuration. In push mode, it continues to control these viewer-owned rendering inputs; it never determines or overrides the resident runtime's configured destination topology or output specifications.

### Destination discovery

Use the standalone control-client operation below to discover canonical destination identifiers before using `--push`:

```text
refrain-viewer --list-destinations
```

This operation requires a running normal Refrain instance and queries its resident runtime-control interface. It displays one entry per configured destination, including its canonical destination identifier, declared presentation aspect ratio, requested output resolution, transient-publication capability, and status distinguishing participation, failure/unavailability, and intentional withdrawal. Destination identifiers are runtime-supplied and opaque; the viewer does not infer or expose backend-specific routing behavior.

`--list-destinations` is a standalone mode. `--config` is invalid with this operation; it does not load viewer content, presentation assets, or configuration to discover topology. The operation does not render a presentation, initialize configured backends, or read runtime persistence independently. It does not accept `--push`, `--render-as`, local output geometry, presentation selection, or presentation overrides. Its table or whitespace layout is not a machine-readable interface in Version 0.1. If no normal resident instance is available, the command exits nonzero with an actionable diagnostic.

### Entry selection

Select an entry and an optional 1-based quotation number with:

```text
--entry ENTRY_ID[:QUOTATION_NUMBER]
```

Quotation numbers are positive integers starting at `1`; if omitted, quotation `1` is selected. The built-in `@preview` pseudo-entry provides its documented short, medium, and long preview quotations: bare `@preview` selects `@preview:1`. Without `--entry`, the viewer selects `@preview:2`.

Malformed selectors, unknown entries, and quotation numbers outside the selected entry are errors. Selecting an entry in the viewer ignores normal eligibility, priority, repetition history, and scheduling.

### Presentation overrides

The following options explicitly override a presentation choice:

| Option | Accepted value |
|---|---|
| `--font FONT_ID` | Identifier of a registered font bundle. |
| `--quotation-face FACE_ID` | Face identifier available in the selected font bundle for the quotation role. |
| `--source-face FACE_ID` | Face identifier available in the selected font bundle for the source role. |
| `--attribution-face FACE_ID` | Face identifier available in the selected font bundle for the attribution role. |
| `--background BACKGROUND_ID\|none` | Registered background identifier, or `none` to suppress the background. |
| `--decoration DECORATION_ID\|none` | Registered decoration identifier, or `none` to suppress the decoration. |
| `--text-color COLOR_ID` | Identifier of a color in the shared palette for literary text. |
| `--tint COLOR_ID` | Identifier of a color in the shared palette for tintable decoration artwork. |
| `--style centered\|left-aligned` | One of the two supported literary presentation styles. |
| `--qr` | Enable the literary QR code. |
| `--no-qr` | Suppress the literary QR code. |
| `--min-font-size PIXELS` | Positive integer design-canvas pixels; lower bound for quotation fitting. |
| `--max-font-size PIXELS` | Positive integer design-canvas pixels; upper bound for quotation fitting. |
| `--debug-layout` | Enable presentation layout diagnostics. |

`--qr` and `--no-qr` are mutually exclusive. When both font-size bounds are supplied, the minimum may not exceed the maximum.

An explicit viewer override is strict. If an explicitly requested registered resource, face, color, style, or other value cannot be used, viewer preparation fails with an actionable diagnostic rather than silently falling back to a lower-precedence preference or default pool. Properties not explicitly overridden continue to use normal Refrain preference resolution and pool selection. `none` explicitly suppresses only the background or decoration, as shown above.

For example:

```text
refrain-viewer --entry johnson-maggie:6 --decoration simple-border
refrain-viewer --min-font-size 48 --max-font-size 120
```

### Local inspection and export

Local inspection and export accept these controls:

| Option | Behavior |
|---|---|
| `--aspect ASPECT` | Select a supported presentation aspect: `4:3`, `5:3`, `16:9`, or `16:10`. |
| `--resolution WIDTH HEIGHT` | Set requested output width and height in positive integer pixels. |
| `--render-as DESTINATION_ID` | Use a destination's configured output specification and apply its visual post-processing. |
| `--output PATH` | Write the completed output PNG to `PATH`. |
| `--window` | Open the simple local viewer window. |

When omitted, the aspect defaults to `16:10` and the resolution uses the full design canvas for the selected aspect. The [architecture](ARCHITECTURE.md#image-spaces-and-output-geometry) defines the design-canvas, presentation-canvas, and output-image geometry; the CLI does not redefine that pipeline.

`--render-as` resolves the canonical destination identifier from the viewer's effective configuration, then uses its declared aspect ratio and requested resolution for the normal viewer rendering pipeline. It applies the destination's visual post-processing to the completed output image before local display or PNG export. For example:

```text
refrain-viewer --render-as waveshare-13in3-e --output panel-preview.png
refrain-viewer --render-as image-server:portrait --window
```

This is local inspection/export only: it does not query the resident runtime, read runtime persistence, or construct configured display backends. `window` and `image-server` preserve pixels; `waveshare-13in3-e` previews its panel palette quantization and dithering. `--render-as` is mutually exclusive with `--aspect` and `--resolution`; it cannot be combined with `--image`, `--push`, or standalone `--list-destinations`. Presentation selection and overrides, `--config`, `--output`, and `--window` remain valid. An identifier not present in the selected configuration is rejected.

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

`TARGET` is `all` or one canonical destination identifier returned by `--list-destinations`. Identifiers are supplied by the runtime and are opaque. `all` means every configured destination still participating in publication; it skips intentionally withdrawn destinations but does not silently omit failed or unavailable destinations.

Push requires a running normal Refrain instance. An unknown or no-longer-configured target is rejected, and an explicitly selected intentionally withdrawn destination is rejected. A directly selected destination that does not support transient publication is rejected before rendering. `--push all` is likewise rejected before rendering if any participating destination does not support it; it does not omit unsupported or failed destinations, and excludes only those intentionally withdrawn. The viewer renders complete image variants using its selected configuration, content, assets, and presentation overrides, then submits those images to the runtime. `--config` controls the viewer-owned rendering inputs; push obtains all destination topology and output geometry exclusively from the resident runtime.

`--push` is mutually exclusive with `--window`, `--output`, `--aspect`, `--resolution`, `--render-as`, and `--list-destinations`. Presentation selection and presentation overrides, including `--config` and `--entry`, remain valid with push.

Preparation progress may be reported while images are rendered. After runtime admission, the viewer reports that publication has begun before waiting on potentially slow backend work. It remains attached for the terminal result. Exit status zero means every selected destination succeeded. Busy, rejected, failed, unavailable-runtime, and unconfirmed outcomes exit nonzero.
