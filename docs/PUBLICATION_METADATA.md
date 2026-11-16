# Publication metadata format

This specification defines the single JSON metadata schema used by prepared
scheduled images and completed publications. Both use schema version `1`.
Preparation and publication differ only in which publication-envelope fields
have been populated and whether a transient publication has scheduled payload.
Destination audience is policy external to this schema. The field `audience`
is prohibited at every level, including the top-level document and embedded
content entry.
Runtime ownership belongs in [Architecture](ARCHITECTURE.md); serialization,
validation, and testing requirements belong in [Engineering](ENGINEERING.md).

## Document fields

Every document contains exactly these top-level fields:

| Field | Type | Prepared scheduled value | Completed publication value |
|---|---|---|---|
| `schema_version` | Integer | `1` | `1` |
| `publication_id` | String or null | `null` | Caller-assigned unique publication-event identifier |
| `publication_type` | String | `"scheduled"` | `"scheduled"` or `"transient"` |
| `published_at` | String or null | `null` | UTC RFC-3339 timestamp ending in `Z` |
| `destination_id` | String or null | `null` | Configured destination identifier |
| `output_specification` | Mapping | Actual prepared output | Actual output of the published image |
| `presentation` | Mapping or null | Committed selection and prepared reveal stage | Scheduled context, or `null` for transient |
| `reconstruction` | Mapping or null | Resolved data used for preparation | Resolved data, or `null` for transient |
| `actions` | Ordered sequence | All committed action declarations | Audience-filtered scheduled actions, or empty for transient |

`publication_id` identifies one publication event. It is assigned by the
publication caller and is not generated during preparation. The same value is
passed to any image, metadata, or future manifest creation for that event.
Publication identity is distinct from the committed quotation identity,
selection revision, and reveal stage.

`published_at` identifies the publication event, not selection time or logical
display date. Finalization accepts a timezone-aware timestamp and serializes
it in UTC with a `Z` suffix. Naive timestamps and ambiguous local-time strings
are invalid. JSON is UTF-8; literary Unicode is emitted without ASCII escaping.

`output_specification` contains exactly:

| Field | Type | Required value |
|---|---|---|
| `aspect_ratio` | String | Supported aspect identifier: `"4:3"`, `"5:3"`, `"16:9"`, or `"16:10"` |
| `requested_output_size` | Sequence of two integers | Actual requested width and height; both positive |

The specification is the resolved output associated with the image, not a
reconstruction target or a calculated raster-layout description.

## Scheduled presentation

For a scheduled document, `presentation` contains exactly:

| Field | Type | Required value |
|---|---|---|
| `display_date` | String | Logical display date in `YYYY-MM-DD` form |
| `quotation_identity` | String | Normalized identity of the committed quotation |
| `selection_revision` | Integer | Positive committed selection revision |
| `reveal_stage_index` | Integer | Nonnegative index of the actual published image stage |
| `reveal_schedule` | Mapping | Effective local `HH:MM` times for `quotation`, `source`, and `attribution` |
| `reveal_stage` | Mapping | Boolean visibility flags for `quotation`, `source`, and `attribution` |

The reveal schedule records the effective scheduling times, including the
quotation's display-day start time. The stage flags describe what the image
actually shows. The committed quotation identity and revision remain unchanged
across publication events and reveal stages.

## Scheduled reconstruction

For a scheduled document, `reconstruction` contains exactly:

| Field | Type | Required value |
|---|---|---|
| `content_entry` | Mapping | Valid single-quotation entry in the [content-entry format](CONTENT_FORMAT.md#content-entries) |
| `presentation_style` | String | `"centered"` or `"left-aligned"`; matches the generated entry |
| `background` | String | Actual stable background identifier or `"none"` |
| `decoration` | String | Actual stable decoration identifier or `"none"` |
| `fonts` | Mapping | `bundle` identifier and `faces` mapping |
| `colors` | Mapping | `text` palette identifier and `decoration` palette identifier or null |
| `qr` | Mapping | Boolean `enabled` and `available` values |
| `font_size_range` | Mapping | Positive integer `minimum` and `maximum`, with minimum not above maximum |
| `insets` | Mapping | Nonnegative integer `left`, `right`, `top`, and `bottom` |

`fonts.faces` contains exactly the `quotation`, `source`, and `attribution`
roles, each mapped to the actual resolved face identifier. `colors` contains
palette identifiers, not resolved RGB values.

`content_entry` contains exactly one quotation: the complete committed
quotation text, available source and attribution, presentation style, effective
source and attribution reveal times, and any other committed literary
properties represented by the authoritative content-entry format. It must not
include unrelated quotations or an `actions` field. Action declarations are
carried only by the top-level `actions` sequence so destination filtering cannot
leak private-only actions through reconstruction data. The entry is
self-contained and does not depend on the original content library.

Resolved resource and palette identifiers are stable names; do not serialize
asset bytes, absolute resource paths, raw RGB values, font files, executable
payloads, output-specific geometry, crop coordinates, rendered text positions,
or other transient raster-layout calculations. Reconstruction input is not a
serialized rendering plan.

## Actions and destination audience

An action contains exactly `type`, `visibility`, and `payload`, using the
content-entry action field types and constraints. The sequence preserves the
original order and duplicates.

The configured destination supplies exactly one audience: `public` or
`private`. The finalizer receives this value separately from the metadata
document. Visibility is nonhierarchical: include an action only when its
`visibility` explicitly
contains the destination's audience. An action declaring both is included for
either audience. Do not deduplicate, reorder, merge, reinterpret, or execute
actions. Preserve each included action's complete original declaration,
including its original `visibility` sequence. Never add an `audience` field to
prepared or completed metadata or to embedded reconstruction content.

Context-independent structural validation may be used when the expected
audience is unavailable, but it does not establish that actions are safe for a
particular destination. Completed scheduled-publication serialization requires
an explicit `public` or `private` audience and rejects every action not
permitted for that audience. A future viewer must validate the completed
scheduled stage, not accept preparation-stage metadata or attempt to finalize
it.

Audience filtering is a metadata rule, not a filesystem permission or
authentication mechanism.

## Transient publications

All transient image sources use the same representation, including finished
images submitted through `--image`, viewer-generated previews, and
application-generated information views. A completed transient document has
the normal envelope and output specification, plus exactly:

```json
{
  "publication_type": "transient",
  "presentation": null,
  "reconstruction": null,
  "actions": []
}
```

Transient metadata has no committed selection identity, display date, reveal
stage, literary content, reconstruction data, resolved artistic-resource
choices, or actions. Finalizing a transient does not inspect scheduled
preparation or current selection state. Information-view classification does
not alter its existing scheduling, coordinator priority, duration, or
acknowledgement behavior.

## Validation and JSON behavior

Preparation validation requires every schema field and all preparation-owned
values. Only `publication_id`, `published_at`, and `destination_id` may be
null, and `publication_type` must be `"scheduled"`. Prepared metadata is not
valid as a completed publication.

Completed validation requires a nonblank publication ID and destination ID, a
valid UTC RFC-3339 timestamp, and the actual output specification. Scheduled
documents require valid presentation and reconstruction data, exactly one
quotation, and audience-filtered actions. Transient documents require null
presentation and reconstruction plus an empty action sequence. Unsupported
versions, missing or extra fields, invalid types, inappropriate nulls,
malformed output specifications, invalid generated entries, duplicate JSON
object keys, and nonstandard JSON numeric values are rejected. In particular,
any `audience` key is an unexpected field and is rejected. Validation does not
repair data or fill values from runtime state.

Serialization is deterministic JSON using UTF-8 text, sorted object keys,
compact separators, and preserved sequence order. Parsing validates the same
schema and stage as serialization. Completed scheduled serialization cannot
omit the audience check. The `refrain-viewer --publication` workflow requires
completed scheduled-document validation and rejects null publication identity,
missing completion fields, unsupported versions, and transient documents.
Viewer validation is context-independent and does not require the audience.
No Python-specific persistence format or runtime/content-library dependency is
used.

Schema version `1` is shared by preparation and completed publication; there
is no second completed-publication schema. A future incompatible format change
requires an explicitly versioned schema rather than silently changing the
meaning of existing fields.

The metadata contract defines no filesystem publisher or publication manifest;
viewer reconstruction consumes the same schema without introducing another
metadata format.
