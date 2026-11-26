# Application Configuration

This document specifies Refrain's application-configuration YAML format, including destinations, storage, scheduling, presentation settings, resource selection, and validation requirements.

## YAML document

Application configuration is conventionally named `config.yaml`.

- Use UTF-8 and exactly one YAML document containing one top-level mapping.
- Use spaces for indentation; two spaces are recommended.
- Use ordinary mappings, sequences, strings, integers, and booleans as specified below.
- Do not use custom tags, executable object constructors, anchors, aliases, merge keys, duplicate mapping keys, or implicit application-specific expressions.
- Quote values resembling dates, times, numbers, or booleans when a string is required. Unquoted scalars are accepted only when the parser produces the required type.
- Boolean values do not satisfy integer fields. YAML null does not satisfy a string, integer, boolean, sequence, or mapping field unless expressly permitted below.

Each executable interprets and validates only the top-level configuration fields relevant to its operation. All other top-level fields are ignored without diagnostics. Executables must not require knowledge of configuration fields owned by other executables.

Within consumed configuration mappings, unknown fields are warned about and ignored unless a stricter validation rule is explicitly defined.

Shared YAML document parsing requirements apply to the entire configuration document.

## Complete example

This example demonstrates all compatible application settings, including every supported destination type and override field. It is a valid configuration under this specification, assuming the referenced bundled `lora` font is usable. The content directory must contain usable content for operations that require a content library. The explicit paths and resource selections are examples, not additional defaults.

```yaml
destinations:
  - id: "desktop"
    type: "window"
    audience: "internal"
    aspect_ratio: "16:9"
    resolution: [1920, 1080]

  - id: "epaper"
    type: "waveshare-13in3-e"
    audience: "internal"
    overrides:
      background: "none"
      decoration: "none"
      font: "lora"
      text_color: "black"
      decoration_color: "sage"
      qr: "none"

  - id: "web-a"
    type: "publish"
    audience: "external"
    aspect_ratio: "5:3"
    resolution: [1920, 1152]
    overrides:
      background: "none"

  - id: "web-b"
    type: "publish"
    audience: "internal"
    aspect_ratio: "16:10"
    resolution: [3840, 2400]

image-server:
  destinations: ["web-a"]
  host: "127.0.0.1"
  port: 8080

storage:
  content: "content"
  state: "state"
  artifacts: "cache/artifacts"
  publish: "publication"

scheduling:
  day_start: "05:00"
  reveal:
    source: "12:00"
    attribution: "18:00"

presentation:
  insets:
    left: 384
    right: 384
    top: 324
    bottom: 324
  information_view:
    duration: 60
  qr:
    external: "https://github.com/ControlForgeHQ/refrain"
    internal: "https://github.com/ControlForgeHQ/refrain"

palette:
  black: "#000000"
  sage: "#8A9B79"
  slate: "#52657A"
  terracotta: "#C65A20"

fonts:
  pools:
    default: ["@literary"]
    literary: ["lora"]
    complete: ["@builtin"]
  faces:
    quotation: "regular"
    source: "italic"
    attribution: "italic"

text:
  min_font_size: 56
  max_font_size: 200
  colors:
    pools:
      default: ["@neutral"]
      neutral: ["black", "slate"]
      complete: ["@builtin"]

backgrounds:
  pools:
    default: ["none"]
    complete: ["@builtin"]

decorations:
  pools:
    default: ["none"]
    complete: ["@builtin"]
  colors:
    pools:
      default: ["@muted"]
      muted: ["black", "sage", "slate"]
      complete: ["@builtin"]
```

The installed distribution supplies `config.default.yaml` as an editable starting point. Its explicit selections are not universal defaults for omitted fields. In particular, its `@builtin` pools and italic source-face preference are configured choices. Initialization and preservation of installed configuration are defined in [CLI](../CLI.md#initialize) and [Initialization](../specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#initialization).

## Destinations

`destinations` is required and must be a nonempty sequence of mappings.

| Field | Type | Required | Constraint |
|---|---|---|---|
| `id` | String | Yes | Globally unique; matches `[A-Za-z0-9][A-Za-z0-9_-]*`; at most 255 ASCII characters. |
| `type` | String | Yes | Exactly `window`, `waveshare-13in3-e`, or `publish`. |
| `audience` | String | Yes | Exactly `external` or `internal`; no default or fallback. |
| `aspect_ratio` | String | Paired with `resolution` where supported | Exactly `4:3`, `5:3`, `16:9`, or `16:10`. |
| `resolution` | Sequence of two integers | Paired with `aspect_ratio` where supported | Positive pixel dimensions in width, height order. |
| `overrides` | Mapping | No | Only the restricted fields below. |

Identifiers and enumerated values are case-sensitive. Missing, null, empty, non-string, or unsupported audiences are errors. Invalid or duplicate destination IDs and capacity excesses are errors. `all` is an ordinary valid ID; `@all` is reserved for CLI publication selection and does not satisfy the ID syntax.

For `publish` destinations, IDs must additionally avoid Windows-reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, and `LPT1`–`LPT9`), regardless of case. IDs of different `publish` destinations must also be unique under case-insensitive comparison, ensuring their publication directories remain distinct on case-insensitive filesystems.

| Destination type | Maximum configured destinations | Default aspect ratio | Default resolution | Explicit geometry |
|---|---:|---|---|---|
| `window` | 1 | `16:9` | `[1920, 1080]` | Supply both fields or neither. |
| `waveshare-13in3-e` | 1 | Fixed `4:3` | Fixed `[1600, 1200]` | Both fields prohibited. |
| `publish` | Multiple | `16:10` | `[3840, 2400]` | Supply both fields or neither. |

A declared aspect ratio and requested resolution are independent values. Dimensions need not exactly match the aspect ratio; `aspect_ratio: "4:3"` with `resolution: [1600, 1190]` is valid. Each requested width must be between 1 and 3840 pixels and each height between 1 and 2400 pixels, independently; square and portrait outputs are valid. Unsupported aspect ratios, boolean or non-integer dimensions, zero or negative dimensions, incomplete geometry pairs, and geometry fields on the fixed Waveshare destination are errors.

The following are alternative declarations, not fields to combine in one destination:

```yaml
# Use the window's default aspect ratio and resolution.
destinations:
  - id: "desktop"
    type: "window"
    audience: "internal"

fonts:
  pools:
    default: ["@builtin"]
```

```yaml
# Supply both configurable geometry fields.
destinations:
  - id: "desktop"
    type: "window"
    audience: "internal"
    aspect_ratio: "4:3"
    resolution: [1600, 1190]

fonts:
  pools:
    default: ["@builtin"]
```

Do not combine either configurable geometry form with a Waveshare destination. Its valid declaration is shown without geometry fields in the complete example.

A `publish` destination has no destination-local filesystem path. Its directory is a direct child of the effective `storage.publish` root, named from its destination ID. Publication file structures belong to [Publication manifest](PUBLICATION.md#manifest-fields).

### Destination overrides

An optional `overrides` mapping supports only these six fields:

| Field | Valid value | Meaning |
|---|---|---|
| `background` | String `"none"` | Suppress the canonical background. |
| `decoration` | String `"none"` | Suppress the canonical decoration. |
| `font` | One registered font-bundle identifier | Replace the canonical font bundle. |
| `text_color` | One identifier in the effective palette | Replace the canonical text color. |
| `decoration_color` | One identifier in the effective palette | Replace the canonical decoration color. |
| `qr` | String `"none"` | Suppress literary QR for this destination. |

All values are case-sensitive strings. A supplied `overrides` value must be a mapping. An empty mapping is valid. Omitted properties retain their canonical values.

These fields do not accept pool references, fallback lists, direct RGB values, booleans, or nested QR mappings. Background and decoration overrides cannot select alternative resources. Unknown keys, wrong types, unknown font or palette identifiers, and unsupported values are configuration errors, with no warning-and-ignore or fallback substitution.

Overrides affect scheduled image preparation. They do not define independent artistic selection or transformations of finished transient images. Decoration suppression uses global insets and quotation font bounds, including their documented defaults; background suppression does not reset geometry. A decoration color has no rendering effect without a decoration layer. Runtime application, face resolution, grouping, and geometry validation belong to [Presentation and Rendering](../specifications/50-PRESENTATION_AND_RENDERING.md).

## Independent image-server settings

Only `refrain-image-server` interprets and validates the `image-server` section.

The standalone image server validates the required `image-server` settings, applicable publication destination definitions, and storage paths needed for its own operation. It does not require content-library loading, font-resource resolution, artistic preparation, or other resident-only services merely to consume verified publication datasets.

The optional top-level `image-server` mapping configures the separately supervised `refrain-image-server` consumer and contains only:

| Field | Type | Default | Constraint |
|---|---|---|---|
| `destinations` | Nonempty sequence of strings | Required; no default | Unique IDs of configured `publish` destinations. |
| `host` | String | `"127.0.0.1"` | IPv4 or IPv6 address literal, or a hostname valid after IDNA conversion. Hostnames may have one trailing dot; the converted name must be 1–253 ASCII characters, with dot-separated labels of 1–63 characters containing letters, digits, or internal hyphens. |
| `port` | Integer | `8080` | 1 through 65535, inclusive. |

Every `destinations` member must identify an existing configured `publish` destination. Duplicates, non-string values, unknown IDs, non-`publish` IDs, and `@all` are invalid. No destination is included implicitly.

A present section must be a mapping containing the required nonempty `destinations` sequence; an empty mapping or null section is invalid:

```yaml
image-server:
  destinations: ["web-a"]
```

This is a section fragment to use in an otherwise complete configuration. Omit the section when no image-server consumer is configured. Invalid optional host or port values produce warnings and use their defaults.

Image-server behavior and network-exposure requirements are defined in [Image Server](../specifications/75-IMAGE_SERVER.md).

## Storage

The optional `storage` mapping contains only the following nonempty path strings:

| Field | Default when omitted |
|---|---|
| `content` | `content/` beside the selected configuration file. |
| `state` | Platform-standard state directory. |
| `artifacts` | Platform-standard prepared-artifact directory. |
| `publish` | Platform-standard publication root. |

`storage.state` identifies a directory containing Refrain's persistent state files, each with a fixed filename:

| Filename | Purpose |
|---|---|
| `state.json` | Authoritative operational state. |
| `global-history.jsonl` | Chronological global selection history. |
| `publication.json` | Current publication checkpoint. |

The serialized formats of `state.json` and `global-history.jsonl` are defined in [Operational State and Global History](STATE.md). The format of `publication.json` is defined in [Publication metadata](PUBLICATION.md#metadata-document-shapes).

Global history is not independently configurable. Its existing recording, rotation, and retention semantics are unchanged.

Absolute paths are used as specified. Relative paths are resolved from the directory containing the selected configuration file, not from the current working directory.

Each omitted storage path retains its independent platform-standard default. Selecting a different configuration file or setting one storage path does not relocate the others. Only omitted `storage.content` follows the selected configuration file.

Standard storage-directory locations and platform-specific path-resolution rules are defined in [Platform paths and publication root](../specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#platform-paths-and-publication-root).

Platform path resolution and storage lifecycles belong to [Installation and Service Operation](../specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md).

A supplied `storage` value must be a mapping. An invalid `storage.content` value produces a warning and uses its default. Invalid explicitly supplied `state`, `artifacts`, or `publish` values are errors; they do not fall back to platform paths. Unknown storage fields are warned about and ignored.

## Scheduling

The optional `scheduling` mapping accepts `day_start` and a `reveal` mapping containing `source` and `attribution`.

| Field | Type | Default |
|---|---|---|
| `scheduling.day_start` | Local time string | `"05:00"` |
| `scheduling.reveal.source` | Local time string | `"12:00"` |
| `scheduling.reveal.attribution` | Local time string | `"18:00"` |

Times must use exactly 24-hour `HH:MM` notation: hours `00`–`23` and minutes `00`–`59`. Seconds, timezone suffixes, and loosely formatted strings such as `"6:00"` are unsupported.

All times use the host operating system's local timezone and daylight-saving rules. A configured timezone field is unsupported.

Effective source and attribution reveal times must be on the same local calendar date as, and no earlier than, `day_start`. They may equal `day_start`, equal one another, or occur in either order. The quotation's initial time is `day_start`; there is no global `reveal.quotation` field.

Missing optional times use their defaults. Invalid optional times warn and use documented defaults only if the resulting effective schedule is valid. If a default would precede the accepted `day_start`, supply a valid reveal time; an effective schedule that cannot meet these constraints is an error.

For example, these are alternative valid schedules:

```yaml
scheduling:
  day_start: "05:00"
  reveal:
    source: "12:00"
    attribution: "18:00"
```

```yaml
scheduling:
  day_start: "20:00"
  reveal:
    source: "20:00"
    attribution: "23:00"
```

Reveal times must be on the same local calendar date as the configured day start and must not precede it.

Per-entry reveal declarations are defined in [Content Entries](CONTENT.md#per-entry-reveal-overrides). Display-date calculation, cumulative stages, clock changes, and missed events belong to [Scheduling and Application Lifecycle](../specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md); commitment belongs to [Selection commitment](../specifications/30-SELECTION_AND_PERSISTENCE.md#selection-commitment).

## Presentation defaults

The optional `presentation` mapping accepts `insets`, `information_view`, and `qr`.

### Literary insets

If `presentation.insets` is omitted, its complete default is:

```yaml
presentation:
  insets:
    left: 384
    right: 384
    top: 324
    bottom: 324
```

When supplied, `insets` must be a mapping with all four edges. Each edge must be a nonnegative integer in design-canvas pixels. Partial mappings, negative values, booleans, and non-integer values are errors.

Insets are measured inward from the aspect-specific design canvas, not the requested output image or the full reference envelope.

The aspect-specific design-canvas dimensions are defined in [Image spaces and raster geometry](../specifications/50-PRESENTATION_AND_RENDERING.md#image-spaces-and-raster-geometry).

For the active design canvas, `left + right` must be less than its width and `top + bottom` less than its height. The resulting literary rectangle must have positive width and height.

A selected decoration's complete `presentation_insets` replaces the global mapping; otherwise the global mapping applies. Asset-side declarations are defined in [Assets](ASSETS.md#presentation-insets). Content entries cannot directly specify insets. Scaling, rounding, composition, and fitting requirements belong to [Literary composition and fitting](../specifications/50-PRESENTATION_AND_RENDERING.md#literary-composition-and-fitting).

### Information view

| Field | Type | Default | Constraint |
|---|---|---|---|
| `presentation.information_view.duration` | Integer | `60` | 0 through 300 inclusive, in seconds. |

`information_view` must be a mapping when supplied. A duration of `0` disables automatic startup information-view presentation; `1` through `300` requests that duration. Strings, booleans, floating-point values, negative values, and values greater than 300 are invalid, warn, and use `60`.

This is a startup-presentation setting, not an external request interface or an additional schedule. Timing, initial publication attempts, and lifecycle belong to [Startup information-view timing](../specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#startup-information-view-timing).

### Literary QR

The optional `presentation.qr` mapping defines default QR payloads by audience:

| Field | Type | Default | Constraint |
|---|---|---|---|
| `external` | String or null | `null` | Nonempty UTF-8 string of at most 62 bytes, or null. |
| `internal` | String or null | `null` | Nonempty UTF-8 string of at most 62 bytes, or null. |

Each audience is independent. An omitted or null value supplies no default payload for that audience.

An invalid `qr` mapping warns and uses null for both audiences. An invalid audience value warns and uses null for that audience without affecting the other. Empty strings, oversized payloads, and non-string non-null values are invalid. Unknown keys follow the general optional-configuration validation policy.

Payloads are opaque strings, preserved exactly after YAML parsing. No URL, Wi-Fi, or other payload-specific interpretation is performed.

The installed default configuration explicitly supplies the Refrain repository URL for both audiences. This does not change the application fallback of null for omitted values.

Content-entry overrides are defined in [Content Entries](CONTENT.md#qr-payloads). Payload precedence is defined in [QR payload resolution](../specifications/20-CONTENT_AND_CONFIGURATION.md#qr-payload-resolution). Destination suppression and rendering belong to [Presentation and Rendering](../specifications/50-PRESENTATION_AND_RENDERING.md#qr-placement-and-conditional-artwork).

## Palette

The optional `palette` mapping defines named RGB colors shared by literary text and decoration tint selection.

| Built-in identifier | Default RGB value |
|---|---|
| `black` | `"#000000"` |
| `white` | `"#FFFFFF"` |
| `red` | `"#FF0000"` |
| `yellow` | `"#FFFF00"` |
| `blue` | `"#0000FF"` |
| `green` | `"#00FF00"` |

These are provisional conventional digital RGB values, not calibrated Spectra-6 pigment measurements.

Each configured key must match the case-sensitive ASCII identifier syntax `[A-Za-z0-9][A-Za-z0-9_-]*`. Each value must be a quoted six-digit `"#RRGGBB"` string; hexadecimal digits may be upper- or lowercase.

Custom entries extend the palette. Configuring a built-in identifier replaces its RGB value without removing the identifier. Invalid identifiers or values warn and are ignored; an invalid built-in override leaves its default value in place.

RGB lists and direct RGB values in resource-selection fields are unsupported. Select palette identifiers instead.

## Resources and named pools

Configuration selects registered resources by stable identifier. It does not register arbitrary filesystem paths.

Bundled resources come from package resources. User fonts, backgrounds, and decorations are discovered recursively under `assets/fonts/`, `assets/backgrounds/`, and `assets/decorations/` beside the selected configuration file. An alternate configuration file supplies its own containing directory as the assets root; neither the working directory nor the standard configuration directory supplies additional user assets in that case. `storage.content` is independent of this assets root.

Resource discovery, registration, and validation use the formats and requirements defined in [Assets](ASSETS.md#resource-identifiers-and-discovery). Discovered valid resources are available by identifier even when absent from a default pool. Discovery alone does not add them to a configured pool.

### Pool declarations

There are five independent pool namespaces:

| Category | Pool mapping | Automatic-selection pool | Default when omitted |
|---|---|---|---|
| Font bundles | `fonts.pools` | `fonts.pools.default` | Required; no implicit pool. |
| Backgrounds | `backgrounds.pools` | `backgrounds.pools.default` | `["none"]` |
| Decorations | `decorations.pools` | `decorations.pools.default` | `["none"]` |
| Literary text colors | `text.colors.pools` | `text.colors.pools.default` | `["black"]` |
| Decoration tint colors | `decorations.colors.pools` | `decorations.colors.pools.default` | `["black"]` |

Each containing section, `colors` section, and `pools` value must use the explicit mapping form. A color sequence directly under `text.colors` or `decorations.colors` is unsupported.

Each pool name must match `[A-Za-z0-9][A-Za-z0-9_-]*` and is case-sensitive. Names are unique within a category but may be reused across categories. Names do not conflict with parent settings such as `fonts.faces` or `decorations.colors`.

Each pool value is a sequence of category-appropriate identifiers and/or strings of the form `"@POOL_NAME"`. References stay within their category and may be nested. Background and decoration pools also accept `"none"`, the reserved absence value; it is not a registered asset. Color pools use the shared effective palette.

`default` is the automatic-selection pool. Its declaration is a nonempty sequence. Other named pools may be empty. A nonempty declaration may still resolve to no usable members.

`builtin` is reserved in every category. A user definition named `builtin` warns and is ignored.

| Reserved pool | Membership |
|---|---|
| Font `builtin` | Successfully registered bundled font bundles only. |
| Background `builtin` | Successfully registered bundled backgrounds only; no implicit `none`. |
| Decoration `builtin` | Successfully registered bundled decorations only; no implicit `none`. |
| Text-color `builtin` | `black` |
| Decoration-color `builtin` | `black` |

Custom and invalid assets are excluded from file-backed `builtin` membership. A configured `palette.black` value remains effective in color pools.

An explicit `"@builtin"` opts into changes to valid bundled membership. Other pools retain their configured membership; there is no implicit `@builtin` fallback.

The `@` reference syntax applies only in supported resource-selection positions. It does not apply to paths, palette RGB values, face names, or destination `overrides`.

### Pool validity and effective membership

Invalid pool names or malformed definitions are diagnosed without discarding unrelated valid definitions. Malformed or unknown references and invalid or unavailable identifiers warn and contribute no candidates. Duplicate resolved identifiers contribute one candidate, retaining the first occurrence. Duplicate font and color identifiers are diagnosed. Cyclic pool references are permitted; their expansion is specified in [Named pools and membership](../specifications/20-CONTENT_AND_CONFIGURATION.md#named-pools-and-membership).

Each named pool retains its actual expanded membership, including an empty `default`. Runtime fallbacks do not insert `none` or `black` into an empty named pool. An explicit reference to that pool remains empty; it does not acquire an implicit `builtin` pool.

A missing or malformed required `fonts.pools.default`, including an explicitly empty sequence, is an error. Invalid or unavailable font members are excluded with warnings. A nonempty font declaration whose usable expansion is empty does not by itself prohibit operation with an otherwise usable explicit content or decoration font preference. When no configured font candidate is usable, ordinary preparation uses the unconditional packaged `source-sans-3/regular` fallback without adding it to any named pool.

Missing background or decoration defaults use `["none"]`. Missing color defaults use `["black"]`. Invalid optional default declarations warn; unusable members are excluded. Automatic background, decoration, and color fallbacks are defined in [Canonical resolution and resource precedence](../specifications/50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence), separately from named-pool membership.

### Global font faces

The optional `fonts.faces` mapping accepts only these roles:

| Key | Value |
|---|---|
| `quotation` | One face identifier |
| `source` | One face identifier |
| `attribution` | One face identifier |

Values match `[A-Za-z0-9][A-Za-z0-9_-]*` and are case-sensitive identifiers, not font paths or pool references. Roles may be omitted; omission expresses no preference. There is no implicit italic preference.

A malformed mapping, unsupported role, or invalid identifier warns and causes the mapping to be ignored without invalidating the font registry. A syntactically valid identifier may be absent from the ultimately selected bundle. Its resolution and `regular` fallback belong to [Font bundles, role faces and recovery](../specifications/50-PRESENTATION_AND_RENDERING.md#font-bundles-role-faces-and-recovery).

`fonts.faces` supplies global role preferences; it does not register faces, change bundle selection, or add candidates to pools.

## Quotation font-size bounds

The optional `text` mapping accepts `min_font_size`, `max_font_size`, and `colors`.

| Field | Type | Default | Constraint |
|---|---|---|---|
| `text.min_font_size` | Integer design-canvas pixels | `56` | Greater than zero. |
| `text.max_font_size` | Integer design-canvas pixels | `200` | Greater than zero and at least the effective minimum. |

Bounds default independently when omitted. Explicit invalid bounds, including booleans, strings, floating-point values, nonpositive values, or an inverted effective range, are errors.

These are automatic primary-quotation sizing limits, not a fixed size and not automatic source or attribution limits. Their units are design-canvas pixels, not requested output-image pixels. Content entries cannot directly set these bounds.

## Validation and compatibility

The following validation rules apply according to the configuration ownership and document parsing requirements defined under [YAML document](#yaml-document).

Configuration is accepted as an effective configuration of valid supplied values, documented defaults, and usable resources. Do not reinterpret invalid values as different accepted meanings or invent fallback values.

| Condition | Result |
|---|---|
| Optional value omitted with a documented default | Use that default silently. |
| Optional value explicitly invalid with a documented default | Warn and use that default, subject to field-specific constraints. |
| Optional value invalid without a documented default | Warn and ignore it, subject to field-specific constraints. |
| Unconsumed top-level field | Ignore without diagnostics. |
| Unknown field within a consumed mapping | Warn and ignore, except where stricter validation is defined. |
| Missing or invalid required value without a usable fallback | Error. |
| Unreadable file, invalid UTF-8, invalid YAML, unsupported YAML constructs, or a non-mapping document | Error; no usable configuration document. |
| Invalid discovered resource or unavailable pool member | Warn and exclude the affected resource or member; retain unrelated valid data. |

Specific constraints take precedence over the general optional-value policy: paired output geometry, fixed Waveshare geometry, destination identity/type/audience/capacity, strict `overrides`, supplied inset completeness and valid geometry, explicit font-size bounds, required font-default declarations, and explicit operational-storage paths must meet their stated rules.

A problem is fatal when a required effective value for the operation cannot be established, including fields expressly designated configuration errors here. Recoverable problems must not prevent acceptance of unrelated valid settings.

Diagnostics identify the configuration file and affected field and explain whether a value was ignored, excluded, or replaced by a documented default. Severity is:

- `INFO`: Useful operational information that does not indicate a configuration problem.
- `WARNING`: A recoverable problem remains compatible with usable effective configuration.
- `ERROR`: A required effective condition cannot be satisfied.

Validation must not overwrite the configuration file or mutate authoritative operational state on a failed load.

