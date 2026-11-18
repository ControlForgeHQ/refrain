# Publication

This document specifies Refrain's two public publication JSON formats:

- **Publication metadata** describes a prepared scheduled image or one completed scheduled or transient publication, including its output specification and applicable literary reconstruction data.
- **Publication manifest** identifies the current complete filesystem dataset for one destination, naming its image and completed metadata files and recording their byte hashes.

Each format has its own `schema_version` field. Both require the integer `1`; sharing that value does not make their schemas interchangeable.

## JSON documents

Both formats use UTF-8 JSON with one top-level object. Reject invalid UTF-8, invalid JSON, duplicate object keys at any level, nonstandard numeric values, unsupported schema versions, missing or unexpected fields, incorrect types, and invalid nulls. Booleans do not satisfy integer fields. Validation does not repair data or obtain missing values from runtime state.

Metadata forbids an `audience` field at every level, including embedded content. Destination audience is supplied separately as policy.

## Metadata fields

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
used for the image, metadata, and manifest belonging to that event.
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

The reveal schedule contains exactly `quotation`, `source`, and `attribution`, each a local 24-hour `HH:MM` string. The stage mapping contains exactly those same three keys with Boolean values. The reveal schedule records the effective scheduling times, including the
quotation's display-day start time. The stage flags describe what the image
actually shows. The committed quotation identity and revision remain unchanged
across publication events and reveal stages.

## Canonical and prepared destination presentation

For a scheduled document, `reconstruction` contains exactly:

| Field | Type | Required value |
|---|---|---|
| `content_entry` | Mapping | Valid single-quotation entry in the [content-entry format](CONTENT.md) |
| `canonical_presentation` | Mapping | Resolved destination-independent artistic presentation |
| `effective_presentation` | Mapping | Actual effective presentation used to prepare this destination's output |

`canonical_presentation` contains exactly:

| Field | Type | Required value |
|---|---|---|
| `presentation_style` | String | `"centered"` or `"left-aligned"`; matches the generated entry |
| `background` | String | Resolved stable background identifier or `"none"` |
| `decoration` | String | Resolved stable decoration identifier or `"none"` |
| `fonts` | Mapping | `bundle` identifier and `faces` mapping |
| `colors` | Mapping | `text` palette identifier and `decoration` palette identifier or null |
| `qr` | Mapping | Exactly `enabled`, the canonical literary QR policy as a Boolean |

`effective_presentation` contains the same artistic-choice fields plus the
following output-preparation fields. Its values describe the resolved result
after applying the destination's supported overrides, not the override
requests:

- `presentation_style`, `background`, `decoration`, `fonts`, and `colors`
  record the actual effective choices. Suppressed background or decoration is
  recorded as `"none"`.
- `qr` contains exactly Boolean `enabled` and `available` fields. `enabled`
  records whether QR policy permits rendering after destination suppression;
  `available` records whether a QR was actually included after decoration
  restrictions, placement validation, and output-geometry checks.
- `font_size_range` and `insets` record the actual effective geometry values
  used for this output in design-canvas units. When decoration is suppressed,
  they record the global insets and minimum/maximum font sizes.

The effective mapping contains exactly `presentation_style`, `background`,
`decoration`, `fonts`, `colors`, `qr`, `font_size_range`, and `insets`.

`font_size_range` contains exactly:

| Field | Type | Required value |
|---|---|---|
| `minimum` | Integer | Positive design-canvas pixel size |
| `maximum` | Integer | Positive design-canvas pixel size, not less than `minimum` |

`insets` contains exactly:

| Field | Type | Required value |
|---|---|---|
| `left` | Integer | Nonnegative design-canvas pixels |
| `right` | Integer | Nonnegative design-canvas pixels |
| `top` | Integer | Nonnegative design-canvas pixels |
| `bottom` | Integer | Nonnegative design-canvas pixels |

Booleans are not integers for these fields. These are the effective
design-canvas configuration values, not mapped presentation-canvas rectangles,
fitted raster font sizes, or text positions. The output specification remains
the requested raster identity.

Resolved resource, bundle, face, and palette identifiers are case-sensitive ASCII strings matching `[A-Za-z0-9][A-Za-z0-9_-]*`. The background and decoration fields additionally use the reserved string `"none"` for suppression or no artwork. A null decoration color records the absence of a resolved tint color.

`fonts` contains exactly `bundle` and `faces`. `colors` contains exactly `text` and `decoration`.

`fonts.faces` contains exactly the `quotation`, `source`, and `attribution`
roles, each mapped to the actual resolved face identifier. `colors` contains
palette identifiers, not resolved RGB values. Stable identifiers and resolved
values are recorded rather than raw override requests, pools, fallback lists,
asset bytes, absolute resource paths, or raw RGB values.

The prepared document's `output_specification` and `effective_presentation`
identify the prepared rendering requirements. `destination_id` remains null
until publication finalization so compatible destinations can share prepared
images and metadata. Completed metadata records the actual destination ID in
the publication envelope. Do not infer the effective presentation from
finished pixels or re-resolve it while finalizing metadata.

The canonical presentation is persisted with the committed daily selection,
independently of destination-specific prepared images. All destinations derive
their effective presentation from that same canonical record. `canonical_presentation`
must therefore remain unchanged when destination overrides differ.

`content_entry` contains exactly one quotation: the complete committed
quotation text, available source and attribution, presentation style, effective
source and attribution reveal times, and any other committed literary
properties represented by the authoritative content-entry format. Its required fields are `id`, `quotations`, `presentation_style`, and `reveal`. The `reveal` mapping contains exactly `source` and `attribution`, matching the corresponding effective times in `presentation.reveal_schedule`; the quotation's start time belongs only to that presentation schedule. Optional literary fields use [Content Entries](CONTENT.md#entry-fields), with no new publication-only entry fields. The normalized sole quotation matches `presentation.quotation_identity`. It must not
include unrelated quotations or an `actions` field. Action declarations are
carried only by the top-level `actions` sequence so destination filtering cannot
leak private-only actions through reconstruction data. The entry is
self-contained and does not depend on the original content library.

Resolved resource and palette identifiers are stable names; do not serialize
asset bytes, absolute resource paths, raw RGB values, font files, executable
payloads, output-specific raster geometry, crop coordinates, rendered text
positions, or other transient raster-layout calculations. The required
effective design-canvas insets and font-size bounds above are configuration
values, not output-specific raster geometry. Reconstruction input is not a
serialized rendering plan.

## Actions and destination audience

Each action contains exactly these fields; unlike an authored content declaration, its `payload` is always present:

| Field | Type | Constraint |
|---|---|---|
| `type` | String | Case-sensitive ASCII identifier matching `[A-Za-z0-9][A-Za-z0-9_-]*`. |
| `visibility` | Nonempty sequence of strings | `"public"`, `"private"`, or both, without repetition. |
| `payload` | String | Opaque text, at most 10,240 UTF-8 bytes; an omitted authored payload is captured as `""`. |

There are at most 100 actions. Preserve their order, duplicates, payload whitespace, and newlines. Invalid publication actions are rejected; the authored-content warning-and-discard recovery rules do not repair publication metadata. The declaration format is defined in [Content Entries](CONTENT.md#actions).

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
permitted for that audience. The publication viewer validates the completed
scheduled stage; it does not accept preparation-stage metadata or finalize it.

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
stage, literary content, canonical or effective presentation data, resolved
artistic-resource choices, or actions. Finalizing a transient does not inspect scheduled
preparation or current selection state. Information-view classification does
not alter its existing scheduling, coordinator priority, duration, or
acknowledgement behavior.

## Metadata validation and serialization

Preparation validation requires every schema field and all preparation-owned
values. The publication-envelope fields `publication_id`, `published_at`, and
`destination_id` must be null, and `publication_type` must be `"scheduled"`.
Scheduled presentation and reconstruction mappings are required. Nested null
values are permitted only where explicitly specified, such as
`colors.decoration`. Prepared metadata is not valid as a completed publication.

Completed validation requires a nonblank publication ID and a destination ID using the identifier syntax in [Application Configuration](CONFIGURATION.md#destinations), a
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

## Persistence and reconstruction

Canonical selection persistence, attachment before destination preparation, cache compatibility, and regeneration are defined in [Architecture](../ARCHITECTURE.md#daily-selection-record) and [prepared images](../ARCHITECTURE.md#prepared-images). The canonical record remains authoritative selection data; effective presentation metadata is derived data associated with its exact prepared image collection.

A complete compatible collection includes valid images and their associated preparation-stage metadata. Reuse retains the recorded effective choices. Missing, damaged, inconsistent, or incompatible required metadata makes the collection unusable for reconstruction-capable publication; images and metadata are regenerated together from the committed selection and persisted canonical presentation. This preserves quotation identity, selection history, canonical choices, and reveal progression. Detailed recovery belongs to [Architecture](../ARCHITECTURE.md#destination-specific-metadata-and-audiences).

Completed scheduled metadata provides a self-contained literary input, not an archival copy of assets or a serialized rendering plan. Publication reconstruction uses the recorded effective presentation as its baseline, with canonical presentation retained separately as provenance. It uses currently installed resources and palette definitions, recalculates geometry for the requested output, and reevaluates QR availability. It does not promise identical pixels after assets or rendering behavior change. The original reveal flags describe the published image; the viewer renders fully revealed by default. Command options and strict unavailable-resource diagnostics are defined in [CLI](../CLI.md#publication-reconstruction).

## Manifest fields

Each destination directory has one stable `manifest.json`. It contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `schema_version` | Integer | Exactly `1`. |
| `publication_id` | String | Publication-event identifier satisfying the filename constraints below. |
| `image_filename` | String | Exactly `<publication_id>.png`. |
| `metadata_filename` | String | Exactly `<publication_id>.json`. |
| `image_sha256` | String | Lowercase 64-character hexadecimal SHA-256 digest of the image file bytes. |
| `metadata_sha256` | String | Lowercase 64-character hexadecimal SHA-256 digest of the metadata file bytes. |

The manifest contains no destination audience, reconstruction fields, history index, or alternate paths. Its schema is independent of metadata validation; a valid manifest alone does not establish a valid dataset. Unsupported schema versions are rejected rather than interpreted as the supported schema.

### Identity and filenames

For filesystem publication, `publication_id` matches `[A-Za-z0-9][A-Za-z0-9_-]{0,239}` and must not be a Windows-reserved device name: `CON`, `PRN`, `AUX`, `NUL`, `COM1` through `COM9`, or `LPT1` through `LPT9`, without regard to case. This 240-character maximum applies to the filesystem dataset identity; metadata's standalone publication-ID requirement is a nonblank string.

Both referenced filenames are relative single-component names in the same destination directory, derived exactly from that identity. Arbitrary paths, separators, dots in the ID, traversal components, drive-qualified paths, and absolute paths are invalid. The stable manifest filename is always `manifest.json`.

The destination directory is a direct child of the effective `storage.publish` root and is named from the validated destination ID. That ID uses `[A-Za-z0-9][A-Za-z0-9_-]*`, at most 256 characters. Configured `publish` IDs also exclude the Windows-reserved device names above and are unique under case-insensitive comparison. Destination and storage configuration are defined in [Application Configuration](CONFIGURATION.md#destinations) and [Storage](CONFIGURATION.md#storage).

### Dataset validation

A reader accepts a dataset only after it has:

1. Read and validated the current stable manifest.
2. Safely opened both referenced regular files in that same destination directory, without following filesystem redirection.
3. Verified both SHA-256 hashes against the exact stored bytes.
4. Validated completed publication metadata.
5. Verified that the metadata's `publication_id` equals the manifest identity and its `destination_id` equals the owning directory's destination ID.
6. Verified a complete single-frame PNG whose dimensions equal `output_specification.requested_output_size`.

Both scheduled and transient completed metadata may belong to a dataset. Prepared metadata cannot. Hash validation is byte-based: rewriting equivalent JSON changes its digest.

### Commit and recovery

The stable manifest replacement is the consumer-visible commit point. A temporary manifest is never authoritative. Before replacement, the prior valid dataset remains current; after replacement, the newly referenced complete dataset is current.

Readers recover from the current manifest and its referenced files, without an original content library, resident process, process-local publication history, or reconstruction of filenames from directory enumeration. Incomplete or unavailable reads use bounded retries. A malformed manifest, missing file, hash mismatch, unsafe object, or uncertain ownership is reported rather than repaired or accepted as valid. Consumers do not rewrite or clean publication storage.

Publication order, superseded-file cleanup, retention after a post-commit failure, storage ownership, and filesystem safety are defined in [Architecture](../ARCHITECTURE.md#dataset-publication-and-recovery) and [Engineering](../ENGINEERING.md#filesystem-publication-storage).

## Complete examples

The following scheduled document describes one completed publication. Its canonical background remains `paper`; the destination's effective background is suppressed. The resource identifiers illustrate recorded choices, not a requirement that those resources be installed on every system.

```json
{
  "schema_version": 1,
  "publication_id": "publication-example",
  "publication_type": "scheduled",
  "published_at": "2026-11-17T18:00:00Z",
  "destination_id": "web-public",
  "output_specification": {
    "aspect_ratio": "16:10",
    "requested_output_size": [
      3840,
      2400
    ]
  },
  "presentation": {
    "display_date": "2026-11-17",
    "quotation_identity": "A thought worth keeping.",
    "selection_revision": 1,
    "reveal_stage_index": 2,
    "reveal_schedule": {
      "quotation": "05:00",
      "source": "12:00",
      "attribution": "18:00"
    },
    "reveal_stage": {
      "quotation": true,
      "source": true,
      "attribution": true
    }
  },
  "reconstruction": {
    "content_entry": {
      "id": "example",
      "quotations": [
        "A thought worth keeping."
      ],
      "source": "An Example Book",
      "attribution": "Example Author",
      "presentation_style": "centered",
      "reveal": {
        "source": "12:00",
        "attribution": "18:00"
      }
    },
    "canonical_presentation": {
      "presentation_style": "centered",
      "background": "paper",
      "decoration": "none",
      "fonts": {
        "bundle": "lora",
        "faces": {
          "quotation": "regular",
          "source": "regular",
          "attribution": "regular"
        }
      },
      "colors": {
        "text": "black",
        "decoration": null
      },
      "qr": {
        "enabled": true
      }
    },
    "effective_presentation": {
      "presentation_style": "centered",
      "background": "none",
      "decoration": "none",
      "fonts": {
        "bundle": "lora",
        "faces": {
          "quotation": "regular",
          "source": "regular",
          "attribution": "regular"
        }
      },
      "colors": {
        "text": "black",
        "decoration": null
      },
      "qr": {
        "enabled": true,
        "available": false
      },
      "font_size_range": {
        "minimum": 56,
        "maximum": 200
      },
      "insets": {
        "left": 384,
        "right": 384,
        "top": 324,
        "bottom": 324
      }
    }
  },
  "actions": [
    {
      "type": "custom_action",
      "visibility": [
        "public",
        "private"
      ],
      "payload": "Opaque consumer text."
    }
  ]
}
```

The corresponding preparation-stage form has the same scheduled payload and actual output specification, with `publication_id`, `published_at`, and `destination_id` set to null. Its actions contain all committed declarations before destination filtering.

This complete transient document has no scheduled context:

```json
{
  "schema_version": 1,
  "publication_id": "transient-example",
  "publication_type": "transient",
  "published_at": "2026-11-17T18:01:00Z",
  "destination_id": "web-public",
  "output_specification": {
    "aspect_ratio": "16:10",
    "requested_output_size": [
      3840,
      2400
    ]
  },
  "presentation": null,
  "reconstruction": null,
  "actions": []
}
```

A filesystem dataset has this shape:

```text
<publish-root>/
└── web-public/
    ├── manifest.json
    ├── transient-example.png
    └── transient-example.json
```

This complete manifest belongs to the transient example above, stored as a 3840 × 2400 RGB paper-white PNG and deterministic compact metadata JSON. Digests cover the exact stored bytes; changing JSON whitespace or PNG encoding requires new digests:

```json
{
  "schema_version": 1,
  "publication_id": "transient-example",
  "image_filename": "transient-example.png",
  "metadata_filename": "transient-example.json",
  "image_sha256": "9ce8c2955002edaa2411d1f3a2ac989e6b37610b99f32402efbe6bcf29c5e6a1",
  "metadata_sha256": "38c646e3467646d2bb922e24824ecf12da5ea261b771ee5825c5a964563e6964"
}
```

