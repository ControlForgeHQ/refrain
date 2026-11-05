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
  timezone: "America/Toronto"
  day_start: "06:00"

content:
  directory: "content"

reveal:
  source: "12:00"
  attribution: "18:00"

information_view:
  duration: 60

display:
  backends:
    - type: "window"
    - type: "image-server"
      host: "127.0.0.1"
      port: 8080

layout:
  presentation_region:
    x: 0.10
    y: 0.15
    width: 0.80
    height: 0.65

  fonts:
    default:
      - "libre-baskerville"
      - "lora"
      - "source-sans-3"

    available:
      my-lora: "fonts/MyCustomLora.otf"

  backgrounds:
    default:
      - "none"

    available:
      my-paper: "backgrounds/MyPaper.png"

  decorations:
    default:
      - "none"

    available:
      my-border:
        image: "decorations/MyBorder.png"
        presentation_region:
          x: 0.15
          y: 0.20
          width: 0.70
          height: 0.55
        background: "my-paper"

  text:
    min_font_size: 28
    max_font_size: 100
```

The example illustrates simultaneous display backends, the information view, a default presentation region, registered fonts, backgrounds, and decorations, and automatic quotation fitting.

Refrain automatically registers its bundled fonts, backgrounds, and decorations. Registered resources can be referenced by stable identifiers without supplying paths in content entries.

The `available` mappings register installation-specific resources. Their paths resolve relative to the application configuration file when not absolute.

The `default` pools control automatic resource selection. A resource need not appear in its default pool to be selected explicitly by a content entry.

The reserved value `"none"` is available for backgrounds and decorations. The example uses it to preserve the original undecorated, paper-white presentation.

User-supplied resource paths, rectangle dimensions, and font-size values are examples rather than universal defaults.

The resolution and precedence of content-entry resource preferences are defined in the corresponding sections below.

### Display backends

The required `display.backends` field selects one or more implementations used to present complete rendered images.

The field must contain a nonempty sequence of backend mappings.

Each backend mapping requires a `type` field identifying one supported built-in backend.

Version 0.1 defines the following built-in backend identifiers:

| Value | Description |
|---|---|
| `"window"` | Displays complete presentation images in a desktop window on a supported graphical Windows or Linux environment. |
| `"waveshare-13in3-e"` | Presents complete images on the supported Waveshare 13.3-inch e-Paper HAT+ (E). |
| `"image-server"` | Makes the current complete presentation image available to HTTP clients. |

Each backend type may appear at most once in `display.backends`.

The sequence must contain at least one valid, uniquely identified backend. Duplicate backend types are configuration errors.

Backend declaration order has no semantic meaning and does not establish execution priority.

Only implemented backends may be selected at runtime. Unsupported backend identifiers do not become available merely because they appear in configuration.

An unavailable backend must produce an actionable diagnostic rather than silently selecting another type. Runtime failures of an individual backend do not invalidate other configured destinations.

The `display.backends` field has no implicit default. Development example configurations may select `"window"`; installations using the physical e-paper panel must explicitly include `"waveshare-13in3-e"`.

The former singular `display.backend` field is not supported. No compatibility alias or automatic conversion is provided.

Backend selection is independent of content selection, reveal scheduling, and image preparation.

All configured backends consume the same complete prepared images. Backend selection does not change the configured presentation region, typography, committed snapshot, or reveal schedule.

Version 0.1 does not support third-party backend discovery, arbitrary Python module paths, or an external display plugin interface.

#### Backend-specific fields

Each backend mapping contains its required `type` field and any supported settings for that backend.

The `window` and `waveshare-13in3-e` backends require no additional configuration fields in Version 0.1.

The `image-server` backend supports optional `host` and `port` fields.

For example:

```yaml
display:
  backends:
    - type: "waveshare-13in3-e"

    - type: "image-server"
      host: "0.0.0.0"
      port: 8080
```

The following fields are supported for the `image-server` backend:

| Field | Type | Required | Default |
|---|---|---|---|
| `host` | String | No | `"127.0.0.1"` |
| `port` | Integer | No | `8080` |

These fields belong directly to the `image-server` backend mapping, not to a separate application-level configuration section.

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

The image-server backend uses the fixed HTTP endpoint `/display/current` and serves PNG images. Neither the endpoint path nor the image format is configurable in Version 0.1.

The backend retains its current image representation in memory and requires no separate image-storage directory or filesystem path.

### General settings

| Field | Type | Required | Default |
|---|---|---|---|
| `general.timezone` | String | Yes | None |
| `general.day_start` | Time string | No | `"06:00"` |

`timezone` must be a valid IANA timezone identifier, such as `"America/Toronto"`.

Timezone abbreviations such as `"EST"` are not accepted as substitutes for IANA identifiers.

`day_start` specifies the local wall-clock time at which a new logical display day normally begins.

Times use 24-hour `HH:MM` notation with two-digit hours and minutes.

Examples of valid times are `"00:00"`, `"06:00"`, and `"18:30"`.

Seconds, timezone suffixes, and loosely formatted times are not supported in Version 0.1.

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

### Content settings

| Field | Type | Required | Default |
|---|---|---|---|
| `content.directory` | String | No | `"content"` |

`directory` identifies the location of the content library.

Relative paths are interpreted relative to the directory containing the application configuration file.

Absolute paths are permitted.

The path must identify a readable directory when the library is loaded.

Directory organization does not influence content eligibility, priority, or selection probability.

### Global reveal schedule

| Field | Type | Required | Default |
|---|---|---|---|
| `reveal.source` | Time string | No | `"12:00"` |
| `reveal.attribution` | Time string | No | `"18:00"` |

The global reveal schedule establishes default local times for source and attribution.

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

The layout configuration defines:

- a default presentation region for the complete composition;
- available fonts and their default selection pool;
- available backgrounds and their default selection pool;
- available decorations and their default selection pool;
- minimum and maximum primary quotation font sizes.

A selected decoration may override the default presentation region and may specify a preferred background.

Backgrounds and decorations do not change the semantics of quotation, source, attribution, or progressive reveal.

The renderer determines the arrangement and fitting of all present literary fields within the effective presentation region.

A fixed quotation font size is not required.

### Presentation region

The `layout.presentation_region` mapping defines the default rectangular area available for the complete literary composition.

| Field | Type | Required |
|---|---|---|
| `layout.presentation_region.x` | Number | Yes |
| `layout.presentation_region.y` | Number | Yes |
| `layout.presentation_region.width` | Number | Yes |
| `layout.presentation_region.height` | Number | Yes |

Coordinates are normalized proportions of the rendered image dimensions.

- `x` identifies the region's left edge.
- `y` identifies the region's top edge.
- `width` identifies the region's horizontal extent.
- `height` identifies the region's vertical extent.

The image's top-left corner is `(0, 0)`, and its bottom-right corner is `(1, 1)`.

For example:

```yaml
layout:
  presentation_region:
    x: 0.10
    y: 0.15
    width: 0.80
    height: 0.65
```

The values must satisfy:

- `0 <= x < 1`
- `0 <= y < 1`
- `0 < width <= 1`
- `0 < height <= 1`
- `x + width <= 1`
- `y + height <= 1`

Boolean values are not valid coordinates.

A decoration may specify its own `presentation_region` mapping using the same fields and validation rules.

When the selected decoration provides a presentation region, that region replaces `layout.presentation_region` for the complete committed presentation. Otherwise, the global region applies.

The effective presentation region contains the quotation and all source and attribution fields present in the selected entry.

All included fields must fit within this region without overlapping, clipping, or truncation.

The effective region remains fixed throughout every reveal stage of the committed selection.

The layout accounts for all present fields regardless of whether they are currently visible. Unrevealed fields retain their allocated positions until their reveal stages are reached.

Absent optional fields do not require reserved space.

Version 0.1 does not expose separate configurable source or attribution regions.

A content entry cannot directly specify a presentation region.

### Font registry

Refrain maintains an effective font registry containing both bundled fonts and fonts explicitly registered in application configuration.

Every font has a stable, case-sensitive identifier. Content entries and the default font pool refer to fonts by these identifiers rather than by filesystem paths.

#### Bundled fonts

Refrain automatically registers the following bundled fonts:

| Identifier | Font family |
|---|---|
| `alegreya` | Alegreya |
| `libre-baskerville` | Libre Baskerville |
| `lora` | Lora |
| `orbitron` | Orbitron |
| `source-sans-3` | Source Sans 3 |

Bundled fonts are application resources and do not require entries in `layout.fonts.available`.

`orbitron` is available for explicit font selection and is not included in the default font pool unless configured there.

Their identifiers are reserved. Application configuration must not redefine or override a bundled font identifier.

Bundled font identifiers form part of the public configuration interface and must remain stable across compatible releases.

#### User-registered fonts

The optional `layout.fonts.available` mapping registers additional fonts supplied by an installation.

Each mapping key is a user-defined font identifier, and its value is the path to a supported font file.

For example:

```yaml
layout:
  fonts:
    available:
      my-lora: "fonts/MyCustomLora.otf"
      family-handwriting: "fonts/FamilyHandwriting.ttf"
```

When omitted, `layout.fonts.available` defaults to an empty mapping.

Font identifiers must be nonempty strings and are case-sensitive.

User-defined identifiers must not duplicate bundled identifiers. Such registrations are ignored with a warning; user-defined fonts cannot replace or shadow bundled fonts.

Font paths must be nonempty strings.

Relative font paths are resolved relative to the directory containing `config.yaml`.

Absolute paths are permitted.

A user-registered font is included in the effective font registry only when its identifier and path are valid and the referenced file exists, is readable, and can be loaded by the renderer.

Invalid, missing, or unreadable font registrations are excluded individually from the effective registry, with warnings identifying the affected identifier and reason.

An invalid registration must not prevent otherwise valid font registrations or bundled fonts from being available.

The effective registry contains all usable bundled fonts and all accepted user-registered fonts. Both are available for explicit selection by content entries, whether or not they appear in the default font pool.

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
```

The configured default pool defines the user's preferred fonts for automatic selection.

The effective default pool contains only identifiers from the configured pool that correspond to usable fonts in the effective registry.

Unavailable, unregistered, or otherwise invalid font identifiers are excluded from the effective default pool with warnings.

Duplicate identifiers are ignored after their first occurrence, with a warning.

The effective default pool must contain at least one usable font whenever Refrain needs to perform a new selection.

The default pool is explicitly configured. Refrain must not automatically add bundled or newly registered fonts to the pool.

A registered font need not appear in the default pool. Fonts outside the default pool remain available for explicit selection by content entries.

The effective default pool identifies the fonts eligible for automatic selection when a content entry has no available preferred font.

An empty or unusable configured default pool cannot be repaired by silently substituting an unrelated bundled font pool.

Bundled fallback during regeneration of an already committed presentation is independent of automatic font selection and is defined in `docs/ARCHITECTURE.md`.

Automatic font selection and its persistence are defined in `docs/ARCHITECTURE.md`.

### Background registry

Refrain maintains an effective background registry containing bundled background images and accepted user-registered images.

Every background has a stable, case-sensitive identifier. The default background pool, decoration preferences, and content-entry preferences refer to these identifiers rather than filesystem paths.

The reserved identifier `"none"` represents no background image. It is always available and cannot be registered or overridden.

#### Bundled backgrounds

Refrain includes a small collection of subtle, paper-like backgrounds, registered automatically under stable identifiers.

The exact bundled identifiers are documented alongside the distributed assets when introduced. Identifiers included in a release are reserved and remain stable across compatible releases.

Bundled backgrounds are available for explicit selection without being automatically added to the default pool.

#### User-registered backgrounds

The optional `layout.backgrounds.available` mapping registers additional background images.

Each key is a user-defined background identifier and its value is the path to a PNG file.

For example:

```yaml
layout:
  backgrounds:
    available:
      handmade-paper: "backgrounds/HandmadePaper.png"
      parchment: "backgrounds/Parchment.png"
```

When omitted, `layout.backgrounds.available` defaults to an empty mapping.

Background identifiers must be nonempty, case-sensitive strings.

User identifiers must not duplicate reserved or bundled identifiers. Such registrations are ignored with a warning.

Relative paths resolve from the directory containing the application configuration file. Absolute paths are permitted.

Background images must be readable, single-frame PNG images with dimensions of 1600 × 1200 pixels.

RGB and RGBA backgrounds are supported. Other formats, image modes, dimensions, or unreadable resources are not accepted in Version 0.1.

Invalid registrations are excluded individually from the effective registry with warnings. They must not prevent other usable backgrounds from being registered.

Background images are drawn over the paper-white base image. An RGBA background may expose some of that base through transparency.

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

Refrain maintains an effective decoration registry containing bundled decorations and accepted user-registered decorations.

A decoration is a complete, transparent image overlay with optional composition metadata.

Each decoration may define:

- an image resource;
- an effective presentation-region override;
- a preferred background identifier, including `"none"`.

The reserved identifier `"none"` represents no decoration. It is always available and cannot be registered or overridden.

#### Bundled decorations

Refrain includes a small collection of restrained graphical decorations such as borders, corner ornaments, and flourishes.

Each bundled decoration has a stable identifier and may include its own presentation-region and background preferences.

The exact bundled identifiers and their associated metadata are documented alongside the distributed assets when introduced.

Bundled decorations are registered automatically and remain available independently of the default decoration pool.

#### User-registered decorations

The optional `layout.decorations.available` mapping registers additional decoration entries.

Each key is a user-defined decoration identifier. Its value is a mapping containing the decoration's image and optional metadata.

| Field | Type | Required | Default |
|---|---|---|---|
| `image` | String path | Yes | None |
| `presentation_region` | Normalized rectangle mapping | No | Global presentation region |
| `font` | Font identifier | No | No preference |
| `background` | Background identifier or `"none"` | No | No preference |

For example:

```yaml
layout:
  decorations:
    available:
      botanical-corners:
        image: "decorations/BotanicalCorners.png"
        presentation_region:
          x: 0.16
          y: 0.18
          width: 0.68
          height: 0.58

      futuristic-corners:
        image: "decorations/FuturisticCorners.png"
        presentation_region:
          x: 0.12
          y: 0.16
          width: 0.76
          height: 0.60
        font: "orbitron"
        background: "hex-paper"
```

When omitted, `layout.decorations.available` defaults to an empty mapping.

Decoration identifiers follow the same nonempty, case-sensitive, reserved-identifier rules as background identifiers.

Relative image paths resolve from the directory containing the application configuration file. Absolute paths are permitted.

Decoration images must be readable, single-frame RGBA PNG images with dimensions of 1600 × 1200 pixels.

Transparency is required so the underlying background can remain visible.

The optional `presentation_region` must satisfy the validation rules defined for `layout.presentation_region`.

The optional `font` must be a nonempty identifier referring to a usable registered font. An unavailable preferred font produces a warning and is treated as an absent preference without invalidating an otherwise usable decoration.

The optional `background` must refer to a usable registered background or `"none"`. An unavailable preferred background produces a warning and is treated as an absent preference without invalidating an otherwise usable decoration.

Invalid decoration image or presentation-region registrations are excluded individually from the effective registry, with warnings.

Decorations provide artwork and composition metadata. They do not define arbitrary drawing instructions, independently positioned text fields, or new literary presentation styles.

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

### Background and decoration resolution

For each selected quotation, Refrain resolves the decoration before resolving the font and background.

An available explicit content-entry decoration takes precedence over the default decoration pool. The value `"none"` suppresses decoration selection.

When no explicit decoration is available, Refrain selects from the effective default decoration pool.

For fonts, precedence is:

1. An available explicit content-entry font.
2. The selected decoration's available preferred font.
3. Automatic selection from the effective default font pool.

For backgrounds, precedence is:

1. An available explicit content-entry background, including `"none"`.
2. The selected decoration's available preferred background, including `"none"`.
3. Automatic selection from the effective default background pool.

An unavailable explicit content-entry preference produces a warning and falls back to the next applicable selection level. It does not invalidate the otherwise valid entry.

An unavailable decoration font or background preference is ignored with a warning, without invalidating an otherwise usable decoration.

An absent decoration preference does not prevent explicit content-entry resource selection or automatic selection from the corresponding default pool.

The selected decoration determines the effective presentation region when it defines an override; otherwise the global presentation region applies.

The final font, background, and decoration identifiers and effective presentation region are committed with the daily selection.

No resource is reselected during reveal progression or restart recovery. Image regeneration resolves the committed identifiers independently of the original content-entry and decoration preferences.

The handling of missing resources during regeneration is defined in `docs/ARCHITECTURE.md`.

### Automatic quotation fitting

The `layout.text` mapping defines the permitted font-size bounds for the primary quotation.

| Field | Type | Required |
|---|---|---|
| `layout.text.min_font_size` | Positive integer | Yes |
| `layout.text.max_font_size` | Positive integer | Yes |

For example:

```yaml
layout:
  text:
    min_font_size: 28
    max_font_size: 100
```

Font sizes are expressed in rendered-image pixels.

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
- direct per-entry presentation-region values;
- per-entry font-size overrides;
- per-quotation presentation-style or visual-resource overrides;
- user-defined literary presentation styles;
- configurable source and attribution regions;
- configurable concealment effects for unrevealed fields;
- automatic selection among fonts based on fitting results;
- automatic foreground/background contrast analysis;
- arbitrary image transformations or independent artwork placement;
- a general-purpose theme engine.

Decorations may define a presentation region, but content entries reference decorations by identifier rather than supplying arbitrary region coordinates.

Additional built-in literary presentation styles may be introduced in future versions without changing the content-entry structure.

Display hardware selection and output resolution are not user-configurable through these layout fields in Version 0.1.

Normalized presentation regions preserve future resolution flexibility without promising that the initial assets or layout have been validated at every possible resolution.

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
| `font` | String | No | Automatic selection from default font pool |
| `background` | String | No | Decoration preference, then default background pool |
| `decoration` | String | No | Automatic selection from default decoration pool |
| `presentation_style` | String | No | `"centered"` |
| `eligibility` | Sequence of eligibility rules | No | Ordinary eligibility |
| `reveal` | Mapping of reveal overrides | No | Global reveal schedule |

No other entry-level fields are defined for Version 0.1.

All quotations in an entry inherit the entry's metadata, priority, font preference, background preference, decoration preference, presentation style, eligibility, and reveal configuration.

Individual quotations do not have independent overrides.

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

An absent `font` field means that no specific content-entry font preference is expressed. An available preferred font from the selected decoration applies when present; otherwise Refrain selects from the effective default font pool.

An explicit empty string or invalid field type is a validation error.

The resolution of preferred fonts, fallback behavior, warnings, and persistence of the selected font are defined in `docs/ARCHITECTURE.md`.

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

The resolved background identifier is committed for the display day and is not reconsidered during progressive reveals or restart recovery.

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

An explicit `"none"` suppresses the default decoration pool and uses the global presentation region.

An absent `decoration` field means automatic selection from the effective default decoration pool.

A selected decoration may supply an effective presentation region, a preferred font, and a preferred background. Explicit content-entry font and background preferences always take precedence over the corresponding decoration preferences.

Unknown decoration identifiers are permitted without invalidating otherwise valid content entries. They produce a warning and use the default decoration pool.

Empty strings, non-string values, and YAML null are invalid.

The resolved decoration identifier and its effective presentation region are committed for the display day and are not reconsidered during progressive reveals or restart recovery.

### Presentation style

The optional `presentation_style` field selects the built-in style used to arrange the literary composition.

It is defined at the content-entry level and applies to every quotation in that entry.

Version 0.1 supports the following values:

| Value | Behavior |
|---|---|
| `"centered"` | Each quotation line is independently centered horizontally. The quotation block is vertically centered within its allocated space. |
| `"left-aligned"` | Quotation lines share a common left edge. The complete text block remains horizontally centered according to its widest rendered line, rather than anchored to the region's left edge, and vertically centered within its allocated space. The byline is right-aligned within the presentation region. |

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

The effective style is preserved in the committed daily snapshot. Subsequent content-library changes do not alter the active presentation.

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

The effective reveal schedule is resolved when preparing the daily snapshot.

Changes to the original entry or global configuration do not alter a committed selection.

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

Application configuration is interpreted into an effective configuration containing accepted values, documented defaults, and usable registered resources.

A configuration problem is fatal only when Refrain cannot establish a valid effective value required for the operation.

Apply the following rules:

- A missing optional value with a documented default uses that default and is reported at informational severity.
- An explicitly supplied invalid optional value with a documented default produces a warning and uses that default.
- An invalid optional value without a documented default produces a warning and is ignored.
- An unrecognized configuration field produces a warning and is ignored.
- A missing or invalid required value without a usable fallback produces an error.
- An unavailable or invalid user-registered font produces a warning and is excluded from the effective font registry.
- An unavailable or unregistered default-pool identifier produces a warning and is excluded from the effective default pool.
- An unavailable or invalid user-registered background or decoration produces a warning and is excluded from its effective registry.
- An unavailable or unregistered default background or decoration identifier produces a warning and is excluded from its effective default pool.
- An unavailable optional font preference on an otherwise usable decoration is ignored with a warning.
- A missing background or decoration pool defaults to `["none"]`.
- A configured background or decoration pool with no usable members falls back to `["none"]` with a warning.
- An invalid decoration presentation region excludes that decoration without invalidating unrelated resources.
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

Invalid or unrecognized fields make the affected content entry invalid.

A YAML file that cannot be parsed is excluded in its entirety, with an actionable warning.

A syntactically valid file containing independently represented content entries may retain valid entries while excluding invalid entries, where the file format permits them to be validated separately.

An invalid entry must not invalidate otherwise valid entries or files.

Conflicting duplicate entry identifiers must not be resolved by arbitrary filesystem enumeration order. All entries participating in a detected identifier conflict are excluded, with diagnostics identifying the conflicting entries.

Content entries whose preferred font, background, or decoration identifier is unavailable remain valid when the identifier itself satisfies the field's syntax rules. Resource fallback behavior is defined in `docs/ARCHITECTURE.md`.

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

An already committed presentation remains independent of subsequent changes or failures in its original content library.

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
- direct per-entry presentation regions or font-size limits;
- per-entry layout customization beyond the defined resource preferences and presentation style;
- automatic font-family selection based on text-fitting performance;
- resource repetition histories or weighted resource selection;
- automatic contrast adjustment or foreground recolouring;
- arbitrary graphical transformations or decoration placement instructions;
- configurable image resolution or multi-resolution asset variants;
- general-purpose themes or style scripting;
- content-triggered external actions;
- independent presentation layouts for individual display backends;
- interactive content editing.

These capabilities may be evaluated for later releases according to the roadmap.