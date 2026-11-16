# Publication metadata format

This specification defines the single JSON metadata schema used for prepared
scheduled images and completed publications. Preparation and publication use
schema version `1`; they differ only in which publication-event fields have
been populated. This document defines data shape and stage completeness.
Runtime behavior belongs to [Architecture](ARCHITECTURE.md), and cache storage
requirements belong to [Engineering](ENGINEERING.md).

Every document contains exactly these top-level fields:

| Field | Type | Prepared scheduled value | Completed publication value |
|---|---|---|---|
| `schema_version` | Integer | `1` | `1` |
| `publication_id` | String or null | `null` | Assigned publication identifier |
| `publication_type` | String | `"scheduled"` | `"scheduled"` or `"transient"` |
| `published_at` | ISO-8601 timestamp or null | `null` | Publication timestamp |
| `destination_id` | String or null | `null` | Selected destination identifier |
| `output_specification` | Mapping | Actual prepared output | Actual published output |
| `presentation` | Mapping or null | Committed selection and prepared reveal stage | Scheduled context, or `null` for transient |
| `reconstruction` | Mapping or null | Resolved data used for preparation | Resolved data, or `null` for transient |
| `actions` | Ordered sequence | All committed action declarations, including visibility | Audience-filtered scheduled actions, or empty for transient |

`output_specification` contains exactly `aspect_ratio` (a supported aspect
identifier) and `requested_output_size` (two positive integer dimensions).
`presentation` contains exactly `display_date` (ISO date),
`selection_revision` (positive integer), `reveal_stage_index` (zero-based
nonnegative integer), and `reveal_stage` (the `quotation`, `source`, and
`attribution` boolean visibility flags).

`reconstruction` contains exactly:

- `content_entry`: a valid single-quotation content entry derived from the
  committed selection. It includes the committed literary text and available
  content-level metadata. Actions are carried by the top-level `actions`
  sequence so a later publication can apply audience filtering without
  altering or leaking the embedded entry.
- `presentation_style`: `"centered"` or `"left-aligned"`.
- `background` and `decoration`: stable identifiers for the resources actually
  used; `"none"` identifies the absence of that resource.
- `fonts`: `bundle` (the resolved font-bundle identifier) and `faces` (exactly
  the role keys `quotation`, `source`, and `attribution`, each with the actual
  face identifier, including a resolved regular-face fallback).
- `colors`: `text` (the resolved palette identifier) and `decoration` (the
  resolved palette identifier or null when no decoration tint was used).
- `qr`: `enabled` (the effective QR setting) and `available` (whether QR was
  actually rendered for this output).
- `font_size_range`: positive integer `minimum` and `maximum` design sizes.
- `insets`: nonnegative integer `left`, `right`, `top`, and `bottom` effective
  presentation insets.

Each action contains exactly `type`, `visibility`, and `payload`, preserving
the content-entry action declaration. Preparation stores the complete ordered
sequence and must not filter it before a destination is chosen. Completed
publication stores only actions allowed for the selected audience, in their
original order.

## Validation stages

Preparation validation requires every field above and valid preparation-owned
values. It permits null only for `publication_id`, `published_at`, and
`destination_id`, because no publication event or destination selection has
occurred. It rejects missing fields, unsupported versions, malformed
reconstruction data, and output, selection, or reveal associations that do not
match the prepared image.

Completed-publication validation uses the same fields and definitions. It
requires a nonempty publication and destination identifier and a valid
timezone-qualified publication timestamp in addition to all
publication-stage-owned values. A completed scheduled document has populated
presentation and reconstruction mappings. A completed transient document has
`presentation: null`, `reconstruction: null`, and an empty `actions` sequence.
The filesystem publication workflow is not part of the preparation-stage
implementation.

The schema records stable resource and palette identifiers, not resource bytes,
filesystem paths, RGB values, or output-dependent layout calculations.
Publication identity, destination identity, and timestamp are never fabricated
to make a prepared document appear complete.
