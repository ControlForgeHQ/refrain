# Content Entries

This document specifies the YAML format for Refrain content entries, including quotations, metadata, actions, presentation preferences, eligibility rules, reveal overrides, and validation requirements.

## YAML document

- Use UTF-8. The recommended extension is `.yaml`.
- Use exactly one YAML document containing one top-level mapping.
- Use spaces for indentation; two spaces are recommended.
- Use ordinary mappings, sequences, strings, integers, and booleans as specified below.
- Do not use custom tags, executable object constructors, anchors, aliases, merge keys, duplicate mapping keys, or implicit application-specific expressions.
- Quote values resembling dates, times, numbers, or booleans when a string is required. Unquoted scalar strings are accepted when the parser produces the intended string value.
- Boolean values do not satisfy integer fields. A supplied null is invalid unless a field's recovery rule expressly handles it.

Each file must contain exactly one entry mapping. Multiple entries, wrapper mappings, multiple YAML documents, and per-quotation mappings are invalid.

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
| `qr` | Sequence of QR declaration mappings | No | No entry-level QR overrides. |
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

No other entry-level fields are defined. All quotations inherit all entry-level properties, including QR declarations, `font_faces`, and both color preferences. They have no independently assigned identifiers, metadata, actions, or overrides.

Unknown fields invalidate the entry, subject to the explicitly recoverable action, QR, and color-member cases below. Omitting an optional field uses its documented absence or default; it does not make an explicitly invalid value equivalent to omission.

## Entry identifiers

`id` is a nonempty, case-sensitive ASCII string matching `[A-Za-z0-9][A-Za-z0-9_-]*`. It begins with a letter or digit and contains only letters, digits, hyphens, and underscores.

Identifiers must be unique across the accepted content library. All entries participating in a detected identifier conflict are excluded; filesystem enumeration order must not choose a winner. Diagnostics identify the conflicting entries.

Use short, descriptive, stable identifiers, such as `"amazing-grace"`. File names and directory locations do not define entry identity. This schema specifies no numerical length cap for entry IDs.

## Quotations, source, and attribution

`quotations` is a nonempty sequence. Each member must be a string containing meaningful text. Empty and whitespace-only strings are invalid; an invalid member invalidates the entry rather than silently removing a quotation.

Quotation strings retain parsed Unicode content, punctuation, and intended line breaks. There is no project-defined maximum quotation count or arbitrary quotation-length limit. A valid quotation may still fail presentation validation or image preparation if it cannot fit the supported layout. Quotation identity is defined by [Entry and quotation identity](../specifications/20-CONTENT_AND_CONFIGURATION.md#entry-and-quotation-identity) and repetition tracking by [Repetition cleanup and pool exhaustion](../specifications/30-SELECTION_AND_PERSISTENCE.md#repetition-cleanup-and-pool-exhaustion), separately from displayed text.

`source` identifies where a quotation originates. `attribution` identifies the person, group, or other entity to which it is attributed. Both are optional; each must be a nonblank string when supplied, containing at least one non-whitespace character. Leading and trailing whitespace in otherwise valid metadata is preserved without trimming or normalization. They are not restricted to song titles or artists:

```yaml
source: "A Book Title"
attribution: "An Author"
```

Omitted metadata has no visible field to reveal. A null, empty, or whitespace-only string does not express absence; omit the field instead.

## Actions

Actions are optional, ordered, opaque declarations. Refrain validates their generic envelope. It does not maintain a type registry, interpret payloads, or execute actions. An entry's action sequence applies unchanged to every quotation.

```yaml
actions:
  - type: "play"
    visibility: ["internal"]
  - type: "custom_action"
    visibility: ["external", "internal"]
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
- `visibility` explicitly lists `external`, `internal`, or both, without repetition. Each declaration is eligible only for the named audiences; there is no default or implied relationship.
- `payload` is an opaque parsed string, preserved exactly including whitespace and newlines. Its UTF-8 encoded length must not exceed 10,240 bytes. Refrain does not parse embedded formats, validate consumer-specific fields, interpret URLs or encodings, normalize payload whitespace, or execute commands.
- Declaration order and duplicates are preserved. Duplicate types and identical actions are valid. No action IDs, merging, sorting, deduplication, dependencies, or per-quotation actions are defined.
- At most 100 valid actions are accepted per entry. Malformed actions do not consume the limit. After 100 valid actions, later actions are ignored with a warning.

A malformed action is discarded with a warning, without rejecting its entry or other actions. This includes a non-mapping member, missing or invalid required field, unsupported or duplicate visibility, non-string or oversized payload, or unsupported envelope field. A malformed top-level `actions` value is warned about and treated as an empty sequence. An empty sequence is valid.

These recovery rules do not repair invalid YAML or override required-entry validation. Invalid YAML still excludes the file.

Capture in the committed selection and snapshot recovery are owned by [Selection and Persistence](../specifications/30-SELECTION_AND_PERSISTENCE.md); destination-audience filtering and publication inclusion are owned by [Destination metadata and audience filtering](../specifications/70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#destination-metadata-and-audience-filtering). Publication serialization is outside this content schema.

## QR payloads

An entry may declare QR payload overrides for the `external` and `internal` audiences. These declarations apply to every quotation in the entry.

```yaml
qr:
  - visibility: ["external"]
    payload: "https://example.org"
  - visibility: ["internal"]
    payload: null
```

Each declaration contains exactly:

| Field | Type | Required | Constraint |
|---|---|---|---|
| `visibility` | Sequence of one string | Yes | Exactly `["external"]` or `["internal"]`. |
| `payload` | String or null | Yes | Nonempty UTF-8 string of at most 62 bytes, or null. |

String payloads are opaque and preserved exactly after YAML parsing. No payload-specific interpretation or normalization is performed.

A null payload explicitly suppresses the inherited payload for its audience. An omitted declaration leaves that audience's configured default unchanged. A missing payload field is invalid, not an instruction to suppress QR.

Accept the first valid declaration for each audience. Warn and discard subsequent declarations for that audience, including those following an accepted null declaration.

Malformed declarations are discarded with warnings without invalidating the entry. A malformed top-level `qr` value provides no entry-level overrides. Discarded declarations do not suppress inherited defaults. Valid declarations for the other audience remain effective.

QR precedence is defined in [QR payload resolution](../specifications/20-CONTENT_AND_CONFIGURATION.md#qr-payload-resolution). Resolved publication data is defined in [Publication](PUBLICATION.md#qr-payloads).

## Priority

`priority` is a signed integer, defaulting to `0`. Negative values are valid. There is no project-defined minimum or maximum. Booleans and floating-point values are invalid.

```yaml
priority: -5
```

Priority is inherited by every quotation. Its place after date specificity and repetition eligibility belongs to [Candidate identity and priority](../specifications/30-SELECTION_AND_PERSISTENCE.md#candidate-identity-and-priority).

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

Named-pool declarations and reserved membership are defined in [Application Configuration](CONFIGURATION.md#resources-and-named-pools). Pool expansion and invalid-member diagnostics are specified in [Named pools and membership](../specifications/20-CONTENT_AND_CONFIGURATION.md#named-pools-and-membership). Artistic selection and fallback are specified in [Canonical resolution and resource precedence](../specifications/50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence).

A syntactically valid but unavailable font, background, or decoration preference does not invalidate the entry. This permits sharing libraries across installations with different resources. Absence of an entry preference permits the established lower-level preference or automatic selection; it does not itself specify a concrete selected resource.

### Font

`font` accepts one nonblank string matching the shared resource-identifier or font-pool-reference syntax: a font-bundle identifier or a font-pool reference.

```yaml
font: "lora"
```

Alternatively:

```yaml
font: "@literary"
```

A registered font need not belong to the default pool to be preferred explicitly. There is no list form or direct font-file path interface. The reserved value `none` is not a font preference and invalidates the entry. Empty, whitespace-only, malformed, null, and non-string values are also invalid. A syntactically valid but unavailable font identifier does not invalidate the entry; normal resource fallback applies.

Font preference precedence and fallback are specified in [Canonical resolution and resource precedence](../specifications/50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence).

### Font faces

The optional `font_faces` mapping accepts only the `quotation`, `source`, and `attribution` roles. Each role is optional; an empty mapping expresses no preferences.

```yaml
font_faces:
  quotation: "handwritten"
  source: "regular"
  attribution: "italic"
```

Each value must be a nonempty, case-sensitive ASCII face identifier using the shared identifier syntax. Unknown roles, non-mapping values, explicit nulls, empty strings, and invalid identifiers reject the entry without rejecting unrelated entries.

A syntactically valid face need not exist in every bundle. This mapping does not select a bundle and has no catch-all role or per-quotation form. Role preference precedence and unavailable-face recovery are specified in [Font bundles, role faces and recovery](../specifications/50-PRESENTATION_AND_RENDERING.md#font-bundles-role-faces-and-recovery).

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

Empty strings, non-string values, and null are invalid; there is no list form. Omission leaves the entry without a background preference. `"none"` is an explicit suppression value. Preference precedence and fallback, including the effect of `"none"`, are specified in [Canonical resolution and resource precedence](../specifications/50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence).

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

Empty strings, non-string values, and null are invalid; there is no list form. Omission leaves the entry without a decoration preference. `"none"` is an explicit suppression value. Decoration preference resolution and fallback are specified in [Canonical resolution and resource precedence](../specifications/50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence).

### Text color

`text_color` accepts a palette identifier, text-color-pool reference, or nonempty sequence containing either:

```yaml
text_color: "black"
```

Alternatively:

```yaml
text_color: ["black", "@neutral"]
```

A declaration must be a string or a nonempty sequence. An invalid outer structure, including null, an empty sequence, a mapping, or another unsupported type, invalidates the entry. Within a structurally valid sequence, invalid member types, malformed identifiers, direct RGB literals, and unavailable identifiers are diagnosed and excluded individually without invalidating the entry. Valid members remain usable. If no usable members remain, the preference falls through to the next level. Duplicate identifiers do not add weight. Palette availability is evaluated during preparation.

Color preference precedence, selection, and fallback are specified in [Canonical resolution and resource precedence](../specifications/50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence).

### Decoration color

`decoration_color` accepts a palette identifier, decoration-color-pool reference, or nonempty sequence containing either:

```yaml
decoration_color: ["black", "@muted"]
```

It uses the shared palette but an independent pool namespace. The same structural and member-level validation rules as `text_color` apply: an invalid outer structure invalidates the entry, while invalid or unavailable individual candidates are diagnosed and excluded without invalidating the entry. A preference with no usable candidates falls through. Duplicate identifiers do not add weight.

Decoration-color preference precedence and fallback are specified in [Canonical resolution and resource precedence](../specifications/50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence). Effective tinting behavior is specified in [Colors and tinting](../specifications/50-PRESENTATION_AND_RENDERING.md#colors-and-tinting).

### Presentation style

`presentation_style` accepts exactly `"centered"` or `"left-aligned"` (case-sensitive). Omission uses `"centered"`. Unknown identifiers, empty strings, null, and non-string values invalidate the entry. The field applies to every quotation in the entry; per-quotation styles are unsupported.

Style-specific layout and byline behavior are specified in [Literary composition and fitting](../specifications/50-PRESENTATION_AND_RENDERING.md#literary-composition-and-fitting).

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

Matching, highest-specificity interpretation (year-month-day, month-day, day, month, ordinary), priority, repetition, and pool exhaustion are owned by [Selection and Persistence](../specifications/30-SELECTION_AND_PERSISTENCE.md); display-date calculation is owned by [Civil time and logical-date evaluation](../specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#civil-time-and-logical-date-evaluation).

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

Validate every supplied reveal override against the effective global schedule before admitting the entry to selection, including overrides for source or attribution fields absent from the entry. Later edits to content or global scheduling do not change the committed schedule. Commitment, cumulative stages, absent metadata, clock changes, and recovery belong to [Scheduling and Application Lifecycle](../specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md).

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
    visibility: ["internal"]
  - type: "custom_action"
    visibility: ["external", "internal"]
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
| Malformed QR declaration, duplicate audience, or malformed QR collection | Apply the QR-specific recovery rules; preserve the entry. |

One entry per file is the supported format, so excluding an entry excludes that file's entry. General references elsewhere to independently validated entries do not authorize a multi-entry format.

A partial library is usable when discovery and loading complete and at least one valid quotation remains. Invalid individual files or entries must not invalidate unrelated valid content.

Recursive source discovery, symbolic-link exclusion, incomplete enumeration, and library-level failure handling are specified in [Content and Configuration](../specifications/20-CONTENT_AND_CONFIGURATION.md#library-loading-and-validation). A successfully loaded, usable library containing no quotation eligible for the current display date follows the [no-eligible-content fallback](../specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#no-eligible-content-fallback), not the library-failure behavior.

Diagnostics identify the affected file and field or entry, where applicable, and explain whether an item was rejected, excluded, or ignored. Warnings must be actionable and must not repeatedly flood ordinary logs.

Omitted optional content-entry fields use their documented defaults or absence semantics silently. No informational diagnostic is required or emitted solely because an optional field was omitted.

For content diagnostics, `INFO` denotes useful operational information that does not indicate a configuration or content problem. `WARNING` identifies a recoverable problem or rejected item when usable content remains available. `ERROR` identifies an unsatisfied required library condition. Application-configuration diagnostic behavior is defined in [Application Configuration](CONFIGURATION.md#validation-and-compatibility).

Repetition-history cleanup, the effect of rejected entries on repetition identity, successful selection commitment, and independence of an already committed selection belong to [Selection and Persistence](../specifications/30-SELECTION_AND_PERSISTENCE.md). A library-level failure must not be treated as an intentionally empty library for cleanup.

## Interface constraints

Unknown entry fields are invalid. Content entries do not support per-quotation metadata or presentation preferences, arbitrary eligibility expressions, content-level presentation geometry, or executable instructions.

Opaque actions are declarations for external consumers; Refrain does not execute them.

