# Operational State and Global History

This document defines the persistent JSON formats for authoritative operational state (`state.json`) and chronological global history (`global-history.jsonl`).

Selection commitment, recovery, atomic writes, and history retention belong to [Selection and Persistence](../specifications/30-SELECTION_AND_PERSISTENCE.md). Reveal scheduling and stage progression belong to [Scheduling and Application Lifecycle](../specifications/40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md).

## Common JSON requirements

Documents use UTF-8 without a byte-order mark. Reject invalid JSON, invalid UTF-8, duplicate object keys at any depth, nonstandard numeric values, incorrect types, invalid nulls, missing required fields, and unsupported fields.

Booleans are not integers. JSON strings must contain valid Unicode representable in UTF-8.

All documented object fields are required unless explicitly stated otherwise. Fields representing absent optional literary content use JSON null where specified.

## Authoritative operational state

The file `state.json` contains one JSON object with exactly these fields:

| Field | Type | Constraint |
|---|---|---|
| `format_version` | Integer | Exactly `1`. |
| `state` | Object | Complete operational-state payload defined below. |
| `sha256` | String | Lowercase hexadecimal SHA-256 digest of the canonical serialized `state` payload. |

Unsupported format versions, missing or invalid fields, and checksum failures invalidate operational-state recovery.

### Canonical serialization and integrity

Canonical JSON serialization uses UTF-8, lexicographically sorted object keys, no insignificant whitespace, and literal Unicode characters rather than ASCII escape substitutions. Non-finite numeric values are prohibited.

The checksum is calculated over the canonical serialized bytes of the `state` object only, not the enclosing document.

The writer emits the complete enclosing document in canonical JSON form followed by one newline.

The checksum detects incomplete or inconsistent state bytes. It is not an authentication mechanism.

### State payload

The `state` object contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `revision` | Integer | Positive; initial selection revision is `1`. |
| `snapshot` | Object | Complete committed selection snapshot. |
| `repetition_history` | Array of strings | Unique normalized quotation identities, sorted in ascending Unicode code-point order. |
| `highest_reveal_stage` | Integer | From `0` through `snapshot.resolved_reveal_stages.length - 1`, inclusive. |

The current snapshot's `quotation_identity` must appear in `repetition_history`.

The revision is the committed selection revision, not a reveal-update counter. Its assignment and update rules belong to [Selection revisions and atomic writes](../specifications/30-SELECTION_AND_PERSISTENCE.md#selection-revisions-and-atomic-writes).

### Committed selection snapshot

The `snapshot` object contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `entry_id` | String | Valid committed content-entry identifier. |
| `quotation_text` | String | Complete original selected quotation, nonblank. |
| `quotation_identity` | String | Normalized identity of `quotation_text`. |
| `source` | String or null | Complete committed source; null when absent. |
| `attribution` | String or null | Complete committed attribution; null when absent. |
| `presentation_style` | String | `"centered"` or `"left-aligned"`. |
| `font` | String or null | Captured authored font preference; null when absent. |
| `font_faces` | Object | Captured literary-role face preferences. |
| `background` | String or null | Captured authored background preference; null when absent. |
| `decoration` | String or null | Captured authored decoration preference; null when absent. |
| `text_color` | Nonempty array of strings or null | Captured authored text-color preferences; null when absent. |
| `decoration_color` | Nonempty array of strings or null | Captured authored decoration-color preferences; null when absent. |
| `reveal_schedule` | Object | Complete committed effective reveal schedule. |
| `resolved_reveal_stages` | Array of objects | Complete frozen reveal-stage sequence. |
| `scheduling` | Object | Committed scheduling context. |
| `actions` | Array of objects | Complete ordered committed action declarations; empty array when none. |

The content-entry identifier, quotation identity, resource preferences, palette references, and action declarations use their applicable semantic constraints from [Content Entries](CONTENT.md).

`quotation_identity` must equal the result of applying Refrain's defined quotation-normalization rules to `quotation_text`. It is not an independently authored value.

A non-null `source` or `attribution` must contain non-whitespace text. Preserve its original whitespace and Unicode content without trimming or normalization.

`font_faces` maps zero or more of `quotation`, `source`, and `attribution` to valid face identifiers. No other keys are permitted.

Color-preference arrays preserve their authored member order and duplicates. Their elements are valid palette identifiers or applicable named-pool references. Do not resolve preference pools or select presentation resources while validating the committed snapshot.

The snapshot contains semantic preferences, not resolved artistic resources, raster geometry, destination overrides, or publication events.

### Effective reveal schedule

The `reveal_schedule` object contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `quotation` | String | Valid `HH:MM` local time, equal to `scheduling.day_start`. |
| `source` | String | Valid `HH:MM` local time, not earlier than `quotation`. |
| `attribution` | String | Valid `HH:MM` local time, not earlier than `quotation`. |

Times use zero-padded 24-hour `HH:MM` notation.

The complete effective schedule is preserved even when an optional literary field is absent.

### Frozen resolved reveal stages

`resolved_reveal_stages` is a nonempty ordered array containing between one and three stages.

Each stage contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `instant` | String | Absolute UTC RFC-3339 timestamp ending in `Z`. |
| `visibility` | Object | Complete cumulative visibility for the stage. |

The `visibility` object contains exactly three Boolean fields:

- `quotation`
- `source`
- `attribution`

Stage indexes are zero-based array positions. The sequence is subject to all of the following constraints:

- Stage instants are strictly increasing in absolute time.
- Stage zero is the initial reveal stage.
- `quotation` is true at every stage.
- Visibility is cumulative: a field that becomes true never becomes false in a later stage.
- If `source` or `attribution` is absent from the snapshot, its visibility is false in every stage.
- Every present optional literary field is visible in the final stage.
- Each stage represents a distinct resolved reveal instant; fields resolving to the same instant share one stage.
- A stage must introduce visibility of at least one previously hidden field, except that stage zero establishes initial visibility.

The sequence is resolved using the host-local timezone and civil-time rules applicable at selection commitment. It is committed atomically with the snapshot.

After commitment, the recorded instants, ordering, and visibility are authoritative. Recovery must not re-resolve them using the host's current timezone or daylight-saving rules.

Do not persist a timezone identifier or replace the frozen sequence when the host timezone changes.

The effective `reveal_schedule` remains available as committed semantic content, but it does not authorize reconstructing or altering `resolved_reveal_stages` after recovery.

### Scheduling context

The `scheduling` object contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `display_date` | String | Calendar date in `YYYY-MM-DD` form. |
| `day_start` | String | Valid zero-padded 24-hour `HH:MM` local time. |

The display date identifies the committed selection's logical display date. The day-start value records its effective scheduling context.

### Committed actions

Every member of `actions` is an object containing exactly:

| Field | Type | Constraint |
|---|---|---|
| `type` | String | Valid action-type identifier. |
| `visibility` | Array of strings | One or both of `"public"` and `"private"`, without repetition. |
| `payload` | String | Complete opaque payload, at most 10,240 UTF-8 bytes. |

Preserve declaration order, duplicates, visibility declarations, and payload bytes as represented by the committed Unicode strings.

The payload field is required even when it is the empty string.

All newly committed snapshots require the `actions` field. An absent or invalid `actions` field is an operational-state validation error.

## Global history

The active history file is `global-history.jsonl` in the effective state directory.

The file uses UTF-8 JSON Lines. Each complete record is one JSON object serialized on a single line, terminated by a newline.

A record contains exactly:

| Field | Type | Constraint |
|---|---|---|
| `revision` | Integer | Positive committed selection revision. |
| `display_date` | String | Committed logical date in `YYYY-MM-DD` form. |
| `selection_timestamp` | String | UTC RFC-3339 event timestamp ending in `Z`. |
| `quotation` | String | Complete original selected quotation text, nonblank. |
| `source` | String or null | Complete committed source; null when absent. |
| `attribution` | String or null | Complete committed attribution; null when absent. |

A non-null source or attribution must contain non-whitespace text. Preserve its original Unicode content and whitespace.

History contains neither `quotation_text` nor `quotation_identity` fields.

The quotation, source, and attribution are copied from the committed selection, independently of its currently revealed stage.

Records are emitted as compact UTF-8 JSON without insignificant whitespace, followed by one newline. Preserve literal Unicode characters rather than replacing them with ASCII escape sequences.

For example:

```json
{"revision":1,"display_date":"2026-11-20","selection_timestamp":"2026-11-20T10:00:00Z","quotation":"A quiet morning.","source":"A Collection of Thoughts","attribution":"Example Author"}
```

For absent source and attribution, both fields remain present with JSON null values.

Global history is an append-only, best-effort record of selection events. It is not authoritative operational state and does not participate in selection revision assignment, repetition eligibility, or reveal progression.

Rotation, retention, interrupted-append recovery, consistency, and concurrency requirements belong to [Global history and retention](../specifications/30-SELECTION_AND_PERSISTENCE.md#global-history-and-retention).
