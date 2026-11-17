# Publication manifest format

This document is the authoritative specification for the filesystem
publication manifest. It is independent of the version-1 publication metadata
schema defined in [Publication Metadata](PUBLICATION_METADATA.md). Runtime
ownership and commit behavior belong in
[Architecture](ARCHITECTURE.md#filesystem-publication-target-backend-integration-planned);
storage safety and validation guidance belong in
[Engineering](ENGINEERING.md#filesystem-publication-storage).

## Manifest document

Each destination directory has one stable `manifest.json`. It is a UTF-8 JSON
object with exactly these fields:

| Field | Type | Required value |
|---|---|---|
| `schema_version` | Integer | Exactly `1`; booleans are not integers for this contract |
| `publication_id` | String | Identifier matching the constraints below |
| `image_filename` | String | Exactly `<publication_id>.png` |
| `metadata_filename` | String | Exactly `<publication_id>.json` |
| `image_sha256` | String | Lowercase 64-character hexadecimal SHA-256 digest of the image bytes |
| `metadata_sha256` | String | Lowercase 64-character hexadecimal SHA-256 digest of the metadata bytes |

No additional fields are defined. A reader rejects missing or unexpected
fields, duplicate JSON object keys, invalid JSON, nonstandard numeric values,
invalid UTF-8, and an unsupported schema version. Version `1` has no
compatibility fallback or implicit migration; a reader must not interpret an
unsupported version as version `1`.

## Identity and filenames

`publication_id` must match
`[A-Za-z0-9][A-Za-z0-9_-]{0,239}` and must not be a reserved Windows device
name (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, or `LPT1`–`LPT9`, without
regard to case). The 240-character maximum leaves room for either extension
within common filesystem filename-component limits and excludes path
separators, dots, traversal components, and drive-qualified paths.

The two filenames are derived exactly from that identity. They are relative
single-component filenames in the same destination directory; readers never
accept arbitrary paths, absolute paths, or traversal in manifest fields.
`manifest.json` itself is the only manifest filename.

The destination directory is a direct child of the configured publication
root. Its name is the destination's validated identifier, matching the
canonical destination syntax `[A-Za-z0-9][A-Za-z0-9_-]*` with a maximum length
of 256 characters. Destination IDs are not supplied as paths, and no
destination identifier appears as an alternate file path in the manifest.

## Dataset validation

The manifest publication ID, image filename, metadata filename, and hashes
identify one dataset. A reader accepts the dataset only after it has read the
current manifest, safely opened both referenced regular files within the same
destination directory, verified each SHA-256 digest, and validated the
completed publication metadata and its association with the publication and
destination IDs. The image dimensions must agree with the completed metadata's
output specification.

Publication metadata retains its own independent schema and validation rules.
The manifest does not duplicate its fields, record a destination audience, or
contain a history index. The stable manifest replacement is the
consumer-visible commit point; a temporary manifest is never authoritative.
