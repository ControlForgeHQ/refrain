# Content Entries

This document defines Refrain's Version 0.1 content-entry YAML interface: field names, types, required values, defaults, supported values, and validation constraints.

Each content file contains exactly one entry. An entry contains one or more quotations and the metadata, actions, eligibility, priority, and presentation preferences shared by all of them. A quotation requiring different treatment belongs in a separate entry.

[Application Configuration](CONFIGURATION.md) owns application-wide settings, palettes, and named-pool declarations. [Architecture](../ARCHITECTURE.md) owns runtime interpretation, preference resolution, selection, scheduling, commitment, rendering, and recovery. [Engineering](../ENGINEERING.md) owns implementation and testing requirements. [CLI](../CLI.md) owns command syntax and viewer overrides.

Asset packages and manifests remain in [Content and Configuration Format](CONTENT_FORMAT.md#font-registry) pending a separate `ASSETS.md`. Publication formats remain in [Publication Metadata](PUBLICATION_METADATA.md) and [Publication Manifest](PUBLICATION_MANIFEST.md) pending consolidation into `PUBLICATION.md`. Those planned documents are not prerequisites for using this schema.

## YAML document

- Use UTF-8. The recommended extension is `.yaml`.
- Use exactly one YAML document containing one top-level mapping.
- Use spaces for indentation; two spaces are recommended.
- Use ordinary mappings, sequences, strings, integers, and booleans as specified below.
- Do not use custom tags, executable object constructors, anchors, aliases, merge keys, duplicate mapping keys, or implicit application-specific expressions.
- Quote values resembling dates, times, numbers, or booleans when a string is required. Unquoted scalar strings are accepted when the parser produces the intended string value.
- Boolean values do not satisfy integer fields. A supplied null is invalid unless a field's recovery rule expressly handles it.

Multiple entries in a sequence, wrapper mappings containing entries, multiple YAML documents, and per-quotation mappings are not Version 0.1 entry formats.

### Quotation strings

Use folded style when source-file wrapping should become one displayed paragraph:

```yaml
quotations:
  - >-
    This quotation occupies several
    source-file lines but becomes
    one continuous paragraph.
```

Use literal style for meaningful line breaks and paragraphs:

```yaml
quotations:
  - |-
    The first line remains separate.
    The second line remains separate.

    A blank line separates paragraphs.
```

The `-` after `>` or `|` suppresses the final trailing newline. Otherwise that newline is part of the parsed string. Parsed quotation text is retained for display; source-file wrapping is not reinterpreted after YAML parsing. These snippets illustrate a field; complete files also require `id`.

## Entry fields

| Field | Type | Required | Default when omitted |
|---|---|---|---|
| `id` | String | Yes | None. |
| `quotations` | Nonempty sequence of strings | Yes | None. |
| `source` | String | No | Absent. |
| `attribution` | String | No | Absent. |
| `actions` | Sequence of action mappings | No | Empty sequence. |
| `priority` | Integer | No | `0`. |
| `font` | Resource identifier or font-pool reference string | No | No entry preference. |
| `font_faces` | Mapping of literary roles to face identifier strings | No | No role preferences. |
| `text_color` | Palette identifier, text-color-pool reference, or nonempty sequence of either | No | No entry preference. |
| `decoration_color` | Palette identifier, decoration-color-pool reference, or nonempty sequence of either | No | No entry preference. |
| `background` | Resource identifier, background-pool reference, or `"none"` | No | No entry preference. |
| `decoration` | Resource identifier, decoration-pool reference, or `"none"` | No | No entry preference. |
| `presentation_style` | String | No | `"centered"`. |
| `eligibility` | Nonempty sequence of eligibility-rule mappings | No | Ordinary eligibility. |
| `reveal` | Mapping of reveal-time overrides | No | No entry overrides; inherit the global schedule. |

No other entry-level fields are defined. All quotations inherit all entry-level properties, including `font_faces` and both color preferences. They have no independently assigned identifiers, metadata, actions, or overrides.

Unknown fields invalidate the entry, subject to the explicitly recoverable action and color-member cases below. Omitting an optional field uses its documented absence or default; it does not make an explicitly invalid value equivalent to omission.

## Entry identifiers

`id` is a nonempty, case-sensitive ASCII string matching `[A-Za-z0-9][A-Za-z0-9_-]*`. It begins with a letter or digit and contains only letters, digits, hyphens, and underscores.

Identifiers must be unique across the accepted content library. All entries participating in a detected identifier conflict are excluded; filesystem enumeration order must not choose a winner. Diagnostics identify the conflicting entries.

Use short, descriptive, stable identifiers, such as `"amazing-grace"`. File names and directory locations do not define entry identity. This schema specifies no numerical length cap for entry IDs.

## Quotations, source, and attribution

`quotations` is a nonempty sequence. Each member must be a string containing meaningful text. Empty and whitespace-only strings are invalid; an invalid member invalidates the entry rather than silently removing a quotation.

Quotation strings retain parsed Unicode content, punctuation, and intended line breaks. There is no project-defined maximum quotation count or arbitrary quotation-length limit. A valid quotation may still fail presentation validation or image preparation if it cannot fit the supported layout. Quotation identity and repetition tracking are defined by [Architecture](../ARCHITECTURE.md#quotation-identity), separately from displayed text.

`source` identifies where a quotation originates. `attribution` identifies the person, group, or other entity to which it is attributed. Both are optional; each must be a nonempty string when supplied. They are not restricted to song titles or artists:

```yaml
source: "A Book Title"
attribution: "An Author"
```

Omitted metadata has no visible field to reveal. A null or empty string does not express absence; omit the field instead.

## Actions

Actions are optional, ordered, opaque declarations. Refrain validates their generic envelope. It does not maintain a type registry, interpret payloads, or execute actions. An entry's action sequence applies unchanged to every quotation.

```yaml
actions:
  - type: "play"
    visibility: ["private"]
  - type: "custom_action"
    visibility: ["public", "private"]
    payload: |
      { "opaque": "consumer-defined text" }
```

Each action mapping supports exactly these fields:

| Field | Type | Required | Default |
|---|---|---|---|
| `type` | String | Yes | None. |
| `visibility` | Nonempty sequence of audience strings | Yes | None. |
| `payload` | String | No | `""`. |

- `type` uses the same case-sensitive ASCII identifier syntax as an entry ID. Any syntactically valid type is accepted.
- `visibility` explicitly lists `public`, `private`, or both, without repetition. Each audience grants permission only for that named audience; there is no default or implied relationship.
- `payload` is an opaque parsed string, preserved exactly including whitespace and newlines. Its UTF-8 encoded length must not exceed 10,240 bytes. Refrain does not parse embedded formats, validate consumer-specific fields, interpret URLs or encodings, normalize payload whitespace, or execute commands.
- Declaration order and duplicates are preserved. Duplicate types and identical actions are valid. No action IDs, merging, sorting, deduplication, dependencies, or per-quotation actions are defined.
- At most 100 valid actions are accepted per entry. Malformed actions do not consume the limit. After 100 valid actions, later actions are ignored with a warning.

A malformed action is discarded with a warning, without rejecting its entry or other actions. This includes a non-mapping member, missing or invalid required field, unsupported or duplicate visibility, non-string or oversized payload, or unsupported envelope field. A malformed top-level `actions` value is warned about and treated as an empty sequence. An empty sequence is valid.

These recovery rules do not repair invalid YAML or override required-entry validation. Invalid YAML still excludes the file.

Destination-audience filtering, capture in the committed selection, snapshot recovery, and publication inclusion are owned by [Architecture](../ARCHITECTURE.md#destination-specific-metadata-and-audiences). Publication serialization is outside this content schema.

## Priority

`priority` is a signed integer, defaulting to `0`. Negative values are valid. There is no project-defined minimum or maximum. Booleans and floating-point values are invalid.

```yaml
priority: -5
```

Priority is inherited by every quotation. Its place after date specificity and repetition eligibility belongs to [Architecture](../ARCHITECTURE.md#selection-priority).

## Presentation preferences

Content fields express preferences using stable resource or palette identifiers. They do not register resources, define asset packages, declare named pools, embed file paths, or provide application-wide settings.

### Identifiers and pool references

Resource and palette identifiers use the shared case-sensitive ASCII syntax `[A-Za-z0-9][A-Za-z0-9_-]*`. A resource-selection string beginning with `@` denotes a named pool in that field's category. The name after `@` uses that same syntax. References do not cross categories.

| Entry field | Pool namespace in application configuration |
|---|---|
| `font` | `fonts.pools` |
| `background` | `backgrounds.pools` |
| `decoration` | `decorations.pools` |
| `text_color` | `text.colors.pools` |
| `decoration_color` | `decorations.colors.pools` |

`@default` and `@builtin` are references within the corresponding category. `none` is a reserved suppression value for backgrounds and decorations only; it is not a generic null, font suppression, or color suppression value.

Named-pool declarations and reserved membership are defined in [Application Configuration](CONFIGURATION.md#resources-and-named-pools). Pool expansion, equal-probability selection among distinct candidates, fallback from empty preferences, and diagnostic behavior belong to [Architecture](../ARCHITECTURE.md#daily-background-and-decoration-selection). Referencing a pool does not embed or define it in an entry.

A syntactically valid but unavailable font, background, or decoration preference does not invalidate the entry. This permits sharing libraries across installations with different resources. Absence of an entry preference permits the established lower-level preference or automatic selection; it does not itself specify a concrete selected resource.

### Font

`font` accepts one nonempty string: a font-bundle identifier or a font-pool reference.

```yaml
font: "lora"
```

Alternatively:

```yaml
font: "@literary"
```

A registered font need not belong to the default pool to be preferred explicitly. There is no list form, direct font-file path interface, or `none` suppression value. An empty string, null, or non-string value is invalid.

The documented resolution order is the entry preference, selected decoration preference, then automatic selection from the effective default font pool. A usable explicit entry or decoration preference does not require a usable default pool. Availability checks, warnings, font loading, and fallback are owned by [Architecture](../ARCHITECTURE.md#font-selection).

### Font faces

The optional `font_faces` mapping accepts only the `quotation`, `source`, and `attribution` roles. Each role is optional; an empty mapping expresses no preferences.

```yaml
font_faces:
  quotation: "handwritten"
  source: "regular"
  attribution: "italic"
```

Each value must be a nonempty, case-sensitive ASCII face identifier using the shared identifier syntax. Unknown roles, non-mapping values, explicit nulls, empty strings, and invalid identifiers reject the entry without rejecting unrelated entries.

A syntactically valid face need not exist in every bundle. This mapping does not select a bundle and has no catch-all role or per-quotation form. The first defined role preference wins in the order entry, decoration, bundle manifest, global `fonts.faces`, then implicit `regular`. An explicit `regular` overrides lower preferences. If the winning face is unavailable, that bundle's `regular` face is used with a warning; lower-level face preferences are not consulted. Runtime face resolution is owned by [Architecture](../ARCHITECTURE.md#font-selection).

### Background

`background` accepts one nonempty string: a background identifier, background-pool reference, or `"none"`.

```yaml
background: "aged-paper"
```

Alternatively:

```yaml
background: "@subtle"
```

Or explicitly suppress background selection:

```yaml
background: "none"
```

An explicit `none` requests the paper-white base and overrides both the decoration's preferred background and the default background pool. Omission permits an available decoration preference, then automatic selection from the effective default pool. An unavailable identifier warns and follows the established fallback without invalidating the entry. Empty strings, non-string values, and null are invalid. There is no list form.

### Decoration

`decoration` accepts one nonempty string: a decoration identifier, decoration-pool reference, or `"none"`.

```yaml
decoration: "lower-flourish"
```

Alternatively:

```yaml
decoration: "@minimal"
```

Or explicitly suppress decoration selection:

```yaml
decoration: "none"
```

Omission means automatic selection from the effective default decoration pool. Explicit `none` suppresses that pool and uses the global presentation insets. An unavailable identifier warns and falls back to the default decoration pool without invalidating the entry. Empty strings, non-string values, and null are invalid. There is no list form.

A selected decoration may supply insets, font and background preferences, and other asset-side presentation preferences. Entry font and background preferences take precedence over corresponding decoration preferences. Content entries cannot directly specify insets, font-size bounds, layers, transformations, or asset manifests.

### Text color

`text_color` accepts a palette identifier, text-color-pool reference, or nonempty sequence containing either:

```yaml
text_color: "black"
```

Alternatively:

```yaml
text_color: ["black", "@neutral"]
```

Direct RGB values and RGB component lists are unsupported. Palette availability is evaluated during preparation. Unknown, malformed, or unavailable preference members are diagnosed and excluded; a preference with no usable members falls through without invalidating the entry. Duplicate identifiers do not add weight.

The documented fallback order is entry, selected background, selected decoration, effective global text-color pool, then built-in `black`. Candidates from different levels are not combined. Runtime selection is owned by [Architecture](../ARCHITECTURE.md#daily-background-and-decoration-selection).

### Decoration color

`decoration_color` accepts a palette identifier, decoration-color-pool reference, or nonempty sequence containing either:

```yaml
decoration_color: ["black", "@muted"]
```

It uses the shared palette but an independent pool namespace. Direct RGB values and RGB component lists are unsupported. Invalid or unavailable members do not invalidate the entry; they are diagnosed and excluded. Duplicate identifiers do not add weight.

The documented fallback order is entry, selected background, selected decoration, effective global decoration-color pool, then built-in `black`, without combining levels. This preference affects only effectively tintable selected decoration layers; it never recolors the background. No decoration color is resolved when no layer is effectively tintable. Runtime tinting and selection belong to [Architecture](../ARCHITECTURE.md#decoration-tinting).

### Presentation style

`presentation_style` accepts exactly one of these case-sensitive strings:

| Value | Meaning |
|---|---|
| `"centered"` | Quotation lines are independently centered horizontally; the quotation block is vertically centered in its allocated space. |
| `"left-aligned"` | Quotation lines share a left edge. The complete block is horizontally centered by its widest rendered line, rather than anchored to the literary rectangle's left edge, and vertically centered in its allocated space. The byline is right-aligned in the literary rectangle. |

Omission uses `"centered"`. Unknown identifiers, empty strings, null, and non-string values invalidate the entry. Both styles use subordinate source and attribution presentation. There are no per-quotation styles. Detailed layout and stable progressive composition belong to [Architecture](../ARCHITECTURE.md#initial-visual-design).

## Eligibility

`eligibility`, when supplied, is a nonempty sequence of rule mappings. Each mapping must match exactly one supported form. Rules are alternatives; declaration order does not establish precedence.

| Exact fields | Valid values | Calendar condition |
|---|---|---|
| `ordinary` | Boolean `true` only | Ordinary eligibility. |
| `year`, `month`, `day` | Positive integer year; month 1–12; day 1–31; date must exist | One calendar date. |
| `month`, `day` | Integer month 1–12 and day 1–31; combination must exist in at least one year | Recurring annual date. |
| `day` | Integer 1–31 | That day in each month containing it. |
| `month` | Integer 1–12 | Every day in that month. |

Booleans and floating-point values are not integer calendar components. Unknown fields, unsupported field combinations, non-mapping members, nulls, and an empty sequence are invalid. Year-only and year-month rules are unsupported. `ordinary` cannot be combined with calendar components.

Omission supplies ordinary eligibility. A date-only declaration does not implicitly add ordinary eligibility; include `ordinary: true` explicitly to express both:

```yaml
eligibility:
  - month: 10
    day: 17
  - ordinary: true
```

Recurring February 29 is valid and matches only leap years. A full date such as February 29 in a non-leap year is invalid. `day: 31` is valid and does not match months without a 31st day. No arbitrary upper limit on the positive year field is defined here.

Matching, highest-specificity interpretation (year-month-day, month-day, day, month, ordinary), display-date calculation, priority, repetition, and pool exhaustion are owned by [Architecture](../ARCHITECTURE.md#content-eligibility-and-selection).

## Per-entry reveal overrides

`reveal` is an optional mapping containing only `source` and `attribution`. Each property is optional; an empty mapping supplies no overrides.

```yaml
reveal:
  source: "09:00"
  attribution: "09:00"
```

Each supplied value is a local-time string in exactly 24-hour `HH:MM` notation, with hours `00`–`23` and minutes `00`–`59`. Seconds, timezone suffixes, loose forms such as `"9:00"`, null, and non-string values are invalid.

Unspecified values inherit the global schedule from [Application Configuration](CONFIGURATION.md#scheduling). The quotation begins at the configured display-day start. There is no content `reveal.quotation`, per-entry day start, or timezone field.

Effective source and attribution times must be on the same local calendar date as, and no earlier than, the configured day start. They may equal day start, equal each other, or occur in either order. An override producing an unsupported or contradictory effective schedule is invalid. An overnight time before day start is not interpreted as the following day.

Intrinsic syntax validation does not replace effective-schedule validation against application configuration. Commitment, cumulative stages, absent metadata, clock changes, and recovery belong to [Architecture](../ARCHITECTURE.md#progressive-reveal). Later edits to content or global scheduling do not change the committed schedule.

## Complete examples

Each block below is a separate, complete content file. Examples using named pools or custom resources require corresponding configuration or available resources for those preferences to be usable; unavailable preferences retain the documented fallback behavior.

### Ordinary entry with multiple quotations

```yaml
id: "example-book"
source: "An Example Book"
attribution: "Example Author"
quotations:
  - "A short quotation."
  - >-
    A longer quotation whose source-file
    wrapping becomes one paragraph.
  - |-
    A quotation with meaningful
    line breaks.

    A second paragraph.
```

### Presentation preferences, faces, and actions

```yaml
id: "example-poem"
source: "A Collection of Poetry"
attribution: "An Example Poet"
priority: -5
font: "lora"
font_faces:
  quotation: "regular"
  source: "italic"
  attribution: "regular"
background: "none"
decoration: "none"
text_color: ["black", "@neutral"]
decoration_color: ["black", "@muted"]
presentation_style: "left-aligned"
actions:
  - type: "play"
    visibility: ["private"]
  - type: "custom_action"
    visibility: ["public", "private"]
    payload: |-
      This text belongs to an external consumer.
      Refrain preserves it without interpreting it.
eligibility:
  - ordinary: true
reveal:
  source: "12:00"
  attribution: "18:00"
quotations:
  - |-
    The first line of a poem,
    followed by the second.
```

The explicit reveal times require a configured day start no later than `12:00`, as with the default `05:00`. Decoration color has no rendering effect with `decoration: "none"`.

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

### One-time special date

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
source: "An Example Source"
attribution: "An Example Author"
eligibility:
  - year: 2026
    month: 10
    day: 17
  - month: 10
    day: 17
  - ordinary: true
reveal:
  source: "10:00"
quotations:
  - "A quotation with more than one eligibility context."
```

The source override requires a configured day start no later than `10:00` and a valid inherited attribution time.

## Validation and diagnostics

Content must be parsed and validated before acceptance. Validation must not silently reinterpret malformed entries, invent quotations, or rewrite author-maintained files.

| Problem | Required result |
|---|---|
| Invalid or unsupported YAML, invalid encoding, or unreadable content file | Exclude the file with an actionable warning; preserve unrelated usable files. |
| Missing required field, invalid ID, invalid quotation, unknown entry field, invalid priority, malformed face mapping, unsupported style, eligibility, or reveal declaration | Exclude the affected entry with an actionable diagnostic. |
| Duplicate entry IDs | Exclude every conflicting accepted entry and identify conflicts. |
| Malformed action or malformed action collection | Apply the action-specific recovery rules; preserve the entry. |
| Syntactically valid but unavailable font, background, or decoration preference | Keep the entry; warn and follow Architecture's resource fallback rules. |
| Unusable color preference members | Diagnose and exclude those members; follow the color preference recovery contract. |
| Missing or inaccessible content directory, unsuccessful source discovery, no content files, or no valid quotations | Content-library failure; no new selection from that library. |

One entry per file is the supported format, so excluding an entry excludes that file's entry. General references elsewhere to independently validated entries do not authorize a multi-entry format.

A partial library is usable when discovery and loading complete and at least one valid quotation remains. Invalid individual files or entries must not invalidate unrelated valid content.

Diagnostics identify the affected file and field or entry, where applicable, and explain whether an item was rejected, excluded, or ignored. Warnings must be actionable and must not repeatedly flood ordinary logs.

For content diagnostics, `INFO` denotes application of a documented default because an optional value was omitted. `WARNING` identifies a recoverable problem or rejected item when usable content remains available. `ERROR` identifies an unsatisfied required library condition. Logging, notice consolidation, and process-output requirements belong to [Engineering](../ENGINEERING.md#logging-and-diagnostics). Application-configuration diagnostic behavior is defined separately in [Application Configuration](CONFIGURATION.md#validation-and-compatibility).

Repetition-history cleanup, the effect of rejected entries on repetition identity, successful-selection commitment, and independence of an already committed selection belong to [Architecture](../ARCHITECTURE.md#selection-pools-and-repetition). A library-level failure must not be treated as an intentionally empty library for cleanup.

## Compatibility and limits

This is a Version 0.1 public interface. New fields and changed meanings require deliberate documentation and review. Unknown entry fields are not an extension mechanism. Future editors must produce this format.

Version 0.1 does not define per-quotation metadata or preferences, arbitrary eligibility expressions, weekday or holiday calculations, complex recurrences, content-level insets or font-size bounds, content-level QR controls, arbitrary executable metadata, or renderer commands. Opaque actions remain declarations for consumers, not instructions executed by Refrain.

