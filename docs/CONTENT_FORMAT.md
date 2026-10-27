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

Unknown fields are validation errors rather than silently ignored extensions.

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
  quotation: "06:00"
  source: "12:00"
  attribution: "18:00"

display:
  backend: "window"

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

  text:
    min_font_size: 28
    max_font_size: 100
```

The example illustrates the initial configuration structure, including a selected display backend, a bounded presentation region, an explicit default font pool, an additional user-registered font, and font-size limits.

Refrain automatically registers its bundled fonts. They can be referenced by their stable identifiers without declaring filesystem paths in application configuration.

The `layout.fonts.available` mapping registers additional fonts supplied by the installation. It may be omitted when no additional fonts are required.

The default font pool controls which registered fonts are eligible for automatic selection. A registered font that is not included in the default pool remains available for explicit selection by content entries.

User-supplied font paths, rectangle dimensions, and font-size values are examples rather than universal defaults. They must be adjusted to match the resources and presentation layout provided by an installation.

### Display backend

The required `display.backend` field selects the implementation used to present complete rendered images.

Version 0.1 defines the following built-in backend identifiers:

| Value | Description |
|---|---|
| `"window"` | Displays complete presentation images in a desktop window on a supported graphical Windows or Linux environment. |
| `"waveshare-13in3-e"` | Reserved for the supported Waveshare 13.3-inch e-Paper HAT+ (E) display; unavailable until implemented. |

Only implemented backends may be selected at runtime. A recognized backend whose implementation is unavailable must produce an actionable error rather than silently selecting another backend.

The field is required and has no implicit default. Development example configurations may select `"window"`; installations using the physical e-paper panel must explicitly select `"waveshare-13in3-e"`.

Backend selection is independent of content selection, reveal scheduling, and image preparation.

Display backends consume complete rendered images. Backend selection does not change the configured presentation region, typography, or committed snapshot.

Unsupported backend identifiers are configuration errors.

Version 0.1 does not support third-party backend discovery, arbitrary Python module paths, or an external display plugin interface.

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
| `reveal.quotation` | Time string | No | Display-day start |
| `reveal.source` | Time string | No | `"12:00"` |
| `reveal.attribution` | Time string | No | `"18:00"` |

The global reveal schedule establishes default local times for the supported semantic fields.

`quotation` is the initial presentation stage and must coincide with the configured display-day start.

`source` and `attribution` specify when those fields first become visible, if present in the selected content entry.

Reveal stages are cumulative.

A field remains visible after its reveal time has been reached.

Multiple fields may share the same reveal time.

When multiple fields become visible simultaneously, they belong to the same effective presentation stage.

For Version 0.1, reveal times must fall within the same local calendar date as the display-day start and must not precede it.

This restriction avoids ambiguity about whether a clock time refers to the current or following calendar date.

The runtime behavior of clock adjustments, missed stages, and restarts is defined by the architecture.

### Layout settings

The initial release provides one configurable, typography-first presentation layout.

The complete literary composition consists of the primary quotation and its optional source and attribution.

The layout configuration defines:

- the presentation region available to the complete composition;
- available fonts;
- fonts eligible for automatic daily selection;
- minimum and maximum primary quotation font sizes.

The renderer determines the arrangement and fitting of all present fields within the presentation region.

A fixed quotation font size is not required.

### Presentation region

The `layout.presentation_region` mapping defines the rectangular area available for the complete literary composition.

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

The presentation region contains the quotation and all source and attribution fields present in the selected entry.

All included fields must fit within this region without overlapping, clipping, or truncation.

The region remains fixed throughout every reveal stage of the committed selection.

The layout accounts for all present fields regardless of whether they are currently visible. Unrevealed fields retain their allocated positions until their reveal stages are reached.

Absent optional fields do not require reserved space.

Version 0.1 does not expose separate configurable source or attribution regions.

Only `layout.presentation_region` is supported.

### Font registry

Refrain maintains an effective font registry containing both bundled fonts and fonts explicitly registered in application configuration.

Every font has a stable, case-sensitive identifier. Content entries and the default font pool refer to fonts by these identifiers rather than by filesystem paths.

#### Bundled fonts

Refrain automatically registers the following bundled fonts:

| Identifier | Font family |
|---|---|
| `libre-baskerville` | Libre Baskerville |
| `lora` | Lora |
| `source-sans-3` | Source Sans 3 |

Bundled fonts are application resources and do not require entries in `layout.fonts.available`.

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

User-defined identifiers must not duplicate bundled identifiers. Such collisions are configuration validation errors; user-defined fonts cannot replace or shadow bundled fonts.

Font paths must be nonempty strings.

Relative font paths are resolved relative to the directory containing `config.yaml`.

Absolute paths are permitted.

Every explicitly registered font must resolve to an existing, readable font file supported by the renderer.

An invalid, missing, or unreadable registered font is a configuration error, even if the font is not included in the automatic default pool.

Registered font validation must not silently discard invalid entries.

The effective registry contains all bundled fonts and all valid user-registered fonts. Both are available for explicit selection by content entries, whether or not they appear in the default font pool.

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

Every identifier must exist in the effective font registry, including bundled fonts and fonts registered through `layout.fonts.available`.

Duplicate identifiers are not permitted.

The default pool is explicitly configured. Refrain must not automatically add bundled or newly registered fonts to the pool.

A registered font need not appear in the default pool. Fonts outside the default pool remain available for explicit selection by content entries.

The default pool identifies the fonts eligible for automatic selection when a content entry has no available preferred font.

Automatic font selection and its persistence are defined in `docs/ARCHITECTURE.md`.

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

Version 0.1 provides one presentation layout with two built-in presentation styles.

The initial public format does not define:

- arbitrary layout templates;
- custom drawing commands;
- independent positioning of every presentation field;
- per-entry presentation regions;
- per-entry font-size overrides;
- per-quotation presentation-style overrides;
- user-defined presentation styles;
- configurable source and attribution regions;
- configurable concealment effects for unrevealed fields;
- automatic selection among different fonts based on fitting results;
- a general-purpose theme engine.

Additional built-in presentation styles may be introduced in future versions without changing the content-entry structure.

Display hardware selection and output resolution are not user-configurable through these layout fields in Version 0.1.

The normalized presentation region preserves future resolution flexibility without promising that the initial layout has been validated at every possible resolution.

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
| `presentation_style` | String | No | `"centered"` |
| `eligibility` | Sequence of eligibility rules | No | Ordinary eligibility |
| `reveal` | Mapping of reveal overrides | No | Global reveal schedule |

No other entry-level fields are defined for Version 0.1.

All quotations in an entry inherit the entry's metadata, priority, font preference, presentation style, eligibility, and reveal configuration.

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

An absent `font` field means that no specific font preference is expressed.

An explicit empty string or invalid field type is a validation error.

The resolution of preferred fonts, fallback behavior, warnings, and persistence of the selected font are defined in `docs/ARCHITECTURE.md`.

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

Application configuration and content files must conform to their respective schemas before being accepted.

Validation includes:

- valid YAML syntax and one top-level mapping;
- required fields and supported field names;
- permitted value types;
- valid timezone identifiers;
- valid time strings and reveal-schedule constraints;
- valid entry identifiers and uniqueness across the content library;
- nonempty quotation collections and quotation strings;
- supported eligibility rules and valid calendar values;
- valid integer priorities;
- valid normalized quotation-region coordinates;
- valid font-size bounds;
- user-registered font identifiers that do not collide with reserved bundled identifiers;
- nonempty user-registered font identifiers and file paths;
- existing, readable, supported user-registered font files;
- a nonempty default font pool;
- default font identifiers present in the effective font registry;
- no duplicate identifiers in the default font pool.

Invalid explicit configuration values must not be silently replaced by defaults.

Every font explicitly registered in application configuration must be valid, even when no content entry currently references it.

Content-entry font preferences have a different validation rule: an unregistered but otherwise valid font identifier is permitted.

An empty or non-string content-entry font value is invalid.

Diagnostics must identify the affected file and field, with sufficient information to correct the error.

Warnings for unavailable content-entry font preferences are required by the architecture.

Unknown fields are validation errors.

A content library containing invalid entries must not be treated as successfully validated.

Recovery from invalid or unavailable source content is defined in `docs/ARCHITECTURE.md`.

## Compatibility and extension

The initial schemas are the public interface for Version 0.1 content and application configuration.

New fields must be introduced deliberately and documented here.

Existing field meanings must not change silently.

Unsupported or unknown fields are errors.

Version-specific migration support may be introduced when a real compatibility requirement emerges.

Refrain must not interpret arbitrary YAML metadata as executable instructions, renderer commands, or external actions.

The eventual content editor, if implemented, must produce files conforming to this specification.

## Out of scope

The initial formats do not define:

- per-quotation metadata or font overrides;
- arbitrary eligibility expressions;
- weekday or holiday calculation rules;
- complex recurrence expressions;
- dynamically downloaded content;
- inline scripts;
- arbitrary presentation templates;
- per-entry presentation regions or font-size limits;
- per-entry layout customization beyond the defined font preference;
- automatic font-family selection based on text-fitting performance;
- font repetition histories or weighted font selection;
- content-triggered external actions;
- multiple configured physical displays;
- interactive content editing.

These capabilities may be evaluated for later releases according to the roadmap.