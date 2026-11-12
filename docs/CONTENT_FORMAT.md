# Content and Configuration Format

This document defines Refrain's user-facing YAML configuration and content-entry formats.

It is authoritative for field names, data types, required values, defaults, validation rules, and file-format compatibility.

Runtime behavior and selection policy belong in `docs/ARCHITECTURE.md`.

Engineering practices, YAML parser selection, storage implementation, and testing requirements belong in `docs/ENGINEERING.md`.

Feature scope and release sequencing belong in `docs/ROADMAP.md`.


## Format principles

Refrain uses YAML for both application configuration and content entries.

The two formats share YAML syntax but have separate schemas and responsibilities.

Application configuration defines settings shared across Refrain.

Content entries define quotations, their metadata, eligibility, priority, and optional reveal-schedule overrides.

The formats are intended to remain practical for direct human editing, even if an interactive editor is introduced in a future release.

Prefer explicit, readable fields over abbreviated expressions or specialized syntax.

Do not expose arbitrary Python expressions, executable tags, or application implementation details through YAML.

Application configuration favors continued operation when invalid or unrecognized settings can be safely ignored or replaced by documented defaults.

Content validation favors preserving usable entries while excluding individual invalid entries or files.

Neither format permits invalid input to silently alter the meaning of accepted values.

Validation and diagnostic requirements for the two formats are defined separately in this document.

## YAML conventions

### File encoding

Files must use UTF-8 encoding.

The recommended file extension is `.yaml`.

A YAML file must contain one top-level mapping.

Multiple YAML documents within a single file are not supported.

### Indentation and collections

Use spaces for indentation, not tabs.

Two-space indentation is recommended.

Collections are represented using ordinary YAML sequences.

For example:

```yaml
quotations:
  - "First quotation."
  - "Second quotation."
```

### Strings

Use double-quoted strings for short text, identifiers, dates, and times where explicit string interpretation improves clarity.

Unquoted YAML scalar strings are accepted when the YAML parser produces the intended string value.

Explicit quotation is recommended for values that resemble dates, numbers, booleans, or other YAML scalar types.

### Multiline strings

Use YAML's folded style (`>`) when source-file line wrapping should not produce displayed line breaks.

```yaml
quotations:
  - >-
    This quotation occupies several
    source-file lines but is displayed
    as one continuous paragraph.
```

Use literal style (`|`) when line breaks are meaningful.

```yaml
quotations:
  - |-
    The first line remains separate.
    The second line remains separate.

    A blank line separates paragraphs.
```

The `-` following `>` or `|` suppresses the final trailing newline.

The final trailing newline is otherwise part of the parsed string.

The quotation's parsed text is retained for display.

Refrain does not reinterpret source-file wrapping after YAML parsing.

### Unsupported YAML features

Content and configuration files must not rely on:

- custom YAML tags;
- executable object constructors;
- aliases or anchors;
- merge keys;
- duplicate mapping keys;
- implicit application-specific expressions.

The supported interface consists of ordinary YAML mappings, sequences, strings, integers, and booleans as defined by the relevant schema.

A parser may recognize additional YAML syntax, but that does not make it part of Refrain's supported format.

## Application configuration

Application configuration is stored in a YAML file, conventionally named `config.yaml`.

It defines settings that apply across the application.

Content-entry-specific information must not be stored in application configuration.

### Example

```yaml
general:
  day_start: "05:00"

content:
  directory: "content"

reveal:
  source: "12:00"
  attribution: "18:00"

information_view:
  duration: 60

presentation:
  qr:
    enabled: true

display:
  backends:
    - type: "image-server"
      host: "127.0.0.1"
      port: 8080
      outputs:
        - id: "default"

layout:
  presentation_insets:
    left: 384
    right: 384
    top: 324
    bottom: 324

  fonts:
    default:
      - "libre-baskerville"
      - "lora"
      - "source-sans-3"
    font_faces:
      source: italic

  backgrounds:
    default:
      - "none"
      - "aged-paper"

  decorations:
    default:
      - "none"
    colors:
      - "black"

  text:
    colors:
      - "black"
    min_font_size: 56
    max_font_size: 200
```

The example illustrates an image-server output, the information view, explicit QR policy, independent literary insets, resource pools, and automatic quotation fitting.

The installed distribution includes `config.default.yaml` as an editable starting point. `python -m refrain --initialize` copies it alongside a packaged sample content library; the installed copy is authoritative and is not synchronized or replaced automatically. Its bundled resource pools use the identifiers documented below and it relies on host-local time rather than a configured timezone. `examples/config.yaml` remains a development example with a separate purpose.

Refrain discovers bundled resources through package resources and user resources recursively beside the effective configuration file under `assets/fonts/`, `assets/backgrounds/`, or `assets/decorations/`. Each discovered resource is available by stable identifier without adding it to a default pool.

Fonts, packaged backgrounds, and decorations use YAML manifests whose referenced files are relative to the manifest directory and confined to that package. Standalone background PNGs use their filename stem as the identifier. See the [asset registries](#font-registry) for manifest schemas and validation.

Custom visual resources are selected by registered identifier; there is no arbitrary absolute-path resource registration interface. The configuration-file, content-directory, and operational-path rules above remain separate.

When `--config` selects a nonstandard configuration file, its containing directory supplies the assets root. Refrain does not search platform-standard or current-working-directory asset locations in that case. `content.directory` remains independent: when omitted it is `content/` beside the configuration file, an explicit relative value is configuration-relative, and an absolute value is used directly. Explicit `storage` paths use the same configuration-relative rule; omitted storage values continue to use independent platform-standard locations.

The `default` pools control automatic resource selection. A resource need not appear in its default pool to be selected explicitly by a content entry.

The reserved value `"none"` is available for backgrounds and decorations. The example uses it to preserve the original undecorated, paper-white presentation.

User-supplied resource paths, rectangle dimensions, and font-size values are examples rather than universal defaults.

The resolution and precedence of content-entry resource preferences are defined in the corresponding sections below.

### Named color palette

The optional top-level `palette` mapping defines named RGB colors available to literary text and decoration preferences and their default pools.

The six built-in identifiers are `black`, `white`, `red`, `yellow`, `blue`, and `green`, initially mapped to `#000000`, `#FFFFFF`, `#FF0000`, `#FFFF00`, `#0000FF`, and `#00FF00`. These conventional digital RGB values are provisional and are not calibrated Spectra-6 pigment measurements.

Custom identifiers follow the shared ASCII asset identifier rules: begin with a letter or digit and contain only letters, digits, hyphens, and underscores. Each value must be a quoted six-digit `#RRGGBB` string. Custom entries extend the built-in palette, and a configured built-in identifier overrides its default RGB value without removing that identifier. Invalid identifiers or values are warned about and ignored; an invalid override leaves the built-in value in place.

For example:

```yaml
palette:
  red: "#C82F32"
  burnt-orange: "#C65A20"
  sky-blue: "#78B7D4"
  nasty-green-goo: "#718C23"

layout:
  decorations:
    colors:
      - "black"
      - "burnt-orange"
```

RGB lists and direct RGB values in content entries or decoration manifests are not supported.

### Display backends

The required `display.backends` field selects one or more implementations used to present complete rendered images.

The field must contain a nonempty sequence of backend mappings.

Each backend mapping requires a `type` field identifying one supported built-in backend.

Version 0.1 defines the following built-in backend identifiers:

| Value | Description |
|---|---|
| `"window"` | Displays complete presentation images in a desktop window on a supported graphical Windows or Linux environment. |
| `"waveshare-13in3-e"` | Presents complete images on the supported Waveshare 13.3-inch e-Paper HAT+ (E). |
| `"image-server"` | Serves one or more named prepared output images to HTTP clients. |

Each backend type may appear at most once in `display.backends`.

The sequence must contain at least one valid, uniquely identified backend. Duplicate backend types are configuration errors.

Backend declaration order has no semantic meaning and does not establish execution priority.

Only implemented backends may be selected at runtime. Unsupported backend identifiers do not become available merely because they appear in configuration.

An unavailable backend must produce an actionable diagnostic rather than silently selecting another type. Runtime failures of an individual backend do not invalidate other configured destinations.

The `display.backends` field has no implicit default. Development example configurations may select `"window"`; installations using the physical e-paper panel must explicitly include `"waveshare-13in3-e"`.

The former singular `display.backend` field is not supported. No compatibility alias or automatic conversion is provided.

Each output destination resolves an output specification consisting of a declared presentation aspect ratio and a requested output resolution. The requested resolution never determines or implies the aspect ratio. Refrain prepares one complete set of reveal-stage images for each unique output specification required by the configured destinations. Destinations with identical specifications may share prepared variants; destinations with different specifications receive their matching variants.

A backend must not geometrically resize, crop, pad, or otherwise adapt an output image prepared for another destination. Backend-owned pixel-format or orientation conversion is permitted only where explicitly defined by that backend's contract. Backend selection is independent of content selection, reveal scheduling, and image preparation.

Version 0.1 does not support third-party backend discovery, arbitrary Python module paths, or an external display plugin interface.

#### Backend-specific fields

Each backend mapping contains its required `type` field and any supported settings for that backend.

The `window` backend resolves one output specification and accepts `aspect_ratio` and `resolution` as a pair. When neither is supplied, its output specification defaults to `16:9 @ 1920 × 1080`; for example, `- type: "window"` uses that default. When both are supplied, they define its output specification; supplying only one is a configuration error.

The `waveshare-13in3-e` backend has the fixed output specification `4:3 @ 1600 × 1200`. Its aspect ratio and resolution are intrinsic to the backend and cannot be configured; supplying either field is a configuration error.

The `image-server` backend supports optional `host` and `port` fields and a required nonempty `outputs` sequence. Each output has a stable, unique `id` within that backend instance and may specify an `aspect_ratio` and `resolution` pair. If neither is supplied, the output defaults to `16:10 @ 3840 × 2400`; supplying only one is a configuration error. One image-server backend instance may serve multiple named outputs; they are not separate backend instances.

For example:

```yaml
display:
  backends:
    - type: "window"
      aspect_ratio: "4:3"
      resolution: [1600, 1200]

    - type: "waveshare-13in3-e"

    - type: "image-server"
      host: "0.0.0.0"
      port: 8080
      outputs:
        - id: "default"

        - id: "repeat-kitchen"
          aspect_ratio: "4:3"
          resolution: [1600, 1200]

        - id: "repeat-hallway"
          aspect_ratio: "16:9"
          resolution: [1920, 1080]
```

The following fields are supported for the `window` backend:

| Field | Type | Required | Default |
|---|---|---|---|
| `aspect_ratio` | Supported aspect ratio string | No | `"16:9"` |
| `resolution` | Two positive integer pixel dimensions, `[width, height]` | No | `[1920, 1080]` |

These fields must either both be omitted or both be supplied. A resolution does not imply an aspect ratio, and Refrain does not infer a resolution from an aspect ratio or fill one supplied field from the other's default.

The `waveshare-13in3-e` backend accepts neither `aspect_ratio` nor `resolution`. Its fixed output specification is `4:3 @ 1600 × 1200`.

The following fields are supported for the `image-server` backend:

| Field | Type | Required | Default |
|---|---|---|---|
| `host` | String | No | `"127.0.0.1"` |
| `port` | Integer | No | `8080` |
| `outputs` | Nonempty sequence of named output mappings | Yes | — |

`host` and `port` belong directly to the `image-server` backend mapping. `outputs` contains the output destinations served by this one backend instance.

Each `outputs` item has the following fields:

| Field | Type | Required | Default |
|---|---|---|---|
| `id` | Stable, nonempty string unique within this image-server backend; its canonical runtime destination identifier must not exceed 256 characters | Yes | — |
| `aspect_ratio` | Supported aspect ratio string | No | `"16:10"` |
| `resolution` | Two positive integer pixel dimensions, `[width, height]` | No | `[3840, 2400]` |

For each named output, `aspect_ratio` and `resolution` must either both be omitted or both be supplied. Supplying only one is a configuration error. Do not infer either value from the other. The output ID identifies a destination within the server and does not create another backend instance.

`host` specifies the local address on which the HTTP service listens.

It must be a nonempty string identifying a valid local bind address or hostname.

Common values include:

- `"127.0.0.1"`: Listen only on the local IPv4 loopback interface.
- `"0.0.0.0"`: Listen on all available IPv4 interfaces.
- A specific local IP address: Listen only on that address.

The default loopback address prevents connections from other network devices. Access from another device requires an appropriate listening address and any necessary operating-system firewall configuration.

Binding to a network-accessible address does not provide authentication or encryption. The image-server service is intended for trusted local networks and must not be exposed directly to untrusted networks or the public Internet.

`port` specifies the TCP listening port. It must be an integer between 1 and 65535, inclusive. Boolean values, strings, floating-point values, zero, and out-of-range integers are invalid.

An unavailable listening address or occupied port is a backend initialization failure, not a configuration fallback condition.

Invalid optional image-server settings are handled according to the application's documented configuration-validation rules.

Unsupported fields within a backend mapping are reported as unrecognized configuration fields.

The image-server exposes each named output as a distinct PNG resource at `/display/<output_id>/current`, as defined in `docs/ARCHITECTURE.md`. A named output's stable ID determines its resource path.

The backend retains each named output's current image representation in memory and requires no separate image-storage directory or filesystem path.

### General settings

| Field | Type | Required | Default |
|---|---|---|---|
| `general.day_start` | Time string | No | `"06:00"` |

The host operating system supplies the local timezone and daylight-saving rules for all configured scheduling times. A `general.timezone` field is unsupported and is reported as an unknown field.

`day_start` specifies the local wall-clock time at which a new logical display day normally begins.

Times use 24-hour `HH:MM` notation with two-digit hours and minutes.

Examples of valid times are `"00:00"`, `"06:00"`, and `"18:30"`.

Seconds, timezone suffixes, and loosely formatted times are not supported in Version 0.1.

### Storage settings

The optional top-level `storage` mapping selects runtime persistence and prepared-artifact locations.

| Field | Type | Required | Default |
|---|---|---|---|
| `storage.state` | Path string | No | Platform-standard operational-state file |
| `storage.history` | Path string | No | Platform-standard global-history file |
| `storage.artifacts` | Path string | No | Platform-standard prepared-artifact directory |

Each field is independent. In particular, setting `storage.state` does not change the default location of global history.

An absolute path is used as specified. A relative path is resolved from the directory containing the selected configuration file. An omitted field continues to use its corresponding platform-standard Refrain location; selecting another file with `--config` does not itself relocate storage.

When present, `storage` must be a mapping and each supported value must be a nonempty string. Unsupported fields are reported and ignored according to the configuration unknown-field policy. An explicitly invalid storage value is an error; Refrain does not replace it with a platform default.

### Information view settings

The optional `information_view` mapping controls automatic presentation of Refrain's application information view during startup.

| Field | Type | Required | Default |
|---|---|---|---|
| `information_view.duration` | Integer | No | `60` |

`duration` specifies the automatic information-view presentation duration in seconds.

Valid values are integers from 0 through 300, inclusive.

- `0` disables automatic information-view presentation.
- Values from `1` through `300` enable automatic presentation for the specified duration.

The duration begins when the first configured display backend successfully publishes the information view.

The duration is measured using elapsed time rather than wall-clock time. Changes to the system clock do not extend or shorten it.

The information view appears once on each application start when enabled. It does not automatically reappear at a display-day boundary.

If the information view cannot be prepared or successfully published within the application's bounded initial attempt period, ordinary daily presentation proceeds without requiring successful information-view publication.

Omitting `information_view` or its `duration` field uses the documented default of 60 seconds.

An explicitly supplied invalid duration produces a warning and uses the documented default, according to the application's configuration-validation rules.

Boolean values, strings, floating-point values, negative integers, and integers greater than 300 are invalid.

This configuration controls automatic startup presentation only. It does not define an external request interface or additional scheduling rules.

### Literary QR setting

The optional `presentation.qr` mapping controls QR generation for literary presentations.

| Field | Type | Required | Default |
|---|---|---|---|
| `presentation.qr.enabled` | Boolean | No | `true` |

When `enabled` is `false`, no QR code is generated for literary presentations. A selected decoration's `qr_ready: false` also suppresses QR generation. Valid positioning that places the complete QR allocation outside the design canvas, or a presentation canvas too small for a complete one-pixel-per-module symbol, suppresses QR with an actionable warning but does not invalidate the decoration or literary presentation. Resolve effective availability separately for each output specification, before selecting its conditional decoration artwork; keep the result stable across that specification's reveal stages. This setting does not affect the standalone information view.

For Version 0.1, an enabled literary QR code always encodes `https://github.com/ControlForgeHQ/refrain`, independently of content, display date, and reveal stage. Its production encoding and raster contract is defined in [QR generation and conditional artwork](ARCHITECTURE.md#qr-generation-and-conditional-artwork). The destination is not configurable, and no content-entry QR field exists.

Boolean values are required when the field is present; strings, integers, and other YAML types are invalid. An omitted setting enables QR generation. An invalid optional value produces a warning and uses the default `true`. Intentional policy or `qr_ready: false` suppression does not require a warning.

QR enablement is configured at the presentation level only. Content entries have no QR override; a decoration's `qr_ready` field may suppress generation for that selected decoration.

### Content settings

| Field | Type | Required | Default |
|---|---|---|---|
| `content.directory` | String | No | `"content"` |

`directory` identifies the location of the content library. The field may be omitted; when absent, the effective directory is `content/` alongside the selected configuration file. This default applies equally to platform-standard configuration and a file selected with `--config`, and does not produce an informational diagnostic.

Relative paths are interpreted relative to the directory containing the application configuration file.

Absolute paths are permitted.

The path must identify a readable directory when the library is loaded.

Directory organization does not influence content eligibility, priority, or selection probability.

### Global reveal schedule

| Field | Type | Required | Default |
|---|---|---|---|
| `reveal.source` | Time string | No | `"12:00"` |
| `reveal.attribution` | Time string | No | `"18:00"` |

The global reveal schedule establishes default host-local times for source and attribution.

The initial presentation stage, which reveals the quotation, occurs at `general.day_start`.

`source` and `attribution` specify when those fields first become visible, if present in the selected content entry.

Reveal stages are cumulative.

A field remains visible after its reveal time has been reached.

Multiple fields may share the same reveal time.

When multiple fields become visible simultaneously, they belong to the same effective presentation stage.

For Version 0.1, reveal times must fall within the same local calendar date as the display-day start and must not precede it.

This restriction avoids ambiguity about whether a clock time refers to the current or following calendar date.

The runtime behavior of clock adjustments, missed stages, and restarts is defined by the architecture.

### Layout settings

Version 0.1 provides one configurable, typography-first presentation layout with optional backgrounds and decorations.

The complete literary composition consists of the primary quotation and its optional source and attribution.

The Version 0.1 public layout configuration defines:

- default independent literary presentation insets;
- discovered fonts and their default selection pool;
- discovered backgrounds and their default selection pool;
- discovered decorations and their default selection pool;
- minimum and maximum primary quotation font sizes.

A selected decoration may override the default literary insets and may specify a preferred background.

Backgrounds and decorations do not change the semantics of quotation, source, attribution, or progressive reveal.

The renderer determines the arrangement and fitting of all present literary fields within the effective rectangle derived from the insets.

A fixed quotation font size is not required.

### Output specifications and presentation insets

Each configured output destination has an output specification consisting of a declared presentation aspect ratio and a requested resolution. The supported declared landscape aspect ratios are 4:3, 5:3, 16:9, and 16:10. The backend-specific fields and defaults are defined in [Display backends](#display-backends). An aspect ratio and resolution are an inseparable pair where configurable: both are omitted to use that destination's documented defaults, or both are supplied explicitly. Supplying just one is a configuration error. Do not infer the aspect ratio from requested dimensions, infer dimensions from the aspect ratio, or fill one explicit value from the other's default. The fixed Waveshare output accepts neither field.

Requested dimensions are positive integer pixels in width, height order and need not exactly match the declared aspect ratio. For example, an output specification may declare 4:3 and request `[1600, 1190]`; the architecture resolves the presentation canvas separately and resizes only the completed image to the requested dimensions. The 3840 × 2400 reference envelope does not limit requested output dimensions. Boolean values, non-integer dimensions, zero or negative dimensions, and unsupported aspect ratios are configuration errors. See [the presentation architecture](ARCHITECTURE.md#image-spaces-and-output-geometry) for design-, presentation-, and output-image geometry.

The optional `layout.presentation_insets` mapping defines the default literary rectangle as four independent design-canvas pixel measurements. If omitted, it defaults to `left: 384`, `right: 384`, `top: 324`, and `bottom: 324`:

| Field | Type | Required |
|---|---|---|
| `layout.presentation_insets.left` | Nonnegative design-canvas pixel integer | Yes, when the mapping is supplied |
| `layout.presentation_insets.right` | Nonnegative design-canvas pixel integer | Yes, when the mapping is supplied |
| `layout.presentation_insets.top` | Nonnegative design-canvas pixel integer | Yes, when the mapping is supplied |
| `layout.presentation_insets.bottom` | Nonnegative design-canvas pixel integer | Yes, when the mapping is supplied |

The 3840 × 2400 envelope defines the maximum design area from which the aspect-specific design canvas is selected. Insets are applied inward from that design canvas's edges, not from the full reference envelope. Thus `left: 180` means 180 design-canvas pixels at every supported aspect ratio. Insets are not normalized coordinates; resolve the literary rectangle in design-canvas coordinates and scale its edges to the presentation canvas using the deterministic rounding rules in `ARCHITECTURE.md`. Do not scale literary geometry directly to aspect-mismatched requested output dimensions. Boolean values and non-integer values are invalid.

For example:

```yaml
layout:
  presentation_insets:
    left: 384
    right: 384
    top: 324
    bottom: 324
```

Each opposing pair must leave a positive width or height on the active design canvas for the declared presentation aspect ratio. A missing edge in a supplied mapping, negative value, or degenerate resulting rectangle is an error. When a decoration supplies `presentation_insets`, it must provide all four edges and the complete mapping replaces the global mapping. Otherwise the global mapping applies. Insets are independent of decoration image dimensions, slice coordinates, and transformations.

The effective rectangle contains the complete quotation and any source and attribution. All present fields, including unrevealed fields, must fit in the rectangle without overlap, clipping, or truncation. Its geometry remains stable across every reveal stage. This fitting guarantee does not prevent the text rectangle from overlapping independently composited artwork or QR output. The default configuration and bundled artwork must avoid undesirable overlap; custom configuration and decoration authors are responsible for checking their composition. Refrain does not detect or correct graphical overlap.

Backend output mappings supply declared aspects and requested dimensions. Layout YAML supplies design-canvas pixel insets and source-image slice measurements. The fixed reference envelope is 3840 × 2400. Design-canvas dimensions, presentation-canvas dimensions, and derived rendering geometry are resolved during image preparation; they are not additional YAML fields or daily-selection state.

A content entry cannot directly specify presentation insets.

### Font registry

Refrain maintains an effective registry of bundled font bundles and valid bundles discovered recursively under `<configuration directory>/assets/fonts/`. Each bundle has a stable, case-sensitive identifier; content entries and the default pool refer to the identifier, not a path.

Bundled font identifiers are `alegreya`, `libre-baskerville`, `lora`, `orbitron`, and `source-sans-3`. These identifiers are reserved and stable. `orbitron` is available for explicit selection but is not in the default pool unless configured there.

#### Font bundle manifests

Each package directory contains a `font.yaml` manifest:

```yaml
format: 1
id: literary
faces:
  regular: Lora-Regular.ttf
  italic: Lora-Italic.ttf
  handwritten: Handwriting-Regular.otf
font_faces:
  quotation: regular
  attribution: italic
```

`format` must be the integer `1`. `id` and face names must begin with an ASCII letter or digit and contain only ASCII letters, digits, hyphens, and underscores. `faces` is a nonempty mapping of face names to supported `.ttf` or `.otf` files and must contain a usable `regular` face. An unusable optional face produces a warning and is excluded individually; an unusable `regular` face excludes the bundle. Invalid face names or other structurally invalid manifest data exclude the bundle. Files within a bundle need not belong to one typographic family. Face paths are relative to the manifest directory.

The optional `font_faces` mapping names the bundle author's preferred face for each of `quotation`, `source`, and `attribution`. Its values are case-sensitive face identifiers, not file paths. Omitted roles express no preference. A malformed mapping or invalid role/identifier is warned about and ignored without invalidating the bundle. A syntactically valid preference may name a face not present in the bundle; the bundle remains valid, and selection-time resolution reports the missing face and uses `regular`.

The `faces` mapping registers font resources; `font_faces` expresses role preferences. They are separate interfaces.

Use safe YAML loading. Unknown manifest fields produce warnings and are ignored. Invalid manifest data, unsupported versions/formats, missing or unreadable resources, absolute paths, parent traversal, and references escaping the package (including symlink escapes) exclude the affected bundle without affecting unrelated resources. Bundled font directories retain their license and copyright files.

All usable bundled and discovered fonts are available for explicit content-entry selection independently of default-pool membership. A custom identifier conflicting with a bundled identifier is excluded. All custom bundles sharing an identifier are excluded with deterministic diagnostics listing their locations.

### Default font pool

The required `layout.fonts.default` field is a nonempty sequence of font identifiers.

For example:

```yaml
layout:
  fonts:
    default:
      - "libre-baskerville"
      - "lora"
      - "my-lora"
    font_faces:
      attribution: italic
```

The configured default pool defines the user's preferred fonts for automatic selection.

The effective default pool contains only identifiers from the configured pool that correspond to usable fonts in the effective registry.

Unavailable, unregistered, or otherwise invalid font identifiers are excluded from the effective default pool with warnings.

Duplicate identifiers are ignored after their first occurrence, with a warning.

The effective default pool must contain at least one usable font only when image preparation requires automatic font selection after explicit content-entry and decoration preferences are unavailable.

The default pool is explicitly configured. Refrain must not automatically add bundled or newly discovered fonts to the pool.

The optional `layout.fonts.font_faces` mapping supplies lowest-priority face preferences and does not affect the pool or bundle-selection randomness. It accepts the same `quotation`, `source`, and `attribution` roles and face-identifier syntax as bundle manifests. Invalid mappings or values are warned about and ignored. The packaged `config.default.yaml` explicitly requests italic attribution; installations whose existing configuration omits this field do not receive an implicit italic preference.

A registered font need not appear in the default pool. Fonts outside the default pool remain available for explicit selection by content entries.

The effective default pool identifies the fonts eligible for automatic selection when a content entry has no available preferred font.

An empty or unusable effective default pool does not prevent use of an otherwise usable explicit content-entry or decoration preference. When automatic selection is required and the effective pool is empty, preparation fails with an actionable diagnostic; Refrain does not substitute an unrelated bundled font pool.

Font-selection precedence, cache reuse, face fallback, and preparation failures are defined in `docs/ARCHITECTURE.md`.

### Background registry

Refrain maintains an effective registry containing bundled and recursively discovered backgrounds. Identifiers are case-sensitive ASCII names beginning with a letter or digit and containing only letters, digits, hyphens, and underscores. The reserved identifier `"none"` represents no background and cannot be registered.

Bundled identifiers are `aged-paper`, `canvas`, `cloth`, `drafting-grid`, `handmade-paper`, `hex`, `isometric-grid`, `limestone`, `recursive-squares`, and `vellum`; they remain stable and are available without being added to the default pool.

#### Discovered backgrounds

Standalone PNG files use their filename stem as the identifier. For example, `assets/backgrounds/aged-paper.png` registers `aged-paper`.

Directories containing `background.yaml` define packaged backgrounds:

```yaml
format: 1
id: forest
image: forest.png
```

`format` must be the integer `1`, and `image` is a relative PNG path resolved from the manifest directory. A recognized package is a discovery boundary, so internal images are not also registered as standalone backgrounds.

Manifests use safe YAML loading; unknown fields produce warnings. Absolute references, parent traversal, paths escaping the package (including symlink escapes), unsupported formats, and unreadable manifests or images exclude only the affected resource. Backgrounds must be readable, single-frame RGB or RGBA PNGs. Source dimensions and aspect ratios may differ from the configured output.

Background composition preserves aspect ratio with centred cover scaling: scale uniformly until the canvas is covered, then crop overflow evenly from opposing sides. The result is composited over paper-white, preserving RGBA transparency; it is never stretched or letterboxed.

All usable discovered backgrounds are available for explicit entry or decoration preferences whether or not included in the default pool. Custom resources cannot shadow bundled identifiers. If custom resources share an identifier, all are excluded and their locations are reported deterministically.

#### Default background pool

The optional `layout.backgrounds.default` field is a nonempty sequence of registered background identifiers and/or `"none"`.

For example:

```yaml
layout:
  backgrounds:
    default:
      - "none"
      - "handmade-paper"
      - "parchment"
```

When omitted, the default background pool is `["none"]`.

The effective pool contains the distinct, usable identifiers from the configured pool. Invalid or unavailable identifiers are excluded with warnings. Duplicates are ignored after their first occurrence.

Each member of the effective pool has equal selection probability.

A registered background outside the default pool remains available for explicit selection by a content entry or decoration.

An explicitly configured pool with no usable members falls back to `["none"]` with a warning.

Backgrounds have no repetition history or selection weights.

### Decoration registry

Refrain maintains an effective registry containing bundled and recursively discovered decorations. A decoration is a transparent overlay with optional presentation metadata. The reserved identifier `"none"` means no decoration and cannot be registered.

Bundled identifiers are `ethereal`, `hex`, `lower-flourish`, `simple-border`, and `top-bottom-borders`. They remain stable and are available independently of the default pool.

#### Decoration manifests

Each package directory under `<configuration directory>/assets/decorations/` contains `decoration.yaml`. The initial supported manifest schema defines an ordered multi-image composition. No compatibility with previous unreleased single-image development manifests is required.

```yaml
format: 1
id: botanical-border
presentation_insets:
  left: 180
  right: 180
  top: 120
  bottom: 160
font: lora
font_faces:
  quotation: handwritten
  attribution: italic
text_color:
  - black
  - burnt-orange
background: aged-paper
qr_ready: true
qr_from_right: 20
qr_from_bottom: 20
tintable: true
decoration_color:
  - sky-blue
  - burnt-orange
layers:
  - image: border.png
    method: nine-slice
    slices:
      left: 96
      right: 96
      top: 96
      bottom: 96
      horizontal: stretch
      vertical: crop
    condition: always
  - image: accent.png
    method: contain
    tintable: false
  - image: centered-flourish.png
    method: cover
  - image: qr-corner.png
    method: contain
    condition: qr
  - image: no-qr-flourish.png
    method: contain
    condition: no-qr
```

| Field | Type | Required | Default |
|---|---|---|---|
| `format` | Integer version (`1`) | Yes | — |
| `id` | Asset identifier | Yes | — |
| `layers` | Nonempty ordered sequence of layer mappings | Yes | — |
| `presentation_insets` | Complete four-edge mapping of nonnegative design-canvas pixel integers | No | Global `layout.presentation_insets` |
| `font` | Font identifier | No | None |
| `font_faces` | Mapping of literary roles to face identifiers | No | None |
| `text_color` | Palette identifier or nonempty sequence of palette identifiers | No | None |
| `background` | Background identifier or `"none"` | No | None |
| `qr_ready` | Boolean | No | `true` |
| `qr_from_left` | Nonnegative design-canvas pixel integer | No | — |
| `qr_from_right` | Nonnegative design-canvas pixel integer | No | `20` when no horizontal method is supplied |
| `qr_from_top` | Nonnegative design-canvas pixel integer | No | — |
| `qr_from_bottom` | Nonnegative design-canvas pixel integer | No | `20` when no vertical method is supplied |
| `qr_centered` | Scalar string: `horizontal` or `vertical` | No | — |
| `tintable` | Boolean | No | `true` |
| `decoration_color` | Palette identifier or nonempty sequence of palette identifiers | No | None |

`format` must be integer `1`; identifiers follow the shared ASCII asset identifier rules. Each layer's image path is resolved relative to the manifest. Safe YAML loading is required and unknown manifest fields produce warnings. Absolute references, parent traversal, escaping paths (including symlink escapes), unsupported formats, invalid layer definitions, and unreadable manifests or images exclude only the affected decoration.

The optional `presentation_insets` must contain all four fields `left`, `right`, `top`, and `bottom`. It replaces the global inset mapping as a whole; partial merging is not performed. Insets are design-canvas measurements, validated and resolved according to [Output specifications and presentation insets](#output-specifications-and-presentation-insets). They are independent of all layer source dimensions, slice coordinates, and transformations.

An unavailable or invalid optional font/background preference produces a warning and is treated as absent without invalidating an otherwise usable decoration. The optional `font_faces` mapping follows the same warning-and-ignore policy when malformed; its preferences need not name faces available in every bundle. Invalid inset metadata or artwork excludes that decoration. Decorations do not define arbitrary drawing instructions, independently positioned text fields, or new literary styles.

The optional `text_color` is a preference for the literary composition's text when that decoration is selected; it never tints decoration images. It accepts the same scalar-or-nonempty-list syntax as the content-entry field. Invalid or unavailable members are diagnosed during image preparation and ignored without invalidating the decoration.

The decoration-wide `tintable` property must be a YAML boolean and defaults to `true`. A malformed value produces a warning and uses the default. The `decoration_color` preference is distinct from `text_color`; it supplies one color for the decoration when at least one layer is effectively tintable. It accepts a palette identifier or nonempty sequence. Invalid or unavailable members are diagnosed during image preparation and ignored without invalidating the decoration.

`qr_ready` must be a YAML boolean and defaults to `true`. When false, QR generation is intentionally suppressed for this selected decoration regardless of the presentation-level QR setting. A malformed value produces a warning and uses the default.

The optional directional offsets are nonnegative integer distances in design-canvas pixels, measured inward from their named edges. Booleans, strings, fractional values, nulls, and other types are invalid. `qr_centered` accepts only one scalar YAML string, `horizontal` or `vertical`; lists, mappings, null, and other values are invalid. Horizontally, at most one of `qr_from_left`, `qr_from_right`, or `qr_centered: horizontal` may be supplied. Vertically, at most one of `qr_from_top`, `qr_from_bottom`, or `qr_centered: vertical` may be supplied. Simultaneous horizontal and vertical centering is not supported. An unspecified horizontal axis defaults to `qr_from_right: 20`; an unspecified vertical axis defaults to `qr_from_bottom: 20`. These defaults apply independently, including when there is no selected decoration.

Offsets and centering position the complete QR allocation from the selected design canvas's edges or center. They are independent of `presentation_insets` and decoration slice geometry. A malformed value, conflicting anchors, or out-of-bounds allocation disables QR for that preparation with an actionable warning. Refrain does not infer precedence, fall back to another position, clamp the allocation, or exclude the otherwise valid decoration. Map the allocation to presentation-canvas coordinates and evaluate raster viability there; insufficient presentation-canvas pixels disables QR with a warning while allowing literary preparation to continue. QR is not generated, positioned, resized, or rerasterized for the output image. Any required final resize distorts it only as part of the complete image.

The application owns a fixed 246 × 246 design-canvas allocation, including the complete four-module quiet zone. Decorations position this allocation but cannot change its dimensions, define a separate QR region, or configure the payload or encoding. Refrain maps all allocation edges independently to the presentation canvas and chooses the largest integer module size that fits the resulting rectangle. See [QR generation and conditional artwork](ARCHITECTURE.md#qr-generation-and-conditional-artwork) for the production raster contract.

Each `layers` item is a mapping with the following fields:

| Field | Type | Required | Default |
|---|---|---|---|
| `image` | Relative single-frame RGB or RGBA PNG path | Yes | — |
| `method` | `"contain"`, `"cover"`, or `"nine-slice"` | No | `"contain"` |
| `slices` | Nine-slice parameter mapping | Only for `"nine-slice"` | — |
| `condition` | `"always"`, `"qr"`, or `"no-qr"` | No | `"always"` |
| `tintable` | Boolean | No | `true` |

For full-canvas artwork, 3840 × 2400 pixels is the reference-quality authoring size. `method` defaults to `contain`; omitting it is equivalent to explicitly setting `method: contain`. `contain` preserves aspect ratio, scales the source image to fit, and centers it on the design canvas with transparent margins as needed. `cover` preserves aspect ratio, uniformly scales the source until it covers the selected design canvas, then crops excess artwork symmetrically around its center. For example, a 3840 × 2400 image used with `cover` on the 3200 × 2400 design canvas is cropped by 320 pixels from each horizontal edge. Cover uses the source dimensions directly for this transform, not an intermediate reference-envelope scale. A smaller custom PNG may be enlarged, but that cannot restore image detail and may reduce sharpness; the source dimensions do not establish an alternate reference coordinate system. `contain` and `cover` accept no `slices` mapping. `nine-slice` requires a `slices` mapping:

| Field | Type | Required | Default |
|---|---|---|---|
| `slices.left` | Nonnegative source-image pixel distance | Yes | — |
| `slices.right` | Nonnegative source-image pixel distance | Yes | — |
| `slices.top` | Nonnegative source-image pixel distance | Yes | — |
| `slices.bottom` | Nonnegative source-image pixel distance | Yes | — |
| `slices.horizontal` | `"stretch"` or `"crop"` | No | `"stretch"` |
| `slices.vertical` | `"stretch"` or `"crop"` | No | `"stretch"` |

The four distances partition the source image directly into nine regions in its actual source-image pixel coordinates, regardless of its dimensions. Booleans and non-integer measurements are invalid. Left and right distances may not exceed the source width in total; top and bottom may not exceed its height. Slice boundaries must resolve to valid source regions. Do not scale the source image or its slice boundaries through the 3840 × 2400 reference envelope. Each configured distance is also the preserved edge thickness on the design canvas, numerically 1:1, regardless of the source image's overall dimensions. Crop retains edge scale and removes equal amounts from opposite ends of that edge segment; when the destination segment is longer than its source, reject the transformation. Stretch adapts an edge along its length. The center stretches in both dimensions. Design canvases too small to preserve the opposing edge thicknesses are invalid. Geometry and rounding follow the deterministic architecture contract.

`condition: always` includes the layer regardless of QR availability; `qr` includes it only when QR is effectively available; `no-qr` includes it only when QR is effectively unavailable. Availability includes presentation-level policy, the selected decoration's `qr_ready` preference, valid placement, and sufficient presentation-canvas pixels. A condition never changes the order of the remaining layers. Invalid conditions, methods, parameter combinations, paths, or source images exclude the containing decoration with an actionable diagnostic. A malformed `tintable` value produces a warning and uses `true`.

The effective tintability of each layer is `decoration.tintable AND layer.tintable`. Both values default to `true`. When any layer is effectively tintable, Refrain selects one decoration color according to the precedence below; successful selection activates tinting. There is no separate activation setting or field. Artwork intended to retain authored RGB must set `tintable: false` at the decoration or layer level. Per-layer palette selection is not supported. Tinting replaces RGB while preserving source alpha.

#### Default decoration pool

The optional `layout.decorations.default` field is a nonempty sequence of registered decoration identifiers and/or `"none"`.

For example:

```yaml
layout:
  decorations:
    default:
      - "none"
      - "botanical-corners"
      - "lower-flourish"
```

When omitted, the default decoration pool is `["none"]`.

The effective pool contains distinct, usable identifiers. Invalid or unavailable identifiers are excluded with warnings, and duplicates are ignored after their first occurrence.

Each member has equal selection probability.

A registered decoration outside the default pool remains available for explicit content-entry selection.

An explicitly configured pool with no usable members falls back to `["none"]` with a warning.

Decorations have no repetition history or selection weights.

Discovery does not change pool membership. Bundled identifiers cannot be shadowed by custom assets. If multiple custom decorations share an identifier, all are excluded and their package locations are reported. The same identifier may be used in different categories.

#### Default decoration color pool

The optional `layout.decorations.colors` field is a nonempty sequence of identifiers from the shared top-level `palette`. When omitted, the effective pool is `["black"]`.

Invalid, unavailable, or duplicate identifiers are excluded with diagnostics. If no usable identifier remains, the pool falls back to `["black"]`. Each distinct usable identifier has equal selection probability.

### Default text-color pool

`layout.text.colors` is an optional nonempty sequence of palette identifiers. When omitted, the effective pool is `["black"]`.

The effective pool contains distinct identifiers registered in the effective palette. Invalid, unavailable, or duplicate members are excluded with warnings. If no usable member remains, the pool falls back to `["black"]`.

Each effective member has equal selection probability. A configured override of `palette.black` applies whenever selection resolves to `black`.

### Background and decoration resolution

For each selected quotation, Refrain resolves the decoration before resolving the font and background.

An available explicit content-entry decoration takes precedence over the default decoration pool. The value `"none"` suppresses decoration selection.

When no explicit decoration is available, Refrain selects from the effective default decoration pool.

First, Refrain selects exactly one font bundle using the existing precedence:

1. An available explicit content-entry font.
2. The selected decoration's available preferred font.
3. Automatic selection from the effective default font pool.

Each literary role then resolves a face within that one selected bundle, independently, in this order:

1. The content entry's `font_faces` preference.
2. The selected decoration's `font_faces` preference.
3. The selected font bundle's `font_faces` preference.
4. `layout.fonts.font_faces`.
5. The bundle's `regular` face.

The first defined preference wins, including an explicit `regular`. If that winning face is unavailable or unusable, that role uses `regular` with a warning; lower-priority preferences are not consulted. A role never selects another bundle. The selected decoration's face preferences apply even when the content entry selected a different bundle.

For backgrounds, precedence is:

1. An available explicit content-entry background, including `"none"`.
2. The selected decoration's available preferred background, including `"none"`.
3. Automatic selection from the effective default background pool.

An unavailable explicit content-entry preference produces a warning and falls back to the next applicable selection level. It does not invalidate the otherwise valid entry.

The literary text color is resolved after the decoration has been selected, using the first level with one or more usable palette identifiers:

1. The content entry's `text_color`.
2. The selected decoration's `text_color`.
3. The effective `layout.text.colors` pool.
4. The built-in `black` fallback.

Invalid, unavailable, or duplicate identifiers are excluded with diagnostics. Selection is uniform among distinct usable identifiers at one level; candidates from different levels are never combined. Resolve the selected palette identifier and RGB value for the complete image preparation.

Decoration colour is resolved once for the selected decoration when at least one layer has effective tintability (`decoration.tintable AND layer.tintable`), using the first level with usable candidates:

1. The content entry's `decoration_color`.
2. The selected decoration's `decoration_color`.
3. The effective `layout.decorations.colors` pool.
4. The built-in `black` fallback.

Invalid and unavailable identifiers are excluded with diagnostics. Duplicate identifiers do not add selection weight. The first level with usable candidates is selected uniformly without combining levels. A successful selection activates tinting; if no layer is effectively tintable, no color is resolved.

Tinting replaces RGB only on effectively tintable layers with the single palette colour selected for the complete preparation and preserves each original alpha channel. No per-layer palette selection is supported.

An unavailable decoration font or background preference is ignored with a warning, without invalidating an otherwise usable decoration.

An absent decoration preference does not prevent explicit content-entry resource selection or automatic selection from the corresponding default pool.

The selected decoration's complete inset override applies when present; otherwise the global insets apply.

Content-level fields in this document express presentation preferences. The selected entry's preferences needed to interpret or present the committed quotation are captured in its daily selection record; regeneration does not reread the original content entry, and later edits do not change those captured preferences. Their resolved resources, colors, output geometry, effective insets, QR availability, ordered layers, and transformations are derived during image preparation and are not committed as resolved rendering decisions.

All variants generated together use consistent presentation-wide choices from the captured preferences, current configuration, and available assets. Raster-dependent geometry, wrapping, fitted font pixel sizes, QR viability and module size, and conditional QR/no-QR decoration layers may differ by output specification. A valid cached image set is reused even when those inputs change. If a new set must be generated, the captured preferences are resolved against current inputs and the resulting visual choices may differ.

The presentation-level QR policy defaults to enabled. Effective QR availability is resolved for each output specification using that policy, the selected decoration's `qr_ready` value, valid in-bounds design-space placement, and sufficient presentation-canvas pixels for at least one pixel per QR module. Resolve this complete decision before selecting conditional decoration layers. QR rasterization and composition occur later on the presentation canvas after literary rendering; layer `condition` values select artwork but do not enable or disable QR generation.

The handling of missing resources during regeneration is defined in `docs/ARCHITECTURE.md`.

### Automatic quotation fitting

The `layout.text` mapping defines the permitted font-size bounds for the primary quotation.

| Field | Type | Required |
|---|---|---|
| `layout.text.min_font_size` | Positive design-canvas pixel integer | Yes |
| `layout.text.max_font_size` | Positive design-canvas pixel integer | Yes |

For example:

```yaml
layout:
  text:
    min_font_size: 28
    max_font_size: 100
```

Configured font-size bounds are design-canvas pixel measurements. Scale the effective bounds to presentation-canvas pixels before fitting and rendering; do not derive them from aspect-mismatched output-image dimensions.

The maximum must be greater than or equal to the minimum.

These fields define the acceptable range for automatic quotation sizing rather than specifying a fixed font size.

The bounds apply to the primary quotation, not automatically to source or attribution text.

The rendering and text-fitting behavior is defined in `docs/ARCHITECTURE.md`, with implementation guidance in `docs/ENGINEERING.md`.

### Initial layout limitations

Version 0.1 provides one presentation layout with two built-in literary presentation styles, optional background images, and optional decorative overlays.

The initial public format does not define:

- arbitrary layout templates;
- custom drawing commands;
- independent positioning of every presentation field;
- direct per-entry presentation-inset values;
- per-entry font-size overrides;
- per-quotation presentation-style or visual-resource overrides;
- user-defined literary presentation styles;
- configurable source and attribution regions;
- configurable concealment effects for unrevealed fields;
- automatic selection among fonts based on fitting results;
- automatic foreground/background contrast analysis;
- arbitrary image transformations or independent artwork placement beyond the documented layer methods and slice fields;
- a general-purpose theme engine.

Decorations may define presentation insets, but content entries reference decorations by identifier rather than supplying inset values.

Additional built-in literary presentation styles may be introduced in future versions without changing the content-entry structure.

Each destination receives the prepared output variant matching its own output specification. Destinations with identical specifications may share variants; destinations with different specifications receive their own variants. A backend may perform only operations explicitly permitted by its contract, such as pixel-format or orientation conversion; it must not geometrically resize, crop, pad, or otherwise adapt another destination's output image.

The renderer derives the aspect-specific design canvas by cropping the fixed reference envelope. It applies configured design-canvas insets there and scales the resulting geometry to the presentation canvas, as defined in `ARCHITECTURE.md`.

## Content entries

Each content file contains one entry with one or more quotations.

A content entry defines shared metadata and configuration inherited by all its quotations.

Quotations do not have individual metadata or scheduling overrides.

### Example: ordinary quotation entry

```yaml
id: "example-book"

source: "An Example Book"
attribution: "Example Author"

quotations:
  - "A short quotation that fits on one line."

  - >-
    A longer quotation that occupies several
    lines in its YAML representation but
    becomes one displayed paragraph.

  - |-
    A quotation with meaningful
    line breaks.
    Each line remains separate.
```

This entry participates in ordinary daily selection because it declares no special eligibility rules.

Each quotation is a separate selection candidate.

### Entry fields

| Field | Type | Required | Default |
|---|---|---|---|
| `id` | String | Yes | None |
| `quotations` | Nonempty sequence of strings | Yes | None |
| `source` | String | No | Absent |
| `attribution` | String | No | Absent |
| `priority` | Integer | No | `0` |
| `font` | String | No | Selected decoration preference, then automatic selection from default font pool |
| `font_faces` | Mapping of literary roles to face identifiers | No | No role preferences |
| `text_color` | Palette identifier or nonempty sequence of palette identifiers | No | Decoration preference, then global text-color pool |
| `decoration_color` | Palette identifier or nonempty sequence of palette identifiers | No | Selected decoration preference, then global pool, then built-in black |
| `background` | String | No | Decoration preference, then default background pool |
| `decoration` | String | No | Automatic selection from default decoration pool |
| `presentation_style` | String | No | `"centered"` |
| `eligibility` | Sequence of eligibility rules | No | Ordinary eligibility |
| `reveal` | Mapping of reveal overrides | No | Global reveal schedule |

No other entry-level fields are defined for Version 0.1.

All quotations in an entry inherit the entry's metadata, priority, font preference, background preference, decoration preference, presentation style, eligibility, and reveal configuration.

Individual quotations do not have independent overrides.

### Text-color preference

An entry may prefer one palette identifier or provide a nonempty selection pool:

```yaml
text_color: burnt-orange
```

```yaml
text_color:
  - black
  - burnt-orange
```

List members have equal probability; duplicate identifiers do not add weight. Identifiers must be available in the effective palette during image preparation. Unknown, malformed, or unavailable members are diagnosed during preparation and excluded; a preference with no usable members falls through to the next selection level without invalidating the content entry. RGB values are not accepted here.

### Decoration-color preference

An entry may prefer one shared-palette identifier or provide a nonempty selection pool:

```yaml
decoration_color: burnt-orange
```

```yaml
decoration_color:
  - sage-green
  - ink-blue
  - burnt-orange
```

This preference affects only a selected decoration whose manifest sets `tintable: true`. It uses the same validation, equal-probability, and fallback rules as other palette preferences; invalid or unavailable identifiers do not invalidate the content entry. Direct RGB values are not accepted.

### Entry identifiers

`id` identifies the content entry independently of its file path.

Identifiers must be unique across the loaded content library.

Identifiers are case-sensitive.

An identifier must:

- be nonempty;
- contain only ASCII letters, digits, hyphens, and underscores;
- begin with a letter or digit.

Recommended identifiers are short, descriptive, and stable.

For example:

```yaml
id: "amazing-grace"
```

Changing a file's name or location does not change the entry identifier.

Individual quotations do not have separately assigned identifiers.


### Quotations

`quotations` must be a nonempty YAML sequence.

Each element must be a string containing meaningful text.

Empty strings and strings containing only whitespace are invalid.

Quotation strings retain their parsed Unicode content, including intended line breaks and punctuation.

There is no project-defined maximum number of quotations per entry.

Quotation length is not arbitrarily restricted by the content format.

However, a quotation that cannot fit the supported presentation layout may fail presentation validation or image preparation.

Each quotation inherits the same entry-level metadata, eligibility, priority, and reveal schedule.

A quotation requiring different treatment must be placed in a separate content entry.

### Source and attribution

`source` identifies where the selected quotation originates.

`attribution` identifies the person, group, or other entity to which the quotation is attributed.

The exact interpretation depends on the content.

For example:

```yaml
source: "A Song Title"
attribution: "An Artist"
```

Or:

```yaml
source: "A Book Title"
attribution: "An Author"
```

Both fields are optional.

When supplied, each must be a nonempty string.

If omitted, the corresponding reveal stage has no visible field to display.

### Priority

`priority` is a signed integer.

Its default is zero.

For example:

```yaml
priority: 10
```

Negative values are permitted:

```yaml
priority: -5
```

There is no project-defined minimum or maximum priority.

Boolean values and floating-point values are not valid priorities.

All quotations in an entry inherit the same priority.

### Font preference

`font` is an optional string specifying the preferred font for every quotation in the entry.

The value refers to a stable identifier in Refrain's effective font registry. The identifier may represent either a bundled font or a font registered in application configuration.

For example:

```yaml
id: "example-poem"

font: "lora"

source: "A Collection of Poetry"

quotations:
  - |-
    The first line of a poem,
    followed by the second.
```

When supplied, `font` must be a nonempty string.

A registered font does not need to appear in the default font pool to be used as a content-entry preference.

An unregistered font identifier is permitted and does not invalidate an otherwise valid content entry.

This allows content libraries to be shared between installations that have different font collections.

An absent `font` field means that no specific content-entry font preference is expressed. An available preferred font from the selected decoration applies when present; otherwise Refrain selects from the effective default font pool. A valid explicit content-entry or decoration font can be used even when the effective default pool has no usable members. The pool is required only when automatic selection is reached.

An explicit empty string or invalid field type is a validation error.

The resolution of preferred fonts, fallback behavior, and warnings during image preparation are defined in `docs/ARCHITECTURE.md`.

### Font face preferences

The optional top-level `font_faces` mapping expresses face preferences for the entry's `quotation`, `source`, and `attribution` roles and applies to every quotation in the entry.

```yaml
font_faces:
  quotation: handwritten
  source: regular
  attribution: italic
```

Each value must be a case-sensitive face identifier: a nonempty string beginning with an ASCII letter or digit and containing only ASCII letters, digits, hyphens, and underscores. All roles are optional. Unknown roles, non-mapping values, explicit nulls, empty strings, and invalid identifiers reject this content entry without rejecting unrelated entries. A valid identifier need not be provided by every bundle. If the entry's winning preference is unavailable in the selected bundle, Refrain uses that bundle's `regular` face rather than consulting a lower-priority preference.

There is no catch-all face or per-quotation face override. This mapping never selects a font bundle.

### Background preference

The optional `background` field selects a background for every quotation in the content entry.

It accepts a stable background identifier from the effective registry or the reserved value `"none"`.

For example:

```yaml
id: "quiet-morning"
background: "handmade-paper"

quotations:
  - "An example quotation."
```

To request an undecorated paper-white background regardless of the selected decoration's preferred background:

```yaml
background: "none"
```

An absent `background` field allows an available selected decoration's preferred background to apply. If none is available, Refrain selects from the effective default background pool.

An explicit `"none"` overrides both a decoration's preferred background and the default background pool.

Unknown background identifiers are permitted without invalidating otherwise valid content entries. They produce a warning and use the normal background fallback rules.

Empty strings, non-string values, and YAML null are invalid.

The background preference is applied during image preparation. A complete existing image set is reused without reconsidering the preference; a regenerated set uses the current preference and available resources.

### Decoration preference

The optional `decoration` field selects a decoration for every quotation in the content entry.

It accepts a stable decoration identifier from the effective registry or the reserved value `"none"`.

For example:

```yaml
id: "example-poem"
decoration: "lower-flourish"

quotations:
  - |-
    The first line of a poem,
    followed by the second.
```

An explicit `"none"` suppresses the default decoration pool and uses the global presentation insets.

An absent `decoration` field means automatic selection from the effective default decoration pool.

A selected decoration may supply presentation insets, a preferred font, and a preferred background. Explicit content-entry font and background preferences always take precedence over the corresponding decoration preferences.

Unknown decoration identifiers are permitted without invalidating otherwise valid content entries. They produce a warning and use the default decoration pool.

Empty strings, non-string values, and YAML null are invalid.

The decoration preference and its insets are applied during image preparation. A complete existing image set is reused without reconsidering them; a regenerated set uses current preferences and available resources.

### Presentation style

The optional `presentation_style` field selects the built-in style used to arrange the literary composition.

It is defined at the content-entry level and applies to every quotation in that entry.

Version 0.1 supports the following values:

| Value | Behavior |
|---|---|
| `"centered"` | Each quotation line is independently centered horizontally. The quotation block is vertically centered within its allocated space. |
| `"left-aligned"` | Quotation lines share a common left edge. The complete text block remains horizontally centered according to its widest rendered line, rather than anchored to the literary rectangle's left edge, and vertically centered within its allocated space. The byline is right-aligned within the literary rectangle. |

For example:

```yaml
id: "example-left-aligned"

presentation_style: "left-aligned"

source: "An Example Book"
attribution: "An Author"

quotations:
  - |-
    A longer quotation whose lines
    are better presented with a
    common left margin.
```

The default is `"centered"` when the field is omitted.

Style identifiers are case-sensitive.

Unknown identifiers, empty strings, and non-string values are validation errors.

The selected style governs the composition's layout. Both initial styles use consistent subordinate presentation for source and attribution.

The selected content's presentation style is retained in its daily selection record so the quotation remains interpretable if its source entry becomes unavailable.

Version 0.1 does not support per-quotation style overrides.

Future releases may introduce additional built-in style identifiers. Content using an unsupported style identifier is invalid rather than silently falling back to another style.

## Eligibility rules

An entry may define one or more eligibility rules.

Each rule identifies either ordinary eligibility or a supported calendar-date pattern.

### Ordinary eligibility

An entry without an `eligibility` field participates in ordinary selection.

Ordinary eligibility may also be declared explicitly:

```yaml
eligibility:
  - ordinary: true
```

Explicit ordinary eligibility is useful when an entry also declares special-date eligibility.

### Date-specific eligibility

Date-specific rules use calendar components with explicit field names.

For example:

```yaml
eligibility:
  - month: 10
    day: 17
```

This matches October 17 each year.

Supported date-rule forms are:

| Fields | Meaning | Specificity |
|---|---|---|
| `year`, `month`, `day` | One calendar date | Year-month-day |
| `month`, `day` | One recurring annual date | Month-day |
| `day` | One day of each month | Day |
| `month` | Every day in one month | Month |

Year-only and year-month rules are not supported in Version 0.1.

A rule must match exactly one of the supported forms.

### Example: several eligibility rules

```yaml
id: "family-celebration"

eligibility:
  - year: 2026
    month: 10
    day: 17
  - month: 10
    day: 17
  - ordinary: true

quotations:
  - "An example quotation."
```

The rules are alternatives.

An entry is eligible if any rule matches the current display date.

If several rules match, the entry takes the highest matching specificity.

The order of rules in the YAML file does not affect precedence.

Including ordinary eligibility makes the entry available for ordinary selection on dates where it has no matching special-date rule.

### Date-field validation

- `year` must be a positive integer.
- `month` must be an integer from 1 through 12.
- `day` must be an integer from 1 through 31.
- `ordinary` must be the boolean value `true`.
- A date rule cannot combine `ordinary` with calendar components.
- An empty eligibility sequence is invalid.
- Date fields must describe a supported eligibility rule.

For a year-month-day rule, the specified calendar date must exist.

For a month-day rule, the calendar combination must exist in at least one year.

February 29 is valid in a recurring month-day rule and matches only in leap years.

A day-of-month rule matches only months containing that day.

For example, `day: 31` does not match April.

### Eligibility interpretation

Eligibility rules define the calendar conditions under which a content entry may participate in selection.

When several rules match the same display date, Refrain uses the highest applicable specificity.

The supported specificity categories are:

1. Year-month-day
2. Month-day
3. Day
4. Month
5. Ordinary

The field combinations defining these categories are specified under `### Date-specific eligibility`.

Selection precedence, repetition history, priority evaluation, and pool exhaustion are defined in `docs/ARCHITECTURE.md`.

## Per-entry reveal overrides

An entry may override the global reveal times of source and attribution.

For example:

```yaml
id: "early-attribution"

source: "An Example Book"
attribution: "Example Author"

reveal:
  source: "09:00"
  attribution: "09:00"

quotations:
  - "A quotation whose metadata is revealed together."
```

Only the overridden fields need to be specified.

Unspecified fields inherit their global values.

The primary quotation always begins at the configured display-day start.

An entry cannot override the quotation reveal time in Version 0.1.

The effective reveal schedule is resolved when preparing the daily selection record.

The selected quotation, its captured content-level presentation preferences, and its resolved reveal schedule do not change if the original entry or global configuration later changes. Regeneration does not reread the original entry. If regeneration is necessary, captured preferences are resolved against current application configuration and available assets, so the resulting image set may reflect those current inputs.

### Override validation

Each supplied reveal value must be a valid `HH:MM` local time.

Effective reveal times must not precede the configured day start.

Source and attribution times must not precede the quotation time.

Source and attribution may appear at the same time or in either order.

An override is invalid if it produces an unsupported or contradictory effective schedule.

## Complete content examples

### Ordinary song entry

```yaml
id: "example-song"

source: "An Example Song"
attribution: "An Example Artist"

quotations:
  - >-
    This is the first example
    quotation from the song.

  - |-
    This is the second example,
    with intentional line breaks.
    Those line breaks are retained.
```

### High-priority recurring annual entry

```yaml
id: "october-celebration"

source: "A Celebration"
priority: 100

eligibility:
  - month: 10
    day: 17

quotations:
  - "A message for this particular day."

  - "Another message for this same occasion."
```

### One-time special-date entry

```yaml
id: "special-event-2026"

priority: 5

eligibility:
  - year: 2026
    month: 12
    day: 25

quotations:
  - "A message for one particular calendar date."
```

### Monthly entry

```yaml
id: "november-reflection"

eligibility:
  - month: 11

quotations:
  - "A quotation eligible throughout November."
```

### Day-of-month entry

```yaml
id: "first-of-month"

eligibility:
  - day: 1

quotations:
  - "A quotation eligible on the first of every month."
```

### Mixed ordinary and special-date entry

```yaml
id: "multi-purpose"

priority: 2

eligibility:
  - month: 10
    day: 17
  - ordinary: true

reveal:
  source: "10:00"

source: "An Example Source"
attribution: "An Example Author"

quotations:
  - "A quotation with more than one eligibility context."
```


## Validation and diagnostics

Application configuration and content files must be parsed and validated according to their respective schemas before their values are accepted.

Validation distinguishes fatal errors, recoverable problems, and informational use of documented defaults.

Diagnostics must identify the affected file and field or entry where applicable, with sufficient information to correct the problem.

### Application configuration

Application configuration is interpreted into an effective configuration containing accepted values, documented defaults, and usable discovered resources.

A configuration problem is fatal only when Refrain cannot establish a valid effective value required for the operation.

Apply the following rules:

- A missing optional value with a documented default uses that default and is reported at informational severity.
- An explicitly supplied invalid optional value with a documented default produces a warning and uses that default.
- An invalid optional value without a documented default produces a warning and is ignored.
- An unrecognized configuration field produces a warning and is ignored.
- A missing or invalid required value without a usable fallback produces an error.
- Output `aspect_ratio` and `resolution` fields must be supplied together or both omitted; supplying only one, or supplying either field for the fixed Waveshare backend, is a configuration error.
- An unavailable or invalid discovered font bundle produces a warning and is excluded from the effective font registry.
- An unavailable or unregistered default-pool identifier produces a warning and is excluded from the effective default pool.
- An unavailable or invalid discovered background or decoration produces a warning and is excluded from its effective registry.
- An unavailable or unregistered default background or decoration identifier produces a warning and is excluded from its effective default pool.
- An unavailable optional font preference on an otherwise usable decoration is ignored with a warning.
- A malformed `font_faces` mapping in global configuration, a decoration manifest, or a font-bundle manifest is warned about and ignored without invalidating the containing resource.
- A missing background or decoration pool defaults to `["none"]`.
- A configured background or decoration pool with no usable members falls back to `["none"]` with a warning.
- Invalid decoration insets, layer definitions, or nine-slice boundaries exclude that decoration without invalidating unrelated resources.
- An unavailable optional background preference on an otherwise usable decoration is ignored with a warning.

Fallback values must be defined by this specification. Validation must not invent undocumented defaults.

Recoverable problems must not prevent other valid configuration values from being accepted.

Invalid configuration values must not be silently accepted as valid.

Configuration warnings must identify the field and explain whether it was ignored, excluded, or replaced by a documented default.

Informational notices for omitted optional values may be consolidated to avoid excessive startup output.

The effective configuration must satisfy the requirements of the operation being performed.

A failed configuration load must not overwrite the configuration file or mutate authoritative operational state.

### Content library

Content files must use valid YAML syntax and conform to the content-entry schema.

Content validation includes:

- valid YAML syntax and supported YAML constructs;
- valid entry identifiers and uniqueness across accepted entries;
- required fields and supported field names;
- permitted value types;
- nonempty quotation collections and quotation strings;
- valid integer priorities;
- supported eligibility rules and valid calendar values;
- valid reveal schedules and presentation settings.
- valid `font_faces` role mappings and face identifiers.

Invalid or unrecognized fields make the affected content entry invalid.

A YAML file that cannot be parsed is excluded in its entirety, with an actionable warning.

A syntactically valid file containing independently represented content entries may retain valid entries while excluding invalid entries, where the file format permits them to be validated separately.

An invalid entry must not invalidate otherwise valid entries or files.

Conflicting duplicate entry identifiers must not be resolved by arbitrary filesystem enumeration order. All entries participating in a detected identifier conflict are excluded, with diagnostics identifying the conflicting entries.

Content entries whose preferred font, background, or decoration identifier is unavailable remain valid when the identifier itself satisfies the field's syntax rules. Resource fallback behavior is defined in `docs/ARCHITECTURE.md`.

Unlike unavailable resource preferences, a malformed content-entry `font_faces` mapping rejects only that entry.

The effective content library consists of accepted, validated entries.

A partial content library is usable when source discovery and loading complete and at least one valid quotation remains.

Individual invalid files or entries do not prevent the effective library from being accepted.

A missing or inaccessible content directory, failed source discovery, a directory containing no content files, or a library with no valid quotations is a library-level failure.

A library-level failure must not be interpreted as an intentionally empty library for repetition-history cleanup.

Content validation must not silently reinterpret malformed entries or invent missing quotations.

### Diagnostic severity

Use the following severity meanings:

- `INFO`: A documented default was applied because an optional value was omitted.
- `WARNING`: A recoverable configuration problem or rejected content item was encountered; usable configuration or content remains available.
- `ERROR`: A required effective configuration or content-library condition cannot be satisfied.

Warnings must be actionable and must not repeatedly flood normal application logs.

Logging implementation and process-output behavior are defined in `docs/ENGINEERING.md`.

### Recovery and repetition history

A usable effective content library may contain rejected files or entries.

When Refrain makes a new selection, repetition-history cleanup uses the quotations belonging to the accepted effective library.

Quotations belonging exclusively to rejected entries may therefore lose their repetition status. If those entries are later corrected and accepted, their quotations may re-enter selection as unused.

This behavior is intentional.

Repetition-history cleanup must not occur when library discovery fails or the effective content library contains no valid quotations.

Cleanup is committed only as part of a successful new selection.

An already committed daily selection remains independent of subsequent changes or failures in its original content library.

Runtime selection, recovery, and scheduling behavior are defined in `docs/ARCHITECTURE.md`.

## Compatibility and extension

The initial schemas are the public interface for Version 0.1 content and application configuration.

New fields must be introduced deliberately and documented here.

Existing field meanings must not change silently.

Unknown application-configuration fields are ignored with warnings. They must not be interpreted as arbitrary extensions or executable instructions.

Unknown content-entry fields invalidate the affected entry without invalidating unrelated entries or files.

Version-specific migration support may be introduced when a real compatibility requirement emerges.

Refrain must not interpret arbitrary YAML metadata as executable instructions, renderer commands, or external actions.

The eventual content editor, if implemented, must produce files conforming to this specification.

## Out of scope

The initial formats do not define:

- per-quotation metadata, font, background, or decoration overrides;
- arbitrary eligibility expressions;
- weekday or holiday calculation rules;
- complex recurrence expressions;
- dynamically downloaded content or visual resources;
- inline scripts;
- arbitrary presentation templates;
- direct per-entry presentation insets or font-size limits;
- per-entry layout customization beyond the defined resource preferences and presentation style;
- automatic font-family selection based on text-fitting performance;
- resource repetition histories or weighted resource selection;
- automatic contrast adjustment or foreground recolouring;
- arbitrary graphical transformations or decoration placement instructions;
- per-entry QR settings;
- general-purpose themes or style scripting;
- content-triggered external actions;
- independent presentation layouts for individual display backends;
- interactive content editing.

These capabilities may be evaluated for later releases according to the roadmap.