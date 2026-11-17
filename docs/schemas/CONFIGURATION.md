# Application Configuration

This document defines Refrain's Version 0.1 application-configuration YAML interface: field names, types, required values, defaults, supported values, and validation constraints.

Configuration selects destinations, storage locations, scheduling times, presentation defaults, and resources. It does not contain content entries, asset manifests, publication metadata, or publication manifests.

[Architecture](../ARCHITECTURE.md) owns runtime behavior, selection and pool-expansion algorithms, precedence, scheduling, rendering, persistence, recovery, and backend lifecycles. [Engineering](../ENGINEERING.md) owns implementation and test requirements. [CLI](../CLI.md) owns configuration-file selection and command syntax.

During the schema split, [Content and Configuration Format](CONTENT_FORMAT.md) remains available for content-entry and asset-package definitions. Separate `CONTENT.md` and `ASSETS.md` documents are planned; publication metadata and manifests will eventually be consolidated into `PUBLICATION.md`. Until then, see [Publication Metadata](PUBLICATION_METADATA.md) and [Publication Manifest](PUBLICATION_MANIFEST.md).

## YAML document

Application configuration is conventionally named `config.yaml`.

- Use UTF-8 and exactly one YAML document containing one top-level mapping.
- Use spaces for indentation; two spaces are recommended.
- Use ordinary mappings, sequences, strings, integers, and booleans as specified below.
- Do not use custom tags, executable object constructors, anchors, aliases, merge keys, duplicate mapping keys, or implicit application-specific expressions.
- Quote values resembling dates, times, numbers, or booleans when a string is required. Unquoted scalars are accepted only when the parser produces the required type.
- Boolean values do not satisfy integer fields. YAML null does not satisfy a string, integer, boolean, sequence, or mapping field unless expressly permitted below.

The supported top-level fields are `destinations`, `image-server`, `storage`, `scheduling`, `presentation`, `palette`, `fonts`, `text`, `backgrounds`, and `decorations`.

Mappings contain the documented fields only. Unknown configuration fields are warned about and ignored, except within destination `overrides`, where unknown fields are errors.

## Complete example

This example demonstrates all compatible application settings, including every supported destination type and override field. It is a valid configuration under this specification, assuming the referenced bundled `lora` font is usable. The content directory must contain usable content for operations that require a content library. The explicit paths and resource selections are examples, not additional defaults.

```yaml
destinations:
  - id: "desktop"
    type: "window"
    audience: "private"
    aspect_ratio: "16:9"
    resolution: [1920, 1080]

  - id: "epaper"
    type: "waveshare-13in3-e"
    audience: "private"
    overrides:
      background: "none"
      decoration: "none"
      font: "lora"
      text_color: "black"
      decoration_color: "sage"
      qr: "none"

  - id: "kitchen"
    type: "image-server"
    audience: "public"
    aspect_ratio: "16:10"
    resolution: [3840, 2400]

  - id: "hallway"
    type: "image-server"
    audience: "private"
    aspect_ratio: "4:3"
    resolution: [1600, 1200]

  - id: "web-public"
    type: "publish"
    audience: "public"
    aspect_ratio: "5:3"
    resolution: [1920, 1152]
    overrides:
      background: "none"

  - id: "web-private"
    type: "publish"
    audience: "private"
    aspect_ratio: "16:10"
    resolution: [3840, 2400]

image-server:
  host: "127.0.0.1"
  port: 8080

storage:
  content: "content"
  state: "state/current.json"
  history: "state/global-history.jsonl"
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
    enabled: true

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

The installed distribution supplies `config.default.yaml` as an editable starting point. Its explicit selections are not universal defaults for omitted fields. In particular, its `@builtin` pools and italic source-face preference are configured choices. Initialization and preservation of installed configuration are defined in [CLI](../CLI.md#initialize) and [Architecture](../ARCHITECTURE.md#application-paths-and-initialization).

## Destinations

`destinations` is required and must be a nonempty sequence of mappings.

| Field | Type | Required | Constraint |
|---|---|---|---|
| `id` | String | Yes | Globally unique; matches `[A-Za-z0-9][A-Za-z0-9_-]*`; at most 256 characters. |
| `type` | String | Yes | Exactly `window`, `waveshare-13in3-e`, `image-server`, or `publish`. |
| `audience` | String | Yes | Exactly `public` or `private`; no default or fallback. |
| `aspect_ratio` | String | Paired with `resolution` where supported | Exactly `4:3`, `5:3`, `16:9`, or `16:10`. |
| `resolution` | Sequence of two integers | Paired with `aspect_ratio` where supported | Positive pixel dimensions in width, height order. |
| `overrides` | Mapping | No | Only the restricted fields below. |

Identifiers and enumerated values are case-sensitive. Missing, null, empty, non-string, or unsupported audiences are errors. Invalid or duplicate destination IDs and capacity excesses are errors. `all` is an ordinary valid ID; `@all` is reserved for CLI publication selection and does not satisfy the ID syntax.

| Destination type | Maximum configured destinations | Default aspect ratio | Default resolution | Explicit geometry |
|---|---:|---|---|---|
| `window` | 1 | `16:9` | `[1920, 1080]` | Supply both fields or neither. |
| `waveshare-13in3-e` | 1 | Fixed `4:3` | Fixed `[1600, 1200]` | Both fields prohibited. |
| `image-server` | Multiple | `16:10` | `[3840, 2400]` | Supply both fields or neither. |
| `publish` | Multiple | `16:10` | `[3840, 2400]` | Supply both fields or neither. |

A declared aspect ratio and requested resolution are independent values. Dimensions need not exactly match the aspect ratio; `aspect_ratio: "4:3"` with `resolution: [1600, 1190]` is valid. Requested dimensions are not limited by the 3840 × 2400 design reference envelope. Unsupported aspect ratios, boolean or non-integer dimensions, zero or negative dimensions, incomplete geometry pairs, and geometry fields on the fixed Waveshare destination are errors.

The following are alternative declarations, not fields to combine in one destination:

```yaml
# Use the window's default aspect ratio and resolution.
destinations:
  - id: "desktop"
    type: "window"
    audience: "private"

fonts:
  pools:
    default: ["@builtin"]
```

```yaml
# Supply both configurable geometry fields.
destinations:
  - id: "desktop"
    type: "window"
    audience: "private"
    aspect_ratio: "4:3"
    resolution: [1600, 1190]

fonts:
  pools:
    default: ["@builtin"]
```

Do not combine either configurable geometry form with a Waveshare destination. Its valid declaration is shown without geometry fields in the complete example.

A `publish` destination has no destination-local filesystem path. Its directory is a direct child of the effective `storage.publish` root, named from its destination ID. Publication file structures belong to [Publication Manifest](PUBLICATION_MANIFEST.md).

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

Overrides affect scheduled image preparation. They do not define independent artistic selection or transformations of finished transient images. Decoration suppression uses global insets and quotation font bounds, including their documented defaults; background suppression does not reset geometry. A decoration color has no rendering effect without a decoration layer. Runtime application, face resolution, grouping, and geometry validation belong to [Architecture](../ARCHITECTURE.md#prepared-images).

## Shared image-server settings

The optional top-level `image-server` mapping contains only:

| Field | Type | Default | Constraint |
|---|---|---|---|
| `host` | String | `"127.0.0.1"` | Nonempty bind address or hostname. |
| `port` | Integer | `8080` | 1 through 65535, inclusive. |

The section's presence enables the shared HTTP listener. An empty mapping and a null value written as a bare `image-server:` key are equivalent:

```yaml
image-server: {}
```

Alternatively:

```yaml
image-server:
```

These are section fragments to use in an otherwise complete configuration. Omit the section to leave external HTTP delivery disabled; image-server destinations may still be configured. Invalid optional host or port values produce warnings and use their defaults.

Listener lifecycle, image retention, routing, and delivery semantics belong to [Architecture](../ARCHITECTURE.md#network-image-service). The default loopback host does not permit remote-device connections. A network-accessible binding provides neither authentication nor encryption; use only on trusted local networks, without direct exposure to untrusted networks or the public Internet.

## Storage

The optional `storage` mapping contains only the following nonempty path strings:

| Field | Default when omitted |
|---|---|
| `content` | `content/` beside the selected configuration file. |
| `state` | Platform-standard operational-state file. |
| `history` | Platform-standard global-history file. |
| `artifacts` | Platform-standard prepared-artifact directory. |
| `publish` | Platform-standard publication root. |

Absolute paths are used as specified. Relative paths are resolved from the directory containing the selected configuration file, not from the current working directory.

Each omitted operational path retains its independent platform-standard default. Selecting a different configuration file or setting one storage path does not relocate the others. Only omitted `storage.content` follows the selected configuration file.

The standard operational defaults are:

| Platform | `state` | `history` | `artifacts` | `publish` |
|---|---|---|---|---|
| Linux | `$XDG_STATE_HOME/refrain/state.json` | `$XDG_STATE_HOME/refrain/global-history.jsonl` | `$XDG_CACHE_HOME/refrain/artifacts` | `$XDG_STATE_HOME/refrain/publish` |
| Windows | `%LOCALAPPDATA%\Refrain\State\state.json` | `%LOCALAPPDATA%\Refrain\State\global-history.jsonl` | `%LOCALAPPDATA%\Refrain\Cache\artifacts` | `%LOCALAPPDATA%\Refrain\Publish` |
| macOS | `~/Library/Application Support/Refrain/State/state.json` | `~/Library/Application Support/Refrain/State/global-history.jsonl` | `~/Library/Caches/Refrain/artifacts` | `~/Library/Application Support/Refrain/Publish` |

On Linux, an unset, empty, or nonabsolute `XDG_STATE_HOME` uses `~/.local/state`; the corresponding `XDG_CACHE_HOME` fallback is `~/.cache`. These environment variables are host path inputs, not YAML fields.

Platform path resolution and storage lifecycles belong to [Architecture](../ARCHITECTURE.md#application-paths-and-initialization) and [Engineering](../ENGINEERING.md#file-paths).

A supplied `storage` value must be a mapping. An invalid `storage.content` value produces a warning and uses its default. Invalid explicitly supplied `state`, `history`, `artifacts`, or `publish` values are errors; they do not fall back to platform paths. Unknown storage fields are warned about and ignored.

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

These section fragments do not describe an overnight reveal schedule. Revealing at `"01:00"` after a `"20:00"` day start is unsupported in Version 0.1.

Per-entry reveal declarations belong to the content-entry schema. Display-date calculation, cumulative stages, commitment, clock changes, and missed events belong to [Architecture](../ARCHITECTURE.md#progressive-reveal).

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

| Declared aspect | Design canvas |
|---|---|
| `4:3` | 3200 × 2400 |
| `5:3` | 3840 × 2304 |
| `16:9` | 3840 × 2160 |
| `16:10` | 3840 × 2400 |

For the active design canvas, `left + right` must be less than its width and `top + bottom` less than its height. The resulting literary rectangle must have positive width and height.

A selected decoration's complete `presentation_insets` replaces the global mapping; otherwise the global mapping applies. Asset-side declarations belong to the asset schema. Content entries cannot directly specify insets. Scaling, rounding, composition, and fitting requirements belong to [Architecture](../ARCHITECTURE.md#literary-presentation-geometry).

### Information view

| Field | Type | Default | Constraint |
|---|---|---|---|
| `presentation.information_view.duration` | Integer | `60` | 0 through 300 inclusive, in seconds. |

`information_view` must be a mapping when supplied. A duration of `0` disables automatic startup information-view presentation; `1` through `300` requests that duration. Strings, booleans, floating-point values, negative values, and values greater than 300 are invalid, warn, and use `60`.

This is a startup-presentation setting, not an external request interface or an additional schedule. Timing, initial publication attempts, and lifecycle belong to [Architecture](../ARCHITECTURE.md#information-view).

### Literary QR

| Field | Type | Default | Constraint |
|---|---|---|---|
| `presentation.qr.enabled` | Boolean | `true` | YAML `true` or `false` only. |

`qr` must be a mapping when supplied. Missing enablement uses `true`; an invalid optional value warns and uses `true`. Strings and integers are invalid.

This setting controls literary presentations and does not affect the standalone information view. A selected decoration may suppress QR through its asset-side `qr_ready` field; a destination may suppress it using `overrides.qr: "none"`.

Version 0.1 has no configurable QR payload, placement, or size in application configuration, and no content-entry QR setting. The fixed payload, output-dependent availability, conditional artwork, placement, and raster rules belong to [Architecture](../ARCHITECTURE.md#qr-generation-and-conditional-artwork); decoration positioning fields belong to the asset schema.

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

Manifest formats, file requirements, package confinement, registration validity, and collision constraints remain in the [legacy asset sections](CONTENT_FORMAT.md#font-registry) pending `ASSETS.md`. Discovered valid resources are available by identifier even when absent from a default pool. Discovery alone does not add them to a configured pool.

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

Invalid pool names or malformed definitions are diagnosed without discarding unrelated valid definitions. Malformed or unknown references and invalid or unavailable identifiers warn and contribute no candidates. Duplicate resolved identifiers contribute one candidate, retaining the first occurrence. Duplicate font and color identifiers are diagnosed. Cyclic pool references are permitted; their expansion is specified in Architecture.

Each named pool retains its actual expanded membership, including an empty `default`. Runtime fallbacks do not insert `none` or `black` into an empty named pool. An explicit reference to that pool remains empty; it does not acquire an implicit `builtin` pool.

A missing or malformed required `fonts.pools.default`, including an explicitly empty sequence, is an error. Invalid or unavailable font members are excluded with warnings. A nonempty font declaration whose usable expansion is empty does not by itself prohibit operation with an otherwise usable explicit content or decoration font preference. Preparation requiring automatic font selection needs at least one usable default candidate; there is no unrelated bundled-font fallback.

Missing background or decoration defaults use `["none"]`. Missing color defaults use `["black"]`. Invalid optional default declarations warn; unusable members are excluded. Automatic background, decoration, and color fallbacks are defined in [Architecture](../ARCHITECTURE.md#daily-background-and-decoration-selection), separately from named-pool membership.

Expansion order, recursion handling, equal-probability selection, resource precedence, face fallback, and strict viewer requests are owned by Architecture and [CLI](../CLI.md#presentation-overrides).

### Global font faces

The optional `fonts.faces` mapping accepts only these roles:

| Key | Value |
|---|---|
| `quotation` | One face identifier |
| `source` | One face identifier |
| `attribution` | One face identifier |

Values match `[A-Za-z0-9][A-Za-z0-9_-]*` and are case-sensitive identifiers, not font paths or pool references. Roles may be omitted; omission expresses no preference. There is no implicit italic preference.

A malformed mapping, unsupported role, or invalid identifier warns and causes the mapping to be ignored without invalidating the font registry. A syntactically valid identifier may be absent from the ultimately selected bundle. Its resolution and `regular` fallback belong to [Architecture](../ARCHITECTURE.md#font-selection).

`fonts.faces` supplies global role preferences; it does not register faces, change bundle selection, or add candidates to pools.

## Quotation font-size bounds

The optional `text` mapping accepts `min_font_size`, `max_font_size`, and `colors`.

| Field | Type | Default | Constraint |
|---|---|---|---|
| `text.min_font_size` | Integer design-canvas pixels | `56` | Greater than zero. |
| `text.max_font_size` | Integer design-canvas pixels | `200` | Greater than zero and at least the effective minimum. |

Bounds default independently when omitted. Explicit invalid bounds, including booleans, strings, floating-point values, nonpositive values, or an inverted effective range, are errors.

These are automatic primary-quotation sizing limits, not a fixed size and not automatic source or attribution limits. Their units are design-canvas pixels, not requested output-image pixels. Scaling and fitting belong to Architecture. Content entries cannot directly set these bounds.

## Validation and compatibility

Configuration is accepted as an effective configuration of valid supplied values, documented defaults, and usable resources. Do not reinterpret invalid values as different accepted meanings or invent fallback values.

| Condition | Result |
|---|---|
| Optional value omitted with a documented default | Use that default silently. |
| Optional value explicitly invalid with a documented default | Warn and use that default, subject to field-specific constraints. |
| Optional value invalid without a documented default | Warn and ignore it, subject to field-specific constraints. |
| Unknown field | Warn and ignore, except strict destination `overrides`. |
| Missing or invalid required value without a usable fallback | Error. |
| Unreadable file, invalid UTF-8, invalid YAML, unsupported YAML constructs, or a non-mapping document | Error; no usable configuration document. |
| Invalid discovered resource or unavailable pool member | Warn and exclude the affected resource or member; retain unrelated valid data. |

Specific constraints take precedence over the general optional-value policy: paired output geometry, fixed Waveshare geometry, destination identity/type/audience/capacity, strict `overrides`, supplied inset completeness and valid geometry, explicit font-size bounds, required font-default declarations, and explicit operational-storage paths must meet their stated rules.

A problem is fatal when a required effective value for the operation cannot be established, including fields expressly designated configuration errors here. Recoverable problems must not prevent acceptance of unrelated valid settings.

Diagnostics identify the configuration file and affected field and explain whether a value was ignored, excluded, or replaced by a documented default. Severity is:

- `INFO`: Useful operational information that does not indicate a configuration problem.
- `WARNING`: A recoverable problem remains compatible with usable effective configuration.
- `ERROR`: A required effective condition cannot be satisfied.

Log transport, repetition control, and process-output requirements belong to Engineering. Validation must not overwrite the configuration file or mutate authoritative operational state on a failed load.

This is the public Version 0.1 configuration interface. New fields and changed meanings require deliberate documentation; unknown YAML metadata is not an extension mechanism or executable instruction.

The retired top-level `display` configuration, configured timezone, arbitrary resource-path registrations, weights or resource repetition histories, configurable QR payloads, arbitrary presentation templates, scripts, and general-purpose theme expressions are not supported configuration fields.
