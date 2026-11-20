# Filesystem Publication and Consumers

## Publication destinations and ownership

Refrain owns literary selection, scheduling, image preparation, and publication to its configured destinations.

`window` and `waveshare-13in3-e` are resident-owned direct-display backends. The built-in `publish` backend is the sole non-direct resident backend.

The resident does not host HTTP services, supervise consumers, or require network availability for filesystem publication.

Each `publish` destination has its own:

- Validated destination ID.
- Output specification.
- Required publication audience.
- Restricted presentation overrides.
- Refrain-owned destination directory.
- Independent publication acknowledgement.

One shared `publish` backend instance may manage multiple destinations. Sharing the backend instance does not merge destination identity, audience, publication events, directory ownership, or acknowledgement.

Scheduled destinations share prepared images only when their output specifications and effective presentation requirements are compatible. Audience does not change pixel compatibility.

The application prepares destination-specific images and finalizes publication metadata before passing them to the filesystem writer.

A transient finished image is already destination-ready. It bypasses scheduled artistic overrides and rendering preparation.

Publication directories are exclusively Refrain-owned. Consumers may read their completed datasets but must not create, modify, rename, or remove objects within them.

Multiple independent consumers may read one destination directory.

Destination configuration does not supply arbitrary filesystem paths. Every destination directory is a direct child of the effective `storage.publish` root, named only from the validated destination ID.

Filesystem publication uses the existing resident destination coordinator, per-backend serialization, failure isolation, and retry policy defined in [Destinations and Runtime Control](60-DESTINATIONS_AND_RUNTIME_CONTROL.md).

A successful `publish` operation means its complete dataset passed the verified filesystem commit point. It does not imply that a consumer has retrieved, accepted, or displayed the image.

## Prepared metadata and event finalization

Publication uses the four exact version-1 forms defined in [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes):

1. Content checkpoint.
2. Content-and-presentation checkpoint.
3. Completed scheduled publication.
4. Completed transient publication.

No fifth public preparation-metadata shape, rendering snapshot, embedded content-entry representation, or dual canonical/effective presentation model is defined.

### Shared checkpoints and preparation

The shared content checkpoint contains the committed selected quotation, effective reveal schedule, current visibility, and complete ordered action declarations.

The completed content-and-presentation checkpoint additionally contains the resolved destination-independent artistic choices.

Both checkpoints belong to the current committed selection and are persisted in the single `publication.json` file under `storage.state`.

Operational state remains authoritative for committed literary selection, selection revision, repetition history, and reveal progression. The completed publication checkpoint is the sole durable authority for resolved destination-independent artistic choices.

Destination-specific preparation derives an independent effective presentation from the validated shared checkpoint, applicable destination overrides, output requirements, and currently available resources.

The shared checkpoint must not be modified by destination preparation.

Its `presentation.qr.enabled` records canonical QR policy. Output-dependent `presentation.qr.available` is omitted from the shared checkpoint and resolved separately for each destination.

Prepared-image caches contain complete images and the internal association and integrity data needed to reuse them safely. They do not establish another public metadata form or independently authoritative artistic record.

A compatible cached image must remain associated with the committed selection, effective presentation requirements, output specification, and reveal-stage visibility that produced it.

A failed or incompatible cache is regenerated using the established recovery requirements without literary reselection or reveal regression.

Prepared-image cache identity, complete-set atomicity, and regeneration belong to [Presentation and Rendering](50-PRESENTATION_AND_RENDERING.md#cache-identity-publication-and-regeneration).

### Event finalization

The application-level publication finalizer constructs one independent completed metadata document for each destination publication event.

For scheduled publication, the finalizer receives:

- The committed literary content and effective reveal schedule associated with the selected prepared image.
- The visibility applicable to that image's reveal stage.
- The actual resolved effective destination presentation associated with the prepared image.
- The destination's required audience and original ordered action declarations.
- The publication-event ID and UTC timestamp.
- The exact destination ID and output specification.

The finalizer validates the prepared image's applicable selection, visibility, effective-presentation, and output associations before completing metadata.

It copies the required data into the completed scheduled form, filters actions for the destination audience, and populates the `publication` section.

The completed scheduled publication contains exactly `schema_version`, `content`, `presentation`, and `publication`.

Its `presentation` object records one effective set of resolved artistic values, not separate canonical and destination presentations.

The completed `presentation.qr` object includes both effective `enabled` and actual `available` values.

`content.reveal_stage` records the three Boolean visibility values represented by the published image. It does not contain a numeric reveal-stage index.

The completed document records the applicable publication event, not subsequent changes to reveal progression or artistic configuration.

Never retrospectively modify a completed publication document when the shared checkpoint changes.

The finalizer must not:

- Choose literary content or artistic resources.
- Rerender or alter image pixels.
- Read or modify operational state.
- Change the shared publication checkpoint.
- Interpret or execute actions.
- Write filesystem publication data.
- Access or initialize a display backend.

Publication identity is supplied by the publication-event owner. Do not invent publication IDs or timestamps during image preparation.

Use the shared hardware-independent metadata validation and serialization implementation.

The finalizer must produce a complete document satisfying its selected form before passing it to the filesystem writer.

The filesystem writer must validate the completed document independently before committing the dataset.

### Publication validation boundaries

Validate exact document forms, required and prohibited fields, types, identifiers, supported values, permitted nulls, output associations, destination identity, and applicable audience requirements.

Reject unsupported versions, duplicate JSON keys, nonstandard numeric values, malformed Unicode, partial objects, unexpected fields, or unresolved required values.

Enforce inexpensive semantic consistency needed to prevent unsafe consumption, including impossible QR policy/availability combinations and visibility flags inconsistent with absent literary fields.

Do not recalculate reveal schedules, load rendering resources, measure text, perform QR placement, or repeat image composition merely to validate completed metadata.

Preparation is responsible for producing semantically correct rendered images and matching metadata. The validator is responsible for enforcing the documented structural, association, and safety constraints.

Use deterministic UTF-8 JSON serialization through the standard-library JSON module, preserving literary Unicode and action order.

Do not use pickle or executable serialization. Do not embed source-asset bytes, font files, absolute resource paths, raw RGB values, or raster-layout plans in publication metadata.

Automated tests must cover all four document forms, rejection of incomplete or wrong-stage metadata, exact effective values, reveal visibility, checkpoint immutability, event identity, output association, Unicode serialization, and independent finalization for multiple destinations.

## Destination metadata and audience filtering

Every configured destination declares exactly one publication audience: `public` or `private`.

The audience is validated as destination configuration before resident startup and is supplied independently to scheduled publication finalization.

The audience is not stored as a field in publication metadata and must not be inferred from the destination ID.

Audience affects published actions, not prepared image identity or artistic resource selection.

The committed selection and shared publication checkpoint preserve the complete ordered action declarations.

Before serializing or exposing completed scheduled publication metadata, copy and filter those declarations for the destination's audience.

Visibility is nonhierarchical:

- A `public` destination includes an action only when its visibility explicitly includes `public`.
- A `private` destination includes an action only when its visibility explicitly includes `private`.
- An action declaring both audiences is included for either destination.

Preserve the original order of included actions, including duplicate declarations, original payloads, and each included action's complete visibility declaration.

Do not add an audience field or rewrite an included action's visibility values.

The completed scheduled publication contains only its filtered `content.actions` array.

A public destination must not expose private-only actions in its completed metadata, including through redundant or nested fields.

The shared checkpoint remains unchanged, so another destination can independently filter the same original actions for its audience.

### Completed-publication limits

The committed content and shared checkpoints retain the authoring limits established by [Publication metadata](../schemas/PUBLICATION.md#actions).

Completed scheduled publication has stricter external-delivery limits:

- At most 16 audience-filtered action declarations.
- At most 4,096 UTF-8 bytes per serialized action object.
- At most 65,536 bytes for the entire serialized completed metadata document.

Apply audience filtering before checking completed-publication action count and byte limits.

Byte limits apply to the exact deterministic serialized UTF-8 representation, not Python character counts.

Do not silently truncate, drop, reorder, or rewrite eligible actions or their payloads to satisfy these limits.

If an otherwise valid selected quotation cannot produce completed metadata within the applicable limits, report a destination publication failure with an actionable diagnostic.

Such failure must not invalidate committed selection, alter repetition history, modify the shared checkpoint, or prevent independent destinations from publishing valid datasets.

Completed transient publications contain no actions and remain subject to the completed metadata size limit.

Validate these constraints before writing a publication dataset.

Audience filtering does not replace filesystem permissions, service authentication, or consumer-side authorization.

Actions are opaque metadata. Neither finalization nor the filesystem publisher executes them.

Automated tests must cover:

- required destination audiences and invalid configuration values;
- independently filtered public and private publications;
- declarations visible to both audiences;
- preservation of ordering, duplicates, visibility arrays, and payload text;
- absence of private-only data from public metadata;
- shared checkpoint immutability;
- filtering before completed-publication size checks;
- action-count, per-action byte, and total metadata byte limits;
- no silent truncation or partial publication when limits are exceeded;
- failure isolation across destinations with different audiences.

## Transient publication metadata

A transient publication describes a completed image-delivery event without associating it with a committed daily literary selection.

Completed transient metadata contains exactly:

- `schema_version`.
- `publication`.

Its `publication.type` is `"transient"`.

It contains no `content` or `presentation` object, action sequence, reconstruction input, or null placeholders for omitted sections.

The publication section records the event ID, UTC timestamp, destination ID, and actual output specification.

Finished-image viewer pushes and externally submitted transient images use this form.

Information-view images also use the completed transient form when published to a `publish` destination.

Their classification does not turn automatic startup information-view presentation into an external IPC request or alter its timing, publication priority, or scheduled-acknowledgement behavior.

The no-eligible-content fallback likewise uses the completed transient form for filesystem publication, because it is not a committed daily selection and cannot truthfully provide a committed selection revision.

That fallback remains an internally required literary presentation: render it with the established normal literary facilities and applicable destination presentation requirements, using the exact curated quotation and attribution defined in [No-eligible-content fallback](40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#no-eligible-content-fallback).

Transient metadata classification does not require the fallback to bypass literary rendering or behave as an externally submitted push.

Do not fabricate committed content, a selection revision, or scheduled checkpoint values to produce publication metadata for the fallback.

Transient publication must not modify authoritative operational state, repetition history, reveal progress, or the shared publication checkpoint.

Its filesystem dataset is independent of scheduled prepared-image persistence.

`refrain-viewer --publication` accepts only completed scheduled metadata and must reject every transient publication, including information-view and fallback publications.

Automated tests must cover exact transient document shape, omission of literary and artistic sections, independence from committed state, information-view classification, and no-eligible fallback publication without synthetic selection.

## Publication paths and containment

The effective `storage.publish` value identifies Refrain's publication root.

Each `publish` destination owns exactly one direct child directory of that root, named from its validated destination ID.

Destination configuration must not supply a separate arbitrary publication directory or cleanup path.

The publication root and every destination directory are Refrain-owned storage, not general-purpose user file directories.

### Protected-path separation

Before creating a publication destination or performing destructive cleanup, verify that the effective publication root and its cleanup scope do not overlap protected Refrain data.

Protected data includes:

- Configuration files and directories.
- Content libraries.
- User-owned assets.
- Authoritative operational-state files.
- Global history and publication checkpoints.
- Prepared-image artifact and cache directories.
- Other configured protected application storage.

Compare effective standard and custom locations, including configuration-relative and absolute paths.

Reject a publication root equal to, contained within, or an ancestor of protected storage when publication cleanup could affect that storage.

The standard Linux layout deliberately places `$XDG_STATE_HOME/refrain/publish` inside the standard `$XDG_STATE_HOME/refrain` state directory. This arrangement is valid because publication cleanup is confined to the `publish` subtree, while `state.json`, `publication.json`, and active and rotated global-history files remain outside that subtree.

This exception applies only to the established standard layout. It does not authorize arbitrary overlap with custom state, content, asset, artifact, or other protected storage. Verify that no protected files or directories fall within the effective publication cleanup scope.

On Windows, the standard publication and state directories are separate children of the local Refrain operational-data directory. Sharing that parent is valid and must not be rejected as an overlap.

If safe separation or containment cannot be established, fail before writing or removing publication objects.

### Path and component safety

Validate publication destination IDs according to [Application Configuration](../schemas/CONFIGURATION.md#destinations), including the additional filesystem-safe requirements for `publish`.

Reject Windows-reserved device names and case-insensitive directory-name collisions even on case-sensitive development filesystems.

Validate component lengths for supported Windows and Linux filesystems before creating publication directories.

The filesystem publication-event ID follows the exact identity and filename constraints in [Publication manifest](../schemas/PUBLICATION.md#identity-and-filenames).

Reject collisions with currently owned publication filenames, including case-insensitive collisions that would be unsafe on Windows.

Use paths derived solely from validated destination IDs, publication IDs, and fixed dataset filenames.

Reject absolute paths, traversal, unexpected separators, drive-qualified components, and unsafe filesystem redirection.

The publication root and selected destination directory must be actual directories, not symbolic links, junctions, reparse points, or redirected paths.

Validate containment and ownership before destructive operations.

Do not follow a symlink, junction, reparse point, or other redirecting filesystem object during cleanup.

Once ownership of an actual destination directory has been established, its complete contents are within Refrain's cleanup scope. Unexpected files and subdirectories are not protected merely because they are unfamiliar.

Delete contained non-current objects safely without following links outside the owned tree. A contained link may be unlinked as an object, but its target must never be traversed or deleted.

If containment, ownership, or safe non-following deletion cannot be established, fail closed with an actionable diagnostic rather than guessing.

The publication root must not be used as a mechanism to delete neighboring application or user data.

Standard `--reset` preserves publication storage. Standard `--purge` operates only on standard Refrain-owned roots and never follows configured custom publication paths.

Installation-management scope and confirmation requirements are defined by [Installation and Service Operation](80-INSTALLATION_AND_SERVICE_OPERATION.md).

Automated tests must exercise standard and custom paths, overlapping protected storage, safe sibling directories, unsafe redirection, case-insensitive collisions, reserved filenames, and complete destination-directory ownership.

## Dataset commit and consumer recovery

Every `publish` destination exposes one current complete dataset consisting of:

- One single-frame PNG image.
- One completed version-1 publication metadata JSON document.
- One stable `manifest.json`.

The image and metadata filenames are derived from the same publication-event ID.

The stable manifest contains the exact fields and filename associations specified by [Publication manifest](../schemas/PUBLICATION.md#manifest-fields).

For example:

```text
<publish-root>/
├── living-room/
│   ├── manifest.json
│   ├── publication-42.png
│   └── publication-42.json
└── kitchen/
    ├── manifest.json
    ├── publication-87.png
    └── publication-87.json
```

The manifest's `id` must equal `metadata.publication.id`.

The metadata destination ID must match the owning destination directory.

The metadata output dimensions must match the complete image.

Both referenced files must be regular files in the same destination directory without filesystem redirection.

The manifest records SHA-256 hashes of the exact image and metadata file bytes.

A valid manifest alone does not establish a valid dataset. Consumers must verify the complete association.

### Writer commit sequence

The reusable filesystem writer receives one completed image and its already-finalized metadata.

For each publication:

1. Validate the destination, completed metadata form, publication identity, output specification, image representation and dimensions, and filesystem component safety.
2. Verify ownership and containment of the publication root and destination directory.
3. Write the new image and metadata under unique publication-derived filenames that do not overwrite the files referenced by the current manifest.
4. Flush, synchronize, and close those files, then compute or verify their exact SHA-256 hashes.
5. Construct and validate a complete temporary manifest referencing the new files.
6. Flush, synchronize, and close the temporary manifest.
7. Atomically replace the stable `manifest.json` using same-filesystem replacement.
8. Verify the committed manifest and referenced dataset association before acknowledging publication success.
9. Clean superseded and other non-current contents from the owned destination directory without following filesystem redirection.

The atomic replacement of `manifest.json` is the consumer-visible commit point.

Do not attempt atomic replacement of the entire destination directory or require a general filesystem transaction framework.

Image and metadata files referenced by the current manifest must remain unchanged until another complete manifest has been committed.

Readers must never encounter a current manifest referencing partially written new files.

Use appropriate directory-metadata synchronization on POSIX where supported. Account for the weaker directory-entry durability available through standard-library facilities on Windows.

A failure before manifest replacement leaves the preceding verified dataset current.

An interruption after replacement may have committed the new dataset even when the writer did not receive confirmation. Reload and validate the current manifest and referenced files before deciding the result.

If the new event ID, hashes, destination, metadata, and image association verify successfully, treat the new publication as committed rather than repeating it.

If the preceding manifest remains current, the attempted publication was not committed.

If the outcome cannot be verified, report it as unconfirmed rather than claiming either definite success or definite failure.

Do not overwrite, remove, or replace a newly committed dataset merely because acknowledgement delivery failed.

A failure during post-commit cleanup must produce an actionable warning without converting a verified successful commit into a failed publication.

Cleanup may be retried at a later safe publication or maintenance opportunity.

After a verified commit, remove all non-current contents within that Refrain-owned destination directory, not merely filenames matching a recognized temporary pattern. Preserve the current manifest and exactly its referenced files.

Cleanup must not follow links, leave the destination directory, or remove files still required by an active safe publication operation.

A subsequent publication must tolerate stale temporary or superseded contents from an interrupted earlier attempt and reconcile them safely.

No additional dataset-history index, backup-generation scheme, transaction journal, or separate publication daemon is required.

### Publication acknowledgement and failure

The resident `publish` backend acknowledges success only after the complete dataset commit has been verified.

It does not wait for independent consumers to read the dataset.

A failed or unconfirmed publication must not alter committed literary selection, repetition history, reveal progression, or the shared publication checkpoint.

The backend uses the normal per-destination retry and failure-isolation policy. Filesystem storage itself does not introduce an independent retry scheduler.

Failure to publish one destination must not invalidate a successfully committed dataset belonging to another destination.

A shared backend-instance failure must be reported for the destinations actually affected, without claiming success for operations that did not complete.

## Dataset writer and reader validation

The reusable writer and reader operate without a physical display, resident selection engine, or network service.

Use the same exact completed-publication and manifest schemas for production validation and hardware-independent tests.

### Writer validation

Before committing, the writer verifies:

- Destination ID and publication ID validity.
- Filesystem-safe component and filename constraints.
- Required completed scheduled or transient metadata form.
- Matching metadata and manifest publication IDs.
- Matching destination directory and metadata destination ID.
- Image dimensions matching the publication output specification.
- Single-frame supported PNG representation.
- Actual image and metadata byte hashes.
- Safe destination ownership and path containment.
- Absence of overwrite or case-insensitive collisions with current dataset files.

Do not load content libraries, choose artistic resources, recalculate reveal schedules, filter actions, or render images in the filesystem writer.

Those operations belong to application preparation and finalization.

A completed scheduled publication must already contain its destination-filtered actions. The writer verifies the required completed-document constraints without silently changing them.

A completed transient publication must not contain content, presentation, or actions.

The writer must reject checkpoint forms as completed publication inputs.

### Consumer validation

Consumers treat the current manifest and its referenced files as untrusted input.

A consumer reading a destination:

1. Reads and validates the current stable manifest.
2. Validates both referenced filenames as confined single components.
3. Opens the referenced regular files without following unsafe filesystem redirection.
4. Reads each file with appropriate bounded allocation.
5. Verifies both SHA-256 hashes.
6. Validates the completed metadata form and its manifest, destination, and output associations.
7. Validates the complete image representation and dimensions before accepting it.
8. Confirms that the current stable manifest still identifies the verified dataset before reporting it as current.

If the manifest changes during verification, discard the inconsistent attempt and retry from a newly read current manifest.

Do not combine a manifest from one publication generation with image or metadata bytes from another.

If the manifest or referenced files are temporarily unavailable because of replacement, use bounded retries starting from the current manifest on each attempt.

An interrupted or failed verification must not cause the reader to accept an unverified or partially updated dataset.

When the bounded retry allowance is exhausted, report an explicit unavailable or invalid-current-publication result.

A consumer may continue displaying a previously verified image only when that image is explicitly represented as stale or unavailable, not as the current verified publication.

A consumer restart must recover from the current manifest and referenced files. It must not depend on previously retained process-local state or a publication-history index.

Consumers must not repair, rewrite, rename, or remove publication files or manifests.

### Required validation

Hardware-independent automated tests must cover:

- Initial publication and complete replacement.
- Independent destination directories.
- Scheduled and transient completed metadata.
- Exact manifest fields, publication identity, and filenames.
- SHA-256 verification of image and metadata bytes.
- Destination and output-specification associations.
- Rejection of missing, damaged, truncated, or mismatched files.
- Unsafe paths, symbolic links, junctions, reparse points, and traversal.
- Case-insensitive collisions, reserved names, and component limits.
- Protected-path overlap rejection.
- Standard sibling state/publication roots remaining valid.
- Interrupted image, metadata, temporary-manifest, and stable-manifest writes.
- Ambiguous manifest-replacement outcomes and verification.
- Pre-commit failure preserving the preceding dataset.
- Post-commit cleanup failure preserving successful publication.
- Cleanup of all non-current contents without escaping the owned directory.
- Concurrent readers across manifest replacement.
- Fresh-manifest retries and bounded exhaustion.
- Restart recovery without historical publication state.
- Preservation of healthy datasets during independent destination failure.
- Publication and consumer operation without network or display hardware.

Run applicable filesystem tests on Windows and Linux. Skip platform-specific link or redirection tests only when the capability is unavailable, with an explicit reason.

Do not treat Linux-only execution as complete cross-platform filesystem validation.

## Independent consumers

Consumer services are separate executables in the same Refrain installation.

They use the shared application configuration where applicable and read validated destination publications.

The resident does not spawn, supervise, restart, or depend on them.

Consumers start, stop, fail, and recover independently.

They do not acquire the resident's exclusive ownership lock or modify authoritative operational state, prepared-image artifacts, or publication directories.

Use existing operating-system service-management facilities where appropriate, including systemd on supported Linux deployments.

Windows development and hardware-independent tests must not require systemd or Linux-specific filesystem behavior.

Do not introduce a custom service manager, service-registration framework, mandatory cloud service, additional Python distribution, or network IPC mechanism merely to support consumers.

### Image-server consumer

The independently supervised `refrain-image-server` is specified in [Image Server](75-IMAGE_SERVER.md). It follows the consumer validation and service boundaries established in this specification.

### Consumer service boundaries

Every consumer selects the configured destinations it reads and validates their completed datasets independently.

Consumers may share one publication directory as read-only clients without coordinating through the resident backend.

A consumer may invoke the installed `refrain-viewer` for explicitly supported publication reconstruction, provided that operation remains read-only and respects published destination metadata.

Consumer failure and recovery must not block normal Refrain selection, scheduling, preparation, or publication.

Do not add consumer-specific publication formats when the established manifest and completed metadata contracts are sufficient.

Automated tests must cover independent consumer lifecycle, read-only filesystem access, concurrent consumers, resident independence, and safe recovery after missing or invalid current datasets.

## Consumer integrations and trust boundaries

The optional `refrain-web-companion` is deferred to a later release.

A future implementation may consume completed publication metadata and reconstruct literary presentations at browser-appropriate geometry using the installed viewer or shared rendering facilities.

It must not own daily quotation selection or require browser and physical-display clients to consume identical raster images.

Public presentation must not expose privileged resident control interfaces.

The architecture distinguishes publicly consumable presentation information from privileged local operational control.

A future public deployment may run outside the trusted local network.

Its publication mechanism, access controls, and trust boundaries must be specified before implementation.

An outbound-only publication path is preferred where it satisfies demonstrated requirements.

Consumer access to a publication directory does not confer permission to access other destination directories, operational state, credentials, or private content.

Destination audience filtering restricts which action declarations enter a completed scheduled publication. It is not a substitute for filesystem access controls or consumer authorization.

External HTTP consumers must not interpret publication metadata as authority to execute actions or invoke privileged commands.

Public presentation must not introduce mandatory network, cloud, or web-service dependencies into ordinary Refrain operation.

## External action publication

Actions are captured as opaque semantic declarations with the committed selected quotation.

Completed scheduled publication includes only actions eligible for the destination's explicitly configured audience, within the established completed-publication limits.

Completed transient publications contain no actions.

Publication and consumer infrastructure must not implicitly execute an action merely because its declaration appears in completed metadata.

Additional external action integrations are deferred.

Future consumers may interpret supported actions only through separately specified, explicitly configured behavior and appropriate trust boundaries.

Privileged operations must not become available to anonymous or public viewers merely because associated literary content is publicly visible.

Do not add new action execution interfaces, implicit privileges, cloud dependencies, or public control channels as part of the filesystem-publication implementation.