# Filesystem Publication and Consumers

## Publication destinations and ownership

Refrain remains responsible for content selection, scheduling, image preparation, and publication to directly attached displays. `window` and `waveshare-13in3-e` remain resident-owned direct-display backends. The built-in `publish` backend is the sole non-direct destination mechanism. The resident does not host HTTP services and does not require network availability. Publication support provides reusable storage, manifest validation, and maintenance behavior; backend registration integrates publication with the resident's existing destination coordinator and runtime-control path.

Each `publish` destination has its own validated ID, resolved output specification, publication audience, presentation overrides, and directory. It publishes the destination-specific presentation prepared by Refrain. Scheduled preparation groups destinations only when their effective presentation requirements match; within a group, presentation-wide artistic choices are resolved once and kept consistent across output specifications. Different effective overrides, including backgrounds, decorations, fonts, colors, tint, or QR settings, must not share prepared images even when output specifications match. Prepared variants may be shared only when both the output specification and effective presentation requirements match. Destinations never share identity, audience, overrides, directory, or publication acknowledgement. A destination directory is a direct child of the publication root, derived only from that validated ID. Destination configuration never supplies an arbitrary deletion path. Publication directories belong to Refrain, not to consumers; multiple consumers may read the same directory.

Destination overrides affect scheduled rendering only. A transient finished image supplied to push is already destination-ready: it is validated against the requested dimensions and published unchanged, without applying destination rendering overrides or preparation.

## Prepared metadata and event finalization

The shared publication-metadata module defines one version-1 JSON schema for prepared scheduled-image metadata and completed scheduled or transient publication metadata. Preparation metadata captures the committed quotation identity, selection revision, logical display date, effective reveal schedule and stage, complete single-quotation reconstruction input, canonical presentation, effective destination presentation, actual output specification, and unfiltered ordered actions alongside the prepared image.

The application-level finalizer accepts prepared metadata when completing a scheduled publication, or no prepared metadata for a transient publication. The caller supplies the publication-event ID and timezone-aware event timestamp, destination ID, actual output specification, and—when scheduled— the image's reveal stage and destination audience. Finalization validates that the image corresponds to the prepared output and stage, copies rather than mutates shared preparation data, and filters actions for exactly one nonhierarchical `public` or `private` audience. It does not choose content, resolve artistic resources, render images, inspect committed runtime state, access a display, or write files. The publication ID is supplied by the publication event owner; it is not generated during preparation.

Transient finalization never reads selection or preparation state. Finished images submitted through `--image`, viewer previews, and information-view images all use the same minimal transient representation. Classification does not alter information-view scheduling, publication priority, duration, or acknowledgement behavior.

The finalizer and JSON validator are hardware-independent application operations used by resident filesystem publication. Scheduled publication loads metadata from the same compatible prepared-image collection as the selected image, then independently finalizes it for each destination. Transient and information-view images use the minimal transient representation and do not read scheduled preparation or selection state.

Use the shared versioned schema and exact field contract in [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes) for both prepared and completed documents. Scheduled reconstruction metadata must preserve the canonical presentation separately from the effective destination presentation. The canonical stable selections come from authoritative operational state; effective metadata records the actual resolved choices, QR inclusion or suppression, and geometry used to prepare the destination image. Keep finalization, validation, parsing, and serialization hardware-independent and based on small JSON-compatible values. Use the standard-library JSON module; serialize deterministically as UTF-8 JSON, reject duplicate object keys and nonstandard numeric values, and validate both preparation and completed stages. Do not use pickle, executable payloads, raw resource paths, resource bytes, RGB values, or raster-layout calculations.

The application-level finalizer must receive the publication-event identity and timestamp, destination identity, actual output specification, and the appropriate prepared metadata and reveal stage for scheduled publication. It must receive no scheduled preparation for transient publication. Finalization must not select content, resolve resources, render images, access resident state or a display backend, mutate cached preparation, or write publication files. Validate destination audience filtering before serialization, including that public output contains no private-only actions in any nested content. Transient documents must contain no scheduled association, reconstruction data, or actions.

Automated tests must cover schema-stage validation, canonical/effective metadata separation and immutability, effective-value representation for every override including decoration-suppression geometry and QR suppression, Unicode JSON round trips, timezone-aware publication timestamps, exact destination/output association, public/private filtering and privacy leakage, order and duplicate preservation, transient metadata, and shared-preparation immutability. These operations must run without a resident process, display hardware, network service, systemd, or publication directory. Filesystem publication, manifest handling, and viewer reconstruction are separate capabilities; viewer reconstruction consumes this schema through the shared renderer, and the filesystem writer validates this completed metadata against its independent manifest contract. The resident `publish` backend supplies the image and exact compatible preparation metadata to the finalizer and writer; hardware-independent end-to-end coverage verifies manifest integrity, audience isolation, transient behavior, and viewer reconstruction independently of the content library.

## Destination metadata and audience filtering

Metadata describes the presentation actually published by one destination, not a generic serialization of the resident's daily selection. Its versioned JSON document contains publication identity, type and timestamp; destination identity and actual output specification; applicable display date, selection identity and actual reveal stage; optional reconstruction data; and an ordered, audience-filtered action sequence. The destination's required `audience` is policy supplied to finalization; it is never a field in preparation or completed metadata, including nested reconstruction content. Publication type is `scheduled` or `transient`. Use explicit `null` values for inapplicable structured fields. The exact scheduled-publication field names, types, and preparation/completion validation stages are defined in [Publication metadata](../schemas/PUBLICATION.md).

Scheduled metadata provides sufficient reconstruction data for a `refrain-viewer` publication mode to render the prepared destination's presentation at another requested aspect ratio and resolution. It includes a valid generated single-quotation content entry derived from the committed selection, the canonical presentation, and the actual effective background and decoration identifiers, font identifier and role-specific faces, palette identifiers, presentation style, QR behavior, insets, and font-size bounds used for that destination. The embedded entry conforms to the authoritative [content-entry format](../schemas/CONTENT.md#entry-fields).

Persist canonical selections with the committed daily selection before destination preparation. Apply each destination's restricted overrides to derive the effective presentation; capture that actual effective result and the output specification from the same preparation operation that produces the image. Do not repeat random canonical selection, infer choices from finished pixels, or re-resolve either record when serializing metadata. The canonical presentation is authoritative selection state; effective destination values are derived prepared metadata. Preserve stable resource and palette identifiers rather than embedding asset contents or RGB values. Do not persist calculated text positions, crop geometry, or other output-dependent layout results. Future reconstruction recalculates geometry through the existing renderer for the requested output specification, using the currently installed Refrain assets and palette definitions; it does not promise archival reproduction if those resources or rendering behavior change. Metadata records the actual reveal stage, while reconstruction input has the complete committed quotation.

Preparation caches the canonical and effective reconstruction metadata with the exact compatible image collection using this same publication-metadata schema. A complete compatible cache therefore includes valid images and valid associated metadata. Reusing the images reuses their recorded effective choices; do not repeat random selection or infer choices from finished pixels to reconstruct missing metadata. Missing, damaged, inconsistent, or incompatible required metadata makes that collection unusable for reconstruction-capable publication. Regenerate its compatible images and metadata together from the committed selection and persisted canonical presentation, without changing its identity, history, canonical choices, or reveal progression. The cache remains disposable derived storage.

The finalizer starts from cached metadata and derives an independent destination-specific instance. It finalizes publication identity and timestamp, actual destination and output specification, actual reveal stage, and audience-filtered actions. It preserves the committed literary identity, the unchanged canonical presentation, and the effective choices that produced the image; it validates the completed document before serialization and never mutates shared cached metadata. Distinct destinations may derive different completed documents from compatible preparations. The resident passes each completed document and its corresponding image to the filesystem writer; successful acknowledgement follows manifest commit.

Each configured destination declares exactly one audience: `public` or `private`. The application obtains this policy from the validated destination configuration and supplies it to finalization; the policy is not inferred or copied into metadata. It is independent of each action's visibility and of presentation overrides. Destinations with equivalent presentation requirements share prepared-image groups and unfiltered metadata even if their audiences differ; audience does not affect cache identity.

Visibility is nonhierarchical: a public destination includes actions declaring `public`; a private destination includes actions declaring `private`; an action declaring both is included for either audience. Preserve eligible actions in their original order, including duplicates. Actions are metadata only and are never implicitly executed by publication or a consumer. Public metadata must never expose private-only actions. Audience filtering does not replace filesystem permissions, authentication, or consumer-side authorization.

Transient publications use the same minimal metadata contract whether their image originated from `--image` or a viewer-generated preview. Their metadata contains publication identity, destination identity, type, timestamp, and output specification, but no committed-presentation association, scheduled selection metadata, literary reconstruction data, or actions. The action sequence is always empty. Transient publication is an image-delivery event, not a reconstructable presentation. Do not extend transient IPC to transfer literary or rendering metadata.

Information-view images use this same transient metadata representation:

```json
{
  "publication_type": "transient",
  "presentation": null,
  "reconstruction": null,
  "actions": []
}
```

The normal publication envelope still supplies publication identity, destination, timestamp, and output specification. The implemented `refrain-viewer --publication` mode rejects this and every other transient publication. The `publish` backend receives the image and corresponding finalized metadata from the application; it does not inspect operational state to infer presentation semantics.

For reconstruction-capable publication, verify that preparation metadata uses the exact publication metadata schema and remains associated with its compatible image collection after cache reuse and process restart. Cover missing or corrupted metadata, mismatched image and metadata collections, compatible destinations sharing prepared images, destinations with different presentation overrides, and adding a `publish` destination that can reuse compatible cached images. Verify destination-specific finalization creates independent complete metadata without mutating shared cached metadata or another destination's result.

Every configured destination must explicitly declare audience `public` or `private`; test missing, null, empty, wrong-type, and unsupported values for rejection before runtime startup. Verify audience is retained on the destination but excluded from publication metadata and prepared-image identity. Preparation keeps every committed action declaration unchanged; finalization filters by destination audience while preserving action order, duplicates, and each included declaration's complete visibility list. Completed scheduled serialization must require an audience and reject actions not visible to it. Test that prepared metadata cannot be serialized or consumed as a completed publication and that blank publication IDs are rejected consistently.

## Transient publication metadata

When publication metadata is produced, an information-view image is a transient publication, like any other pushed transient image. It uses the minimal transient metadata representation and has no association with the committed daily quotation, scheduled-selection metadata, literary reconstruction data, or actions. Its publication envelope still identifies the publication, destination, timestamp, and output specification. Its transient classification does not make the internally scheduled startup view an external IPC request or change its publication priority, duration, or restoration behavior.

Treat an information-view image as transient for publication metadata, using the same minimal representation as other transient publications: `publication_type: transient`, `presentation: null`, `reconstruction: null`, and an empty `actions` sequence. It has no committed daily quotation association, scheduled-selection metadata, literary reconstruction data, or actions. Its normal publication envelope still identifies the publication, destination, timestamp, and output specification. Distinguish information-view publication identity from committed daily presentation identity without exposing view semantics to display backend implementations.

Include hardware-independent automated tests covering:

- the minimal transient publication metadata for information views, with no scheduled-selection association, reconstruction data, or actions;

## Publication paths and containment

Before any destructive publication operation, reject a resolved publication root that overlaps protected Refrain data: configuration, content, user assets, authoritative state or history files, prepared-artifact/cache directories, or other protected configured storage. Overlap includes a root equal to, inside, or an ancestor of a protected data path when cleanup could reach that data. Compare against effective custom paths as well as standard paths. The standard publication root may share the platform operational-data parent with sibling state and history files, but must not contain, replace, or be contained by those protected data targets. Perform these checks before creating or cleaning a destination; fail closed if safe separation cannot be established.

Path validation and destructive operations must prove that a destination stays within the publication root and must reject traversal, symbolic links, junctions, reparse points, and other filesystem redirection. Never follow a redirecting path or delete an object outside the owned destination directory. Reject unsafe destinations rather than attempting cleanup or repair.

## Dataset commit and consumer recovery

Each destination directory contains one current complete single-frame PNG image, one versioned JSON metadata document, and a stable `manifest.json`. For example:

```text
<publish-root>/
├── default/
│   ├── manifest.json
│   ├── <publication-id>.png
│   └── <publication-id>.json
├── web-public/
└── web-private/
```

The exact manifest fields, filename constraints, and version behavior are defined in [Publication manifest](../schemas/PUBLICATION.md#manifest-fields). The metadata schema is versioned independently in [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes). Image and metadata filenames derive from the publication ID in the completed metadata. Consumers read the manifest, verify both referenced files and their hashes, and accept only a complete matching dataset.

The reusable writer receives a completed image and its already-finalized metadata. One publication follows this order:

1. Validate their publication and destination identities, metadata contract,
   and image dimensions.
2. Write and complete uniquely named image and metadata files, then compute
   their SHA-256 hashes.
3. Write and complete a temporary versioned manifest describing those files.
4. Atomically replace `manifest.json` with the complete temporary manifest.
5. Remove superseded publication files and recognized temporary contents.

Replacing `manifest.json` is the consumer-visible commit point; atomic replacement of a whole directory is not required. Never overwrite the files referenced by the current manifest before the replacement. A failure before commit leaves the prior valid dataset current. A failure after commit must not invalidate the new publication. A malformed manifest, missing referenced file, hash mismatch, unsafe directory object, or uncertain ownership is reported without repair or acceptance as a valid dataset. On a subsequent publication, the writer removes only recognized stale temporary or superseded files owned by the destination. Consumers tolerate incomplete or unavailable reads using bounded retries. A consumer that starts after publication recovers solely from the current manifest and its referenced files. Do not add publication history, backups, a filesystem transaction framework, or a separate publication daemon.

When this writer is integrated, publication failures will use the existing per-destination bounded retry and eventual-failure behavior; after exhaustion, a later publication opportunity will permit another attempt. This storage implementation does not schedule retries or alter committed selection state.

## Dataset writer and reader validation

The hardware-independent filesystem writer stores one current dataset per validated destination ID. The resident-owned `publish` destination backend uses the existing per-backend coordinator and writes already-finalized metadata with its matching complete image. Follow the ownership and commit behavior in [Publication destinations and ownership](#publication-destinations-and-ownership) and [Dataset commit and consumer recovery](#dataset-commit-and-consumer-recovery), the root setting in [Storage](../schemas/CONFIGURATION.md#storage), the exact [manifest contract](../schemas/PUBLICATION.md#manifest-fields), and the independent [metadata contract](../schemas/PUBLICATION.md#metadata-validity). Use `pathlib` for path construction, keep every destination as a direct child of the effective publication root, and derive its name only from a validated destination ID. Destination configuration must not accept an arbitrary path to delete.

Scheduled publication metadata must be loaded from the compatible prepared variant associated with the selected image, then finalized independently for each destination and audience. Transient publications use minimal metadata and must preserve submitted image pixels. Acknowledge scheduled publication only after the writer's manifest commit is verified; do not persist a second acknowledgement state or introduce a filesystem retry worker.

Validate root and destination ownership before any destructive operation. Reject symbolic links, Windows junctions, reparse points, traversal, unexpected objects, and any other redirection at the root or along a destination path. Containment checks must not resolve an unsafe link and then treat its target as owned. Traverse owned directories without following links; never remove a destination outside the publication root. On uncertain ownership or unsafe objects, fail without attempting repair or deletion.

Before creating or cleaning a destination, reject a publication root that overlaps protected configuration, content, asset, operational-state, history, cache, artifact, or other configured storage paths. Compare resolved standard and custom storage targets and reject equality, nesting, or an ancestor root whose cleanup could reach protected data. The standard publication root may share the operational-data parent with sibling state and history files, but must not overlap those protected file targets. If safe separation is uncertain, fail before the destructive operation. Standard `--purge` remains limited to platform-standard locations and never follows or deletes a custom `storage.publish` override.

Validate already-finalized metadata with the shared completed-publication contract; verify its publication and destination identities and output dimensions against the image. Do not select content, alter metadata, resolve resources, or filter actions in storage. Write unique image and metadata files and close them before preparing and closing a temporary manifest. Replace the stable manifest atomically in the destination directory; this replacement is the commit point. Use same-filesystem replacement and synchronize directory metadata where supported. On Windows, report replacement failures without claiming a commit; if replacement has occurred, retain the new dataset and report a post-commit failure distinctly.

Consumers validate the manifest and referenced filenames as untrusted input, verify both SHA-256 hashes, validate metadata association, and accept only a complete matching dataset. A consumer reads but never rewrites, cleans, or claims ownership of publication directories. Keep retries bounded; recovery after consumer restart starts from the current manifest, not from process-local state or publication history. Do not add a transaction journal, backup generations, or an unbounded retry loop.

Automated tests cover initial publication and replacement, manifest and hash validation, destination and metadata association, image dimensions, failures before and after replacement, stale temporary cleanup, corrupted or missing current files, directory isolation, and controlled reader observations across manifest replacement. Filesystem validation must also cover protected-path overlaps and symbolic links, junctions, and reparse points where supported. Run the hardware-independent tests on both Linux and Windows; do not treat Linux-only execution as cross-platform validation.

Test interruption and failure before and after the manifest replacement, concurrent readers observing replacement, hash mismatch, absent or superseded files, restart recovery, bounded retry exhaustion, and cleanup isolation among multiple destinations. Include traversal and symlink/junction/reparse-point cases where the platform supports them; skip only an unavailable filesystem capability with an explicit reason. Exercise filesystem behavior on both Linux and Windows. Consumer services and path handling must not assume systemd or Linux filesystem conventions in hardware-independent tests.

For filesystem publication, verify that standard and configuration-relative or absolute custom publication roots overlapping protected configuration, content, asset, operational-state, history, cache, artifact, or other storage targets are rejected before writes or cleanup. Also verify that the platform-standard publication root remains valid as a sibling of the authoritative state and history files beneath its operational-data parent, without overlapping either file path. Validate destination identifiers, manifest schema and hashes, completed metadata/image association, destination isolation, unsafe links and reparse points, and fail-closed handling of unexpected publication objects. Use fault injection to cover interrupted image, metadata, temporary-manifest, and stable-manifest writes; verify that pre-commit failures preserve the previous dataset and post-commit failures preserve the new one. Cover stale temporary recovery, corruption and missing files, reader behavior during manifest replacement, and initialize/reset/purge ownership exclusions on Linux and Windows.

## Independent consumers

Consumer services are separate executables in the same Refrain installation and use the shared `config.yaml`. Each reads and validates its own top-level configuration section (including planned `image-server:` and `web-companion:` sections), identifies the publication destinations it consumes, and reads and verifies their datasets without modifying them. A service may invoke the installed `refrain-viewer` for custom rendering, but does not select quotations or modify Refrain operational state.

Consumers start, stop, and recover independently of the resident. They do not acquire the resident's exclusive runtime lock. The resident does not spawn, supervise, or depend on them. Consumer enablement in application configuration is distinct from service enablement in systemd. Use existing operating-system service facilities, including systemd on supported Linux deployments; do not add a service manager, general plugin or service-registration framework, additional Python distribution, or network IPC mechanism. The integrated `image-server` remains in place until the independent `refrain-image-server` replacement is implemented and validated. Add future consumer integrations only when justified. Hardware-independent development and testing must remain usable on Windows without assuming systemd or Linux filesystem conventions.

Filesystem publication is the sole non-direct destination mechanism; consumers read Refrain-owned publication data without modifying it or sharing the resident's lifecycle. The current integrated `image-server` is transitional and remains in place until its independent consumer replacement is implemented and validated.

## Consumer integrations and trust boundaries

A `refrain-web-companion` consumer is planned for a later release. It runs as a separately supervised process in the same Refrain installation and reads destination publications without modifying them.

It may use published metadata and invoke the installed `refrain-viewer` to reconstruct a presentation at browser-appropriate geometry. It does not own selection or require the browser and e-paper display to consume identical image files.

Web presentation must not become responsible for daily quotation selection.

The current integrated `image-server` remains in place until its independent consumer replacement is implemented and validated. The target resident does not host HTTP services or depend on a consumer being enabled or running.

Optional public presentation is deferred.

The architecture distinguishes public presentation information from privileged local operations.

A future public deployment may operate on a separate device or service outside the trusted local network.

Public publishing must not require exposing privileged local application interfaces.

An outbound-only publication path is preferred where it satisfies the future requirements.

The exact publication mechanism and trust boundaries will be specified before that feature is implemented.

Public presentation does not grant privileged local control.

## External action publication

Publication of actions to external consumers is deferred. Future metadata publication must respect each action's explicitly declared visibility audiences and must not expose actions to destinations outside those audiences.

Privileged operations must not become available to anonymous public viewers merely because associated content is publicly visible.

External integrations must be explicitly configured and must not introduce mandatory cloud or network dependencies into ordinary display operation.
