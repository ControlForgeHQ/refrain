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
  font_size: 72
  margin: 80
```

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

The initial release supports one typography-first presentation layout.

The initial public configuration surface is:

| Field | Type | Required | Default |
|---|---|---|---|
| `layout.font_size` | Positive integer | No | Layout-defined |
| `layout.margin` | Nonnegative integer | No | Layout-defined |

Values are expressed in output-image pixels at the configured display resolution.

`font_size` specifies the nominal quotation text size.

`margin` specifies the minimum outer content margin.

Additional layout fields may be introduced when the actual layout is designed and validated.

The initial configuration format does not provide an arbitrary layout language, custom drawing commands, or a general theme engine.

Physical display selection and hardware-specific resolution are not configurable through these fields in Version 0.1.

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
| `eligibility` | Sequence of eligibility rules | No | Ordinary eligibility |
| `reveal` | Mapping of reveal overrides | No | Global reveal schedule |

No other entry-level fields are defined for Version 0.1.

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

Quotation identity is derived from the parsed quotation text.

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

Source, attribution, eligibility, entry ID, and priority do not form part of quotation identity.

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
- permitted priority values.

Invalid explicit values must not be silently replaced by defaults.

Diagnostics should identify the affected file, field, and reason for rejection.

A content library containing invalid entries must not be treated as successfully validated.

The application may continue presenting a previously committed valid daily snapshot when the source library is unavailable or invalid, as required by the architecture.

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

- per-quotation metadata overrides;
- arbitrary eligibility expressions;
- weekday or holiday calculation rules;
- complex recurrence expressions;
- dynamically downloaded content;
- inline scripts;
- arbitrary presentation templates;
- per-entry layout customization;
- content-triggered external actions;
- multiple configured physical displays;
- interactive content editing.

These capabilities may be evaluated for later releases according to the roadmap.