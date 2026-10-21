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

layout:
  quotation_region:
    x: 0.10
    y: 0.15
    width: 0.80
    height: 0.55

  fonts:
    default:
      - "liberation-serif"
      - "dejavu-serif"
      - "liberation-sans"

    available:
      liberation-serif: "fonts/LiberationSerif-Regular.ttf"
      dejavu-serif: "fonts/DejaVuSerif.ttf"
      liberation-sans: "fonts/LiberationSans-Regular.ttf"

  text:
    min_font_size: 28
    max_font_size: 100
```

The example illustrates the initial configuration structure, including a bounded quotation region, a font registry, an automatic font-selection pool, and font-size limits.

Font paths, rectangle dimensions, and font-size values are examples rather than universal defaults. They must be adjusted to match the fonts and presentation layout provided by an installation.

This example describes the initial configuration structure. The presentation settings are intentionally limited until the first layout is defined and validated.

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

The quotation occupies a defined rectangular region. The renderer automatically determines an appropriate font size and line wrapping within that region.

The layout configuration defines:

- the permitted quotation region;
- available fonts;
- fonts eligible for automatic daily selection;
- minimum and maximum quotation font sizes.

A fixed quotation font size is not required.

### Quotation region

The `layout.quotation_region` mapping defines the rectangular area available for the primary quotation.

| Field | Type | Required |
|---|---|---|
| `layout.quotation_region.x` | Number | Yes |
| `layout.quotation_region.y` | Number | Yes |
| `layout.quotation_region.width` | Number | Yes |
| `layout.quotation_region.height` | Number | Yes |

Coordinates are normalized proportions of the rendered image dimensions.

- `x` identifies the region's left edge.
- `y` identifies the region's top edge.
- `width` identifies the region's horizontal extent.
- `height` identifies the region's vertical extent.

The image's top-left corner is `(0, 0)`, and its bottom-right corner is `(1, 1)`.

For example:

```yaml
layout:
  quotation_region:
    x: 0.10
    y: 0.15
    width: 0.80
    height: 0.55
```

The values must satisfy:

- `0 <= x < 1`
- `0 <= y < 1`
- `0 < width <= 1`
- `0 < height <= 1`
- `x + width <= 1`
- `y + height <= 1`

Boolean values are not valid coordinates.

The quotation region remains fixed throughout all reveal stages of a committed presentation.

The renderer may wrap text and adjust font size within this region but must not silently draw quotation text outside it.

Source and attribution information occupy separate reserved presentation regions defined by the initial layout. Their appearance must not cause the quotation region to change.

The initial release does not expose arbitrary positioning of every presentation element.

### Font registry

The `layout.fonts.available` mapping defines the fonts available to Refrain.

Each mapping key is a font identifier, and its value is the path to a supported font file.

For example:

```yaml
layout:
  fonts:
    available:
      liberation-serif: "fonts/LiberationSerif-Regular.ttf"
      dejavu-serif: "fonts/DejaVuSerif.ttf"
      liberation-sans: "fonts/LiberationSans-Regular.ttf"
```

Font identifiers must be nonempty strings and are case-sensitive.

Font paths must be nonempty strings.

Relative font paths are resolved relative to the directory containing `config.yaml`.

Absolute paths are permitted.

Every registered font must resolve to an existing, readable font file supported by the renderer.

An invalid, missing, or unreadable registered font is a configuration error, even if the font is not included in the automatic default pool.

Registered font validation must not silently discard invalid entries.

The font registry provides stable identifiers that content files can reference without embedding machine-specific filesystem paths.

### Default font pool

The `layout.fonts.default` field is a nonempty sequence of font identifiers.

For example:

```yaml
layout:
  fonts:
    default:
      - "liberation-serif"
      - "dejavu-serif"
      - "liberation-sans"
```

Every default identifier must exist in `layout.fonts.available`.

Duplicate identifiers are not permitted.

When a content entry does not specify a font, Refrain randomly selects one font from this pool for the new daily presentation.

Every default font has equal selection probability.

Font selection is independent for each committed daily selection.

The default font pool does not maintain a repetition history or exhaustion cycle. A font may be selected on consecutive days.

A registered font need not appear in the default pool. Such a font remains available for explicit selection by content entries.

Font selection occurs before daily snapshot commitment.

The actual resolved font is included in the committed daily snapshot and permanent global selection history.

The font is not part of quotation repetition identity.

### Automatic quotation fitting

The renderer automatically determines the quotation font size and line wrapping required to fit the selected text inside the configured quotation region.

The `layout.text` mapping establishes permitted font-size bounds.

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

The renderer selects the largest permitted font size that accommodates the complete quotation within the configured region.

It may wrap text at suitable word boundaries while preserving explicit line breaks and paragraph structure from the parsed quotation.

Automatic fitting must not alter the quotation's wording or punctuation.

Text must not be silently clipped, truncated, or omitted.

If the quotation cannot fit at the minimum permitted font size, preparation fails with a meaningful diagnostic.

The font-size bounds apply to the quotation region, not automatically to source or attribution text.

The selected font and resolved presentation configuration remain stable across every reveal stage of the committed selection.

The renderer's measurement and fitting implementation belongs in `docs/ENGINEERING.md`.

### Initial layout limitations

Version 0.1 provides one presentation layout.

The initial public format does not define:

- arbitrary layout templates;
- custom drawing commands;
- independent positioning of every presentation field;
- per-entry quotation regions;
- per-entry font-size overrides;
- automatic selection among different fonts based on fitting results;
- a general-purpose theme engine.

Display hardware selection and output resolution are not user-configurable through these layout fields in Version 0.1.

The normalized quotation region preserves future resolution flexibility without promising that the initial layout has been validated at every possible resolution.

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
| `eligibility` | Sequence of eligibility rules | No | Ordinary eligibility |
| `reveal` | Mapping of reveal overrides | No | Global reveal schedule |

No other entry-level fields are defined for Version 0.1.

All quotations in an entry inherit the entry's metadata, priority, font preference, eligibility, and reveal configuration.

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

Source and attribution are metadata associated with the selected quotation.

They do not participate in quotation identity or repetition tracking.

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

Priority does not override date specificity or the preference for unused quotations.

The architecture defines the ordering of priority and repetition rules.

### Font preference

`font` is an optional string specifying the preferred font for every quotation in the entry.

The value identifies a font in the application configuration's `layout.fonts.available` registry.

For example:

```yaml
id: "example-poem"

font: "dejavu-serif"

source: "A Collection of Poetry"

quotations:
  - |-
    The first line of a poem,
    followed by the second.
```

When the specified identifier exists in the font registry, Refrain uses that font for the selected quotation.

A content entry may specify any registered font, including one that is not part of the default font pool.

When `font` is omitted, Refrain randomly selects a font from `layout.fonts.default`.

When `font` identifies an unregistered font, Refrain:

1. Accepts the content entry as valid.
2. Logs a warning identifying the entry and unavailable font.
3. Uses the configured default font pool when resolving a daily selection from that entry.

An unavailable content-entry font preference must not prevent an otherwise valid entry from participating in quotation selection.

The warning should be issued when loading and validating the content library rather than repeatedly during daily selection.

An explicitly registered font whose underlying file is missing, unreadable, or invalid remains an application configuration error. Such errors must not trigger content-entry fallback.

The selected font is resolved once for the daily presentation, before snapshot commitment.

The actual selected font is included in the committed daily snapshot and permanent global selection history.

The original requested font preference remains unchanged in the content file.

The selected font does not influence quotation eligibility, priority, or repetition identity.

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

### Specificity and repetition

The format defines eligibility data; it does not redefine selection policy.

The applicable specificity precedence is:

1. Year-month-day
2. Month-day
3. Day
4. Month
5. Ordinary

Matching specificity takes precedence over priority and repetition status.

Repetition history, exhaustion, pool resets, and final selection are defined in `docs/ARCHITECTURE.md`.

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

## Quotation identity

Quotation identity is derived exclusively from the parsed quotation text.

Refrain normalizes identity by:

1. Applying Unicode NFC normalization.
2. Replacing consecutive whitespace characters with a single space.
3. Removing leading and trailing whitespace.

For example, these strings have the same repetition identity:

```yaml
quotations:
  - "A quotation with several words."
  - >-
    A quotation with
    several words.
```

Normalization does not modify the text used for presentation.

Spelling, capitalization, punctuation, and non-whitespace characters remain significant.

Source, attribution, eligibility, entry ID, priority, and font selection do not form part of quotation identity.

Selecting the same quotation with a different font does not make it a different quotation for repetition purposes.

The permanent global history may record the selected font for each committed presentation without changing the quotation's repetition identity.

Refrain is not required to detect semantically similar quotations with different text.

## Validation and diagnostics

Both application configuration and content files must be validated before their data is accepted.

Validation includes:

- YAML syntax;
- expected top-level structure;
- required fields;
- supported field names;
- correct value types;
- valid timezone identifiers;
- valid times and effective reveal schedules;
- valid entry identifiers;
- duplicate entry identifiers;
- nonempty quotation sequences;
- nonempty quotation strings;
- supported eligibility rules;
- valid calendar values;
- permitted priority values;
- valid normalized quotation-region coordinates;
- valid minimum and maximum font-size bounds;
- nonempty font registry identifiers and paths;
- existence, readability, and supported format of every registered font;
- nonempty default font pool;
- default font identifiers present in the font registry;
- duplicate identifiers in the default font pool.

Invalid explicit application configuration values must not be silently replaced by defaults.

Every registered font must be valid. An invalid registered font is a configuration error even if no content entry currently references it.

Content-entry font preferences are handled differently.

An unregistered content-entry font preference produces a warning and uses the configured default pool when the entry's quotation is selected. It does not invalidate the content entry.

An empty or otherwise invalid `font` value is a content validation error rather than a request for automatic selection.

Diagnostics should identify the affected file, field, and reason for an error or warning.

Warnings for unavailable content-entry font preferences should identify the requested font and affected entry.

A content library containing invalid entries must not be treated as successfully validated.

The application may continue presenting a previously committed valid daily snapshot when the source library is unavailable or invalid, as required by the architecture.

Font selection, fallback, and presentation resolution must occur before selection commitment. A committed selection must not be altered merely because font availability or configuration subsequently changes.

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
- per-entry quotation regions or font-size limits;
- per-entry layout customization beyond the defined font preference;
- automatic font-family selection based on text-fitting performance;
- font repetition histories or weighted font selection;
- content-triggered external actions;
- multiple configured physical displays;
- interactive content editing.

These capabilities may be evaluated for later releases according to the roadmap.