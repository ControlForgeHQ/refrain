# Publication

This document defines publication metadata and filesystem publication manifests as UTF-8 JSON data.

## JSON values

Each document is one JSON object. Reject invalid UTF-8, invalid JSON, duplicate object keys at any depth, nonstandard numeric values, unsupported schema versions, missing required fields, unexpected fields, incorrect types, and invalid nulls. Strings must contain valid Unicode representable in UTF-8. Booleans are not integers.

Each object contains exactly its specified fields, except fields explicitly marked optional. Omission represents an absent optional value. Unresolved sections and fields are omitted; null is valid only for `presentation.colors.decoration`, where it means no resolved tint color.

Metadata has no `audience` field at any level. Object values cannot contain resource bytes, absolute resource paths, raw RGB values, executable objects, or raster-layout data. Action payloads are opaque strings and are not interpreted as structured objects.

## Metadata document shapes

One dataset has progressively populated sections. The validation stage determines the exact required and omitted root fields:

| Form | Required root fields | Omitted root fields |
|---|---|---|
| Content checkpoint | `schema_version`, `content` | `presentation`, `publication` |
| Content and presentation checkpoint | `schema_version`, `content`, `presentation` | `publication` |
| Completed scheduled publication | `schema_version`, `content`, `presentation`, `publication` | None |
| Completed transient publication | `schema_version`, `publication` | `content`, `presentation` |

`schema_version` is the integer `1` in every form. A present section is complete for its form; a partial `presentation` or `publication` object is invalid. No root stage discriminator is defined. Checkpoints are not completed publications.

A completed scheduled document has `publication.type: "scheduled"`; a completed transient document has `publication.type: "transient"`. A transient document contains no literary content, presentation choices, or actions, including null or empty placeholders for those sections.

## Content

`content` contains exactly the following required fields and any present optional fields:

| Field | Type | Required | Constraint |
|---|---|---|---|
| `display_date` | String | Yes | Valid Gregorian calendar date in `YYYY-MM-DD` form. |
| `selection_revision` | Integer | Yes | Positive committed selection revision. |
| `reveal_schedule` | Object | Yes | Exactly `quotation`, `source`, `attribution`, each a local 24-hour `HH:MM` string (`00:00`–`23:59`); `source` and `attribution` must each be no earlier than `quotation`. |
| `reveal_stage` | Object | Yes | Exactly `quotation`, `source`, `attribution`, each Boolean. |
| `quotation` | String | Yes | One complete selected quotation containing at least one non-whitespace character. |
| `source` | String | No | Complete source text, nonblank when present; omit when absent. |
| `attribution` | String | No | Complete attribution text, nonblank when present; omit when absent. |
| `actions` | Array of action objects | Yes | Ordered sequence of zero to 100 declarations in checkpoints; zero to 16 audience-filtered declarations in completed scheduled publications. |
| `qr` | Array of QR declaration objects | Yes | Zero to two declarations in checkpoints; zero or one in completed scheduled publications. |

Quotation, source, and attribution strings preserve their original text, including Unicode, whitespace, and meaningful line breaks, under the literary string definitions in [Content Entries](CONTENT.md#quotations-source-and-attribution). Complete text remains present independently of visibility flags. No entry wrapper, entry identifier, quotation list, quotation identity, priority, eligibility, authored preference, duplicated schedule, or reveal-stage ordinal is part of this object.

The reveal schedule includes the quotation's display-day start and the effective source and attribution times. The flags express visibility: in checkpoints, the recorded current visibility; in completed scheduled metadata, visibility of that publication's image. They are not publication acknowledgements or an implicit stage index. The time format alone does not establish the flags' values. Scheduling semantics are defined in [Reveal progress and missed events](../specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#reveal-progress-and-missed-events).

`reveal_stage.quotation` must be `true`. When `source` or `attribution` is absent, its corresponding reveal-stage flag must be `false`. Otherwise, visibility flags are independent of the schedule's time strings; validation does not recalculate reveal-stage progression.

### Actions

Each action contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `type` | String | Case-sensitive ASCII identifier matching `[A-Za-z0-9][A-Za-z0-9_-]*`. |
| `visibility` | Nonempty array of strings | `"external"`, `"internal"`, or both, without repetition. |
| `payload` | String | Required opaque text, at most 10,240 UTF-8 bytes. An absent authored payload is represented by `""`. |

Array order, duplicate declarations, payload whitespace and newlines, and each included declaration's complete original visibility array are significant. Invalid declarations are invalid metadata; content-authoring recovery rules do not repair them. The authored declaration shape is defined in [Content Entries](CONTENT.md#actions).

Checkpoint `content.actions` contains all captured actions. Completed scheduled `content.actions` contains only declarations whose visibility explicitly includes the destination's independently supplied `external` or `internal` audience. Visibility is nonhierarchical: `external` does not imply `internal`, or conversely. An action declaring both is eligible for either. An empty filtered sequence is valid.

Completed scheduled validation with a supplied audience rejects every action that lacks that audience. Completed scheduled serialization requires that audience check. Context-independent validation without an audience establishes structural validity only, not suitability for a destination. Audience is never inferred from `destination_id` or serialized into the document.

Completed scheduled publication actions are subject to a maximum of 4,096 UTF-8 bytes per deterministically serialized action object. Apply the completed-publication action count and byte limits after audience filtering. Reject an oversized publication rather than silently truncating, omitting, or modifying otherwise eligible actions.

### QR payloads

`content.qr` is required in both checkpoint forms and completed scheduled publications.

Each declaration contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `payload` | String | Nonempty opaque UTF-8 string of at most 62 bytes. |
| `visibility` | Array of one string | Exactly `["external"]` or `["internal"]`. |

Payloads preserve their original Unicode content, whitespace, and newlines. Null payloads, duplicate audience declarations, and additional declaration fields are invalid.

Both checkpoint forms contain zero to two resolved declarations, with at most one declaration per audience. Different audiences retain separate declarations even when their payloads are identical.

Completed scheduled publications contain zero or one declaration. A present declaration identifies the QR payload rendered in the associated image and retains its original visibility. An empty array means no literary QR was rendered.

Completed scheduled serialization requires the declaration's visibility to match the destination audience. When an audience is supplied for validation, a mismatched declaration is invalid. Context-independent validation establishes structural validity only.

Completed transient publications omit the entire `content` section.

## Presentation

`presentation` contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `style` | String | `"centered"` or `"left-aligned"`. |
| `background` | String | Resolved stable background identifier or `"none"`. |
| `decoration` | String | Resolved stable decoration identifier or `"none"`. |
| `fonts` | Object | Exactly `bundle` and `faces`, as below. |
| `colors` | Object | Exactly `text` and `decoration`, as below. |
| `font_size_range` | Object | Exactly positive integer `minimum` and `maximum`; `maximum >= minimum`. |
| `insets` | Object | Exactly nonnegative integer `left`, `right`, `top`, `bottom`. |

Resource, bundle, face, and palette identifiers are case-sensitive ASCII strings matching `[A-Za-z0-9][A-Za-z0-9_-]*`. Background and decoration additionally use the reserved value `"none"` for absence or suppression. Values are resolved identifiers, not authored pools, preference lists, override requests, filenames, asset bytes, or raw RGB values. Resource shapes are defined in [Assets](ASSETS.md).

`fonts.bundle` is a resolved bundle identifier. `fonts.faces` contains exactly the `quotation`, `source`, and `attribution` roles, each mapped to its resolved face identifier, even when a literary field is absent or hidden.

`colors.text` is a resolved palette identifier. `colors.decoration` is a resolved palette identifier or null; null denotes absence of a resolved tint color.

Font-size bounds and insets are effective configuration values in design-canvas pixels. They are not fitted raster font sizes, mapped rectangles, rendered positions, crop coordinates, or other raster-layout calculations. The presentation records one set of resolved choices; no canonical/effective duplicate objects exist.

## Publication

`publication` is present only in completed metadata and contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `id` | String | Nonblank publication-event identifier. Filesystem datasets additionally satisfy the manifest identity constraints below. |
| `type` | String | `"scheduled"` or `"transient"`. |
| `timestamp` | String | Valid UTC RFC-3339 timestamp ending in `Z`. |
| `destination_id` | String | Configured destination identifier as defined in [Application Configuration](CONFIGURATION.md#destinations). |
| `output_specification` | Object | Exactly `aspect_ratio` and `requested_output_size`, as below. |

`id` identifies one publication event, independently of selection revision and visibility. `timestamp` denotes the event timestamp, not the logical display date. Naive timestamps and local-time strings without an offset are invalid; the JSON value is UTC with `Z`.

`output_specification.aspect_ratio` is one of `"4:3"`, `"5:3"`, `"16:9"`, or `"16:10"`. `requested_output_size` is an array of exactly two integers, width then height. Width must be 1–3840 and height must be 1–2400. These dimensions are independent of the declared aspect ratio; portrait and square outputs are valid. This object contains no calculated layout dimensions.

Destination and output configuration are defined in [Application Configuration](CONFIGURATION.md#destinations).

## Metadata validity

Validation checks the selected document form, exact keys, field types, lexical and numeric constraints, and any supplied audience. It does not supply missing values, repair invalid data, look up content or resources, or establish rendering feasibility. Structural validity does not certify resource availability, typography, layout fit, QR placement, or identical reproduced pixels.

Checkpoint forms have no publication event values or output specification. Completed scheduled metadata requires all three sections and destination-appropriate actions and QR declarations. Completed transient metadata requires only the version and publication object. No completed document may substitute a checkpoint or contain unresolved required values.

Every completed scheduled or transient metadata document must be no more than 65,536 bytes in its deterministic serialized UTF-8 JSON representation. Apply this limit to the complete document after scheduled-publication audience filtering. Reject oversized completed metadata without truncation. Checkpoint forms do not have this external-delivery size limit.

Deterministic serialization uses UTF-8 JSON, sorted object keys, compact separators, preserved array order, and unescaped literary Unicode. Parsing applies the same field and stage constraints. The completed scheduled form is the metadata input defined by [CLI publication reconstruction](../CLI.md#publication-reconstruction).

## Manifest fields

Each destination directory has one stable `manifest.json`. It contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `schema_version` | Integer | Exactly `1`. |
| `id` | String | Publication-event identifier satisfying the filename constraints below. |
| `image_filename` | String | Exactly `<id>.png`. |
| `metadata_filename` | String | Exactly `<id>.json`. |
| `image_sha256` | String | Lowercase 64-character hexadecimal SHA-256 digest of the image file bytes. |
| `metadata_sha256` | String | Lowercase 64-character hexadecimal SHA-256 digest of the metadata file bytes. |

The manifest contains no destination audience, reconstruction fields, history index, or alternate paths. Its schema is independent of metadata validation; a valid manifest alone does not establish a valid dataset. Unsupported schema versions are rejected rather than interpreted as the supported schema.

### Identity and filenames

For filesystem publication, `id` matches `[A-Za-z0-9][A-Za-z0-9_-]{0,239}` and must not equal `manifest` or a Windows-reserved device name (`CON`, `PRN`, `AUX`, `NUL`, `COM1` through `COM9`, or `LPT1` through `LPT9`), without regard to case. This 240-character maximum applies to the filesystem dataset identity; metadata's standalone publication-ID requirement is a nonblank string.

Both referenced filenames are relative single-component names in the same destination directory, derived exactly from that identity. Arbitrary paths, separators, dots in the ID, traversal components, drive-qualified paths, and absolute paths are invalid. The stable manifest filename is always `manifest.json`.

The destination directory is a direct child of the effective `storage.publish` root and is named from the validated destination ID. Destination identifier constraints and storage configuration are defined in [Application Configuration](CONFIGURATION.md#destinations) and [Storage](CONFIGURATION.md#storage).

### Dataset consistency

A valid filesystem dataset contains the manifest, both referenced regular files in its destination directory without filesystem redirection, and completed metadata. Both stored file hashes must match the manifest's SHA-256 values.

The completed metadata's `publication.id` equals the manifest's `id`; `publication.destination_id` equals the owning directory's destination ID. The image is a complete single-frame PNG with dimensions equal to `publication.output_specification.requested_output_size`. Scheduled and transient completed documents are both valid dataset metadata; checkpoints are not.

Digests describe exact file bytes, including JSON whitespace and PNG encoding. Equivalent parsed JSON does not imply equal hashes. Filesystem behavior is defined in [Dataset commit and consumer recovery](../specifications/70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#dataset-commit-and-consumer-recovery).

## Complete examples

Example resource identifiers illustrate recorded values; validity does not require those resources to be installed.

### Content checkpoint

All captured actions are present; presentation and publication are absent.

```json
{
  "schema_version": 1,
  "content": {
    "display_date": "2026-11-18",
    "selection_revision": 1,
    "reveal_schedule": {
      "quotation": "05:00",
      "source": "12:00",
      "attribution": "18:00"
    },
    "reveal_stage": {
      "quotation": true,
      "source": false,
      "attribution": false
    },
    "quotation": "A thought worth keeping.",
    "source": "An Example Book",
    "attribution": "Example Author",
    "actions": [
      {
        "type": "custom_action",
        "visibility": [
          "external",
          "internal"
        ],
        "payload": "Opaque consumer text."
      },
      {
        "type": "private_note",
        "visibility": [
          "internal"
        ],
        "payload": "Private consumer text."
      }
    ],
    "qr": [
      {
        "payload": "https://github.com/ControlForgeHQ/refrain",
        "visibility": [
          "external"
        ]
      },
      {
        "payload": "https://example.org/private",
        "visibility": [
          "internal"
        ]
      }
    ]
  }
}
```

### Content and presentation checkpoint

The same content has a complete presentation section. Publication is absent.

```json
{
  "schema_version": 1,
  "content": {
    "display_date": "2026-11-18",
    "selection_revision": 1,
    "reveal_schedule": {
      "quotation": "05:00",
      "source": "12:00",
      "attribution": "18:00"
    },
    "reveal_stage": {
      "quotation": true,
      "source": false,
      "attribution": false
    },
    "quotation": "A thought worth keeping.",
    "source": "An Example Book",
    "attribution": "Example Author",
    "actions": [
      {
        "type": "custom_action",
        "visibility": [
          "external",
          "internal"
        ],
        "payload": "Opaque consumer text."
      },
      {
        "type": "private_note",
        "visibility": [
          "internal"
        ],
        "payload": "Private consumer text."
      }
    ],
    "qr": [
      {
        "payload": "https://github.com/ControlForgeHQ/refrain",
        "visibility": [
          "external"
        ]
      },
      {
        "payload": "https://example.org/private",
        "visibility": [
          "internal"
        ]
      }
    ]
  },
  "presentation": {
    "style": "centered",
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
}
```

### Completed scheduled publication

This external destination record has source visibility enabled and includes only the action visible to its audience. The complete quotation, source, and attribution remain available as data.

```json
{
  "schema_version": 1,
  "content": {
    "display_date": "2026-11-18",
    "selection_revision": 1,
    "reveal_schedule": {
      "quotation": "05:00",
      "source": "12:00",
      "attribution": "18:00"
    },
    "reveal_stage": {
      "quotation": true,
      "source": true,
      "attribution": false
    },
    "quotation": "A thought worth keeping.",
    "source": "An Example Book",
    "attribution": "Example Author",
    "actions": [
      {
        "type": "custom_action",
        "visibility": [
          "external",
          "internal"
        ],
        "payload": "Opaque consumer text."
      }
    ],
    "qr": [
      {
        "payload": "https://github.com/ControlForgeHQ/refrain",
        "visibility": [
          "external"
        ]
      }
    ]
  },
  "presentation": {
    "style": "centered",
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
  },
  "publication": {
    "id": "publication-example",
    "type": "scheduled",
    "timestamp": "2026-11-18T17:00:00Z",
    "destination_id": "web-a",
    "output_specification": {
      "aspect_ratio": "16:10",
      "requested_output_size": [
        3840,
        2400
      ]
    }
  }
}
```

### Completed transient publication

```json
{
  "schema_version": 1,
  "publication": {
    "id": "transient-example",
    "type": "transient",
    "timestamp": "2026-11-18T17:01:00Z",
    "destination_id": "web-a",
    "output_specification": {
      "aspect_ratio": "16:10",
      "requested_output_size": [
        3840,
        2400
      ]
    }
  }
}
```


### Filesystem manifest

This manifest describes the supplied complete transient example dataset. Its hashes cover the exact compact UTF-8 metadata and the 3840 × 2400 RGB white PNG supplied with this example.

```json
{
  "schema_version": 1,
  "id": "transient-example",
  "image_filename": "transient-example.png",
  "metadata_filename": "transient-example.json",
  "image_sha256": "9d8e0815185722c4cf8d7fa49fcf7fd71207f427aef740e589ae8b033a60511a",
  "metadata_sha256": "325ad4b4bea92e705e9cc8a1c694f2c3f6307338b1008856e8a9320bff043275"
}
```


