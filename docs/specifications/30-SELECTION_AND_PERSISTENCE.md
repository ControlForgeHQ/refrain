# Selection and Persistence

## Authoritative and derived state

Authoritative operational state owns:

- the current committed selection and its monotonically increasing revision;
- active repetition history;
- the immutable daily selection record;
- monotonic reveal progress;
- scheduling context needed for recovery.

Global history owns chronological historical selection records but does not determine operational behavior.

Prepared images are disposable cache entries derived from the current daily selection, its reveal stages, the required output specifications and compatible preparation groups, and the configuration and resources available when the variants were prepared.

The appropriate reveal stage is initially determined by the committed schedule and current time.

Within a committed selection, reveal progress must not move backward.

The currently required stage is therefore the later of:

- the stage required by the current time;
- the highest stage already reached for the committed selection.

Reveal progression must survive application restarts while the committed selection's display date matches the current logical display date.

Prepared images are reused without checking for configuration or asset changes. If a set is unusable, regenerate it completely from current inputs; exact visual reproduction is not a requirement.

The future calendar archive is a separate historical presentation resource and is not authoritative for the active display.

Use ordinary local filesystem storage for Refrain's initial persistent data.

A database service is not required.

The storage representation should remain simple, inspectable, and suitable for recovery after unexpected termination.

Authoritative operational state, global selection history, and prepared images have separate storage responsibilities.

Operational state must not depend on reading global-history records or prepared-image files to determine the current selection revision.

The architectural commitment and recovery requirements determine the storage design.

## Eligibility and specificity

The content-selection system determines which quotations are eligible for the display date associated with a new selection.

Eligibility rules belong to content entries and are inherited by every quotation within those entries.

The initial scheduling model supports:

- ordinary quotations eligible on any display date;
- quotations matching a particular month;
- quotations matching a particular day of the month;
- quotations matching a particular month and day;
- quotations matching a particular year, month, and day.

An entry may declare multiple eligibility rules.

An entry matches the highest specificity of any of its rules satisfied by the current display date.

Quotations intended only for special occasions do not automatically participate in ordinary selection.

An entry may participate in ordinary and special-date selection only when its eligibility explicitly permits both.

Additional eligibility expressions may be introduced when required by an accepted feature.

Matching date-specific eligibility takes absolute precedence over less-specific eligibility.

The supported specificity order, from highest to lowest, is:

1. Year-month-day (`Y-M-D`)
2. Month-day (`M-D`)
3. Day (`D`)
4. Month (`M`)
5. Ordinary eligibility

Only quotations belonging to the highest specificity available for the current display date participate in that selection.

For example, on October 17:

- a quotation matching October 17 of the current year outranks an annually recurring October 17 quotation;
- an October 17 quotation outranks a quotation matching the 17th of any month;
- a day-of-month quotation outranks one matching any day in October;
- all matching special-date quotations outrank ordinary quotations.

Date specificity determines the winning candidate pool and takes absolute precedence over repetition status and priority. Evaluate priority only after date specificity and repetition eligibility; priority cannot override date specificity.

Lower-specificity quotations must not be considered merely because every quotation in a higher-specificity pool has previously appeared.

If a single quotation is assigned to October 17, it remains the selection for that date every year unless a more-specific matching quotation overrides it.

A year-month-day quotation is eligible only on its specified date unless another eligibility rule explicitly applies.

Automated testing should cover:

- date-specificity precedence;

## Candidate identity and priority

Every quotation within an eligible content entry contributes an individual selection candidate.

Each candidate inherits its containing entry's:

- priority;
- eligibility;
- source and attribution metadata;
- reveal configuration;
- other applicable presentation configuration.

Entries containing multiple quotations therefore contribute multiple candidates.

Selection is performed among quotations, not among content entries.

The number of content entries must not independently influence selection probability.

Among unused quotations within the winning pool, Refrain retains candidates having the highest numerical priority.

Lower-priority quotations remain eligible for subsequent selections while unused.

When multiple candidates remain tied for the highest priority, one is selected randomly.

An entry with negative priority remains eligible and may be selected once higher-priority unused alternatives have been exhausted.

When a pool resets, priority is evaluated again using the complete pool.

Equal-priority distinct quotation candidates must have equal selection probability. Duplicate occurrences must not distort that probability among distinct quotation messages.

Quotation identity depends only on normalized text.

Multiple candidate occurrences containing the same normalized quotation may have different inherited metadata.

Such occurrences share repetition-history identity.

When multiple occurrences of the same quotation remain eligible, the selected occurrence determines the metadata included in the daily selection record.

Refrain is not required to detect or resolve unintended duplicate content entries beyond applying the established selection and quotation-identity rules.

Priority determines preference among otherwise eligible unused quotations.

Automated testing should cover:

- priority selection;
- equal-probability random selection behavior where practical;

## Repetition cleanup and pool exhaustion

Refrain maintains one global repetition-history collection containing normalized quotation identities.

The collection records quotations consumed by committed selections during their active repetition cycles.

Repetition history is persistent but selectively resettable.

For each new selection, the application constructs a nonempty effective content library from successfully discovered sources and accepted entries.

Repetition identities no longer corresponding to any quotation in that effective library are removed from the proposed repetition history.

Repetition-history cleanup considers every accepted quotation, regardless of current date eligibility, specificity, priority, or font availability.

Rejected files and entries do not contribute identities to the effective library. Quotations represented exclusively by those rejected sources may therefore lose their recorded repetition status, even if the source entries are subsequently corrected.

Do not prune repetition history when content directories are missing or inaccessible, source discovery or enumeration fails, or the effective content library contains no valid quotations.

For each new selection, the application identifies the highest-specificity eligible quotation pool.

Within the highest-specificity winning pool, exclude quotation identities already in repetition history while unused candidates remain. Priority must not permit a consumed quotation to repeat while an unused candidate remains in that pool.

When every quotation in the winning pool has been consumed, the application removes the identities of all quotations in that pool from repetition history.

The application then reevaluates the same pool.

Exhausting a selection pool resets only the repetition identities belonging to that pool; it must not clear unrelated quotation identities.

For example, exhausting the annual October 17 pool must not reset quotations belonging only to Christmas or the ordinary selection pool.

The applicable pool is determined dynamically from currently eligible quotations rather than from a permanently stored membership list.

Changes to content-library membership therefore affect subsequent selections without invalidating existing committed selections.

When a quotation participates in multiple eligibility contexts, resetting one pool may make that quotation eligible again in another context.

This is an accepted consequence of using one resettable repetition-history collection.

Repetition-history cleanup and pool resets do not modify previously recorded global-history events.

Repetition history is authoritative operational state and must not be reconstructed from global history, including after restart: reconstruction would reverse intentional pool resets and introduce a dependency on historical-log retention.

Persist cleaned repetition history only as part of the next successful new selection commitment. No separate startup write, maintenance operation or service, periodic background service, or periodic pruning task is required.

Repetition history contains normalized identities of quotations consumed within active selection cycles.

It is maintained in authoritative operational state and persists across application restarts.

Unlike global history, repetition history may have identities removed when the currently eligible highest-specificity pool becomes exhausted.

For a new selection, Refrain also removes identities no longer represented in the nonempty effective content library.

Repetition-history resets and cleanup do not alter previously recorded global selection history.

Repetition identities absent from a nonempty effective content library may be removed during a new selection, but failed source discovery or an empty effective library must never trigger repetition-history cleanup.

Before selecting a quotation, successfully discover and examine the content sources and construct a nonempty effective content library from accepted entries.

Derive the set of normalized quotation identities belonging to every accepted entry in the effective library.

Intersect the persisted repetition history with those identities.

Use the resulting collection for repetition-aware selection.

Individual invalid content files or entries do not prevent cleanup when the remaining effective library is usable.

Automated testing should cover:

- repetition-history cleanup using accepted content only;
- preservation of repetition history when content discovery fails or no valid quotations remain;
- pool exhaustion and selective reset;

## Selection procedure

For each new daily selection:

1. Determine the applicable display date.
2. Discover and examine the content sources, constructing a nonempty effective library from accepted entries.
3. Remove repetition identities no longer present in the effective content library.
4. Identify eligible content entries.
5. Expand eligible entries into individual quotation candidates.
6. Determine the highest matching date specificity.
7. Retain candidates matching that specificity.
8. Exclude quotation identities present in the cleaned repetition history.
9. If no unused quotations remain, remove the identities of the winning pool from repetition history and reevaluate that pool.
10. Retain candidates having the highest priority.
11. Randomly select one remaining distinct quotation identity.
12. Resolve the selected occurrence and its inherited metadata.
13. Preserve the selected occurrence's semantic metadata, effective reveal schedule, presentation style, declared content preferences, and complete ordered action sequence needed to interpret or present the quotation.
14. Prepare the daily selection record.
15. Atomically commit the daily selection record, updated repetition history, next selection revision, initial reveal progression, and required scheduling context as authoritative operational state.
16. Record the committed selection in global history on a best-effort basis.

Selection is not complete until operational-state commitment succeeds.

An unavailable or empty effective content library cannot produce a new selection and must not trigger repetition-history cleanup.

A failed or interrupted operational-state commitment permits the selection procedure to run again.

The next selection revision is derived from authoritative operational state, never from global-history contents.

Visual resources and rendering decisions are resolved during preparation, not selection commitment.

Selection policy must not depend on file enumeration order or incidental filesystem behavior.

## Selection commitment

Selection identifies the individual quotation to be displayed during the next presentation interval.

The selected quotation inherits the eligibility, priority, reveal configuration, presentation metadata, and declared actions of its containing content entry.

A new daily selection becomes authoritative only after its complete daily selection record, updated repetition history, next selection revision, initial reveal progress, and required scheduling context have been durably committed consistently as one operational-state revision with one logical commit point.

An interrupted or unsuccessful operational-state commitment leaves the proposed selection incomplete.

Once commitment succeeds, the selection remains authoritative independently of subsequent image preparation, display updates, or global-history recording.

Each committed selection is eligible for recording in global history. Global-history recording is best-effort and does not participate in the authoritative operational-state transaction.

After operational-state commitment, failure to prepare images, update the display, or append global history must not invalidate the committed selection, cause reselection, or commit the same selection event again.

Selection commitment establishes a new authoritative operational-state revision containing:

- the complete daily selection record;
- the updated repetition history;
- the identity and scheduling context of the committed selection;
- initial reveal progression.

These values form one consistent operational-state update.

An interrupted operational-state update must recover to either the preceding valid selection or the newly committed selection.

Global-history recording follows successful selection commitment but is not part of the authoritative operational-state transaction.

The persistence mechanism must provide reasonable protection against incomplete writes and interrupted replacement.

The exact storage formats, rotation mechanics, and persistence operations are documented under [Selection revisions and atomic writes](#selection-revisions-and-atomic-writes) and [Global history and retention](#global-history-and-retention).

Global-history recording is independent of that commit and must not be included in its transaction.

Construct a complete next operational state and publish it using atomic filesystem replacement.

Temporary and final state files must reside on a filesystem supporting the required replacement semantics.

Flush file contents before replacement and synchronize relevant directory metadata where supported.

A failure before publication leaves the previous operational state authoritative. A failure after publication may require reloading state to establish whether the new selection was committed.

Do not require a global-history append to succeed before recognizing a committed selection.

Resolve the canonical presentation only after the quotation selection is committed so visual-resource failure cannot prevent or repeat quotation selection. Attach the resolved canonical selections to that selection with the same complete-state atomic replacement mechanism. Publish them before preparing destination variants; a failed attachment leaves them unresolved, while a successful attachment is reused unchanged after restart. Attaching them does not advance the selection revision or alter repetition history or reveal progress.

## Committed selection snapshot

Refrain maintains sufficient durable operational state to preserve:

- the current committed daily selection and its monotonically increasing revision;
- the display date associated with that selection;
- the selected quotation's original text;
- the selected content identity, optional source and attribution, and content properties needed to interpret or present the quotation;
- the selected entry's complete ordered action sequence;
- the effective reveal schedule and scheduling context needed to resume it;
- the resolved canonical presentation for the committed daily selection, once it has been resolved;
- active repetition history;
- the highest reveal stage reached for the current selection;

Refrain separately maintains a chronological global history of selection events.

Operational state is authoritative for selection, scheduling, reveal progression, and recovery. Global history is historical information and is not required for normal operation.

The daily selection record contains a complete copy of the selected quotation and the semantic content properties needed to apply its reveal behavior without consulting the original content library. It also captures the selected entry's complete ordered action sequence as opaque semantic data and, once resolved, the canonical presentation.

It includes the selected entry identity and quotation identity, the selected quotation's original text, optional source and attribution, effective reveal schedule, display date, any selected content preferences needed to interpret or present the quotation, the entry's immutable ordered actions, and the canonical presentation's resolved stable selections. These captured values remain authoritative for this selection; later edits to the source entry do not replace them, and recovery never rereads that entry to obtain them. The record does not contain other quotations from the entry.

The record is not a serialized rendering plan. Actions are not rendering inputs. Persist the canonical stable selections, not destination-specific overrides or raster-dependent results. Do not store output dimensions, design-canvas geometry, resolved literary rectangles, QR placement or module size, layer transformation geometry, or other derived rendering values solely to reproduce previously generated pixels. Resolve and durably record the canonical presentation once for the selection before preparing destination variants. If that resolution or its persistence is interrupted, recovery may complete it; once recorded, it must not be independently reselected for a destination or after restart.

Only the current prerelease operational-state schema is supported. Do not maintain readers, migrations, rendering branches, or tests for earlier internal schemas. A numeric discriminator is not required unless technically necessary; if retained, its current prerelease value is `1`. Incompatible or invalid state must produce an actionable diagnostic reflecting the effective state-file location; it must not silently replace the selected content or modify the state file. For a platform-standard state path, the diagnostic may direct the operator to stop Refrain and run `refrain --reset`. For a configured state path outside the standard location, identify that path and direct the operator to stop Refrain and manually back up and remove or quarantine only that file; `--reset` does not manage custom paths.

Selection commitment does not depend on resolving visual resources.

Content-level presentation preferences remain part of the selected record when needed to preserve the selected entry's intended behavior. They are inputs to canonical resolution; the resolved canonical selections are persisted separately from destination-specific prepared artifacts.

The daily selection record is immutable after commitment except for monotonic reveal progress, scheduling context required by the display-day model, and the one-time attachment of its canonical presentation.

Prepared images are disposable derived artifacts. Regeneration preserves the selected content, canonical presentation, and reveal progression. Destination-specific effective presentations may reflect configured overrides; raster-dependent geometry is resolved for each output specification.

The daily selection record contains the selected entry identity, normalized quotation identity, original quotation text, optional source and attribution, effective reveal schedule, display date, any selected content-level properties or preferences needed to interpret or present the quotation, and—once resolved—the canonical presentation's stable artistic selections. These captured preferences and canonical selections are authoritative for the committed selection; preparation and recovery do not reread the source entry. Selection revision, repetition history, highest reveal stage, and scheduling context are held in authoritative operational state.

The record does not contain a destination-specific rendering plan. Persist canonical font bundle and role-face identifiers, palette identifiers, background and decoration selections or suppression, presentation style, and QR policy. Do not persist destination overrides, output dimensions, design-canvas and presentation-canvas sizes, effective inset rectangle or font bounds, palette RGB values, tinting decisions, QR placement or module size, layer transformations, or other destination- and raster-dependent parameters solely for pixel-identical recovery.

The selected quotation and captured content-level preferences remain available even when the source YAML entry is edited or unavailable. Editing that entry does not change the committed selection. If regeneration is needed, reuse the persisted canonical selections and apply current destination overrides and output specifications; do not make new canonical selections. Current assets or rendering behavior may affect usable output without altering the selected quotation, captured preferences, canonical presentation, or effective reveal schedule.

Preparation errors are reported without changing the committed selection, repetition history, or reveal progress.

A committed daily selection preserves the selected content, captured content-level preferences, effective reveal schedule, and once-resolved canonical presentation independently of subsequent content-library or configuration changes.

Preserve the selected content's presentation preferences in the daily selection record when needed to interpret or present the quotation. Those captured preferences are authoritative for the committed selection: do not reread the original content entry after commitment, and do not let later edits to it change the captured values.

The semantic committed selection, captured preferences, and persisted canonical presentation do not change when source content or configuration files are edited. If a valid prepared cache cannot be reused, reuse the canonical selections and apply current destination overrides, output specifications, and available assets during regeneration. Do not resolve the captured preferences or pools again for a committed selection. Derived destination geometry and rendering results are not frozen at commitment, so regenerated appearance may differ without changing canonical identity.

## Selection revisions and atomic writes

Selection revisions increase monotonically. Derive each new selection revision from the preceding authoritative operational-state revision, never from the number or contents of global-history records.

An interrupted operational-state commitment must not leave a partially committed selection or inconsistent repetition history. Do not treat a partially written or invalid daily selection record as a completed selection.

Each `SelectionProposal` carries the base state revision supplied to `select_quotation`.

The caller obtains the base revision and repetition history from the same recovered operational state.

A successful new selection uses `current_revision + 1`. The initial selection uses revision 1.

Display dates may repeat or move backward after clock adjustments and are not revision keys.

Commit accepts a proposal only when its base revision matches the current operational revision, except for an exact idempotent retry of an already published selection.

An idempotent retry preserves any subsequent reveal progression and does not commit another selection.

The store assumes one writer at a time. Revision checks reject stale proposals and reveal-progress updates but are not a cross-process compare-and-swap. Callers must serialize concurrent writes sharing the same state path.

No general state-store locking or transaction framework is required; resident process exclusivity is specified separately under [runtime ownership](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#resident-ownership-and-authenticated-control).

Selection commitment and reveal advancement use the same complete-state publication mechanism.

Write a unique temporary file in the state file's directory, flush and synchronize its contents, then publish it with `os.replace`.

On POSIX, synchronize applicable parent-directory metadata after replacement.

Temporary files are not recovery candidates.

The temporary and final files share a filesystem, and replacement is the single operational-state publication point.

The standard-library implementation does not synchronize directory metadata on Windows, so directory-entry durability across sudden power loss is weaker there.

If directory synchronization fails after replacement, the operation reports that publication occurred. Callers must reload authoritative state before deciding whether to retry.

The selection-state commit initializes reveal progress for a new selection independently of its predecessor.

`PersistentStateStore.advance_reveal_progress(expected_revision, stage)` requires the current committed revision and accepts nonnegative integer stage ordinals.

Missing state and stale revisions raise a state-commit error without publishing a change.

Reveal advancement replaces only `highest_reveal_stage`. It preserves the selected content record, repetition history, and selection revision.

Requests for the current or an earlier stage do not advance progress or rewrite the state document.

Publication failures retain the existing reporting distinction between failure before replacement and failure after publication.

Automated testing should cover:

- atomic selection commitment;

Test persistence failure at meaningful boundaries, including failures before and after commitment.

Verify that incomplete data cannot be mistaken for successfully committed state.

Where practical, test recovery using a newly initialized application instance rather than only inspecting the state of the instance that performed the write.

## Recovery and state compatibility

After commitment, the active selection must not require access to the original YAML entry. The content library does not override a valid committed daily selection record. Removing, renaming, modifying, or invalidating the original entry leaves that selection unchanged and does not prevent recovery when the committed record is valid.

On startup, Refrain first attempts to recover the committed operational selection.

If selection commitment was interrupted, Refrain must recover the last valid operational state and repeat selection when necessary.

If rendering or image persistence was interrupted after commitment, Refrain regenerates the complete stage set from the persisted canonical presentation using current destination overrides, output specifications, and available resources. Existing fallback and diagnostic policies apply to unavailable or invalid resources without reselecting canonical resources.

If canonical presentation resolution was interrupted before its selections were durably recorded, recovery may complete that resolution once for the committed daily selection. Once persisted, those canonical selections are authoritative across restarts and destination preparation; an override change does not cause them to be selected again.

If current operational state is incompatible, unavailable, or invalid, report an actionable diagnostic identifying the effective state-file location. For a platform-standard state path, the diagnostic may direct the operator to stop Refrain and run `refrain --reset`. For a configured path outside the standard location, direct the operator to stop Refrain and manually back up and remove or quarantine only that file; do not suggest `--reset` for a custom path. Do not modify the state or silently substitute another quotation. Valid current-format state remains recoverable.

Missing, damaged, or inaccessible global history must not prevent operational recovery.

The existing physical e-paper image should be preserved when recovery cannot safely complete.

Persistent operational state must be validated when loaded. Incomplete, invalid, or integrity-check-failing state must not be silently accepted. An interrupted state publication must not produce a partially committed selection or inconsistent repetition history. A failure after selection commitment must preserve the committed quotation. Global-history failures must not prevent operational recovery, and global history must not be used to reconstruct repetition state or determine the next revision.

Only the current prerelease operational-state schema is supported. Do not add schema migrations, legacy readers, normalization paths, rendering branches, or tests for earlier internal state formats. A numeric discriminator is unnecessary unless required by the implementation; if one is retained, the sole current prerelease value is `1`. The snapshot's `actions` field is optional when reading this same version-1 schema so valid pre-action snapshots recover with an empty action sequence; newly written snapshots include the field. If present, persisted actions must be validated strictly, and invalid action data must follow ordinary persistent-state recovery errors rather than content-loader warning-and-drop behavior. Incompatible or invalid state must produce an actionable diagnostic reflecting the effective state-file location, without silently replacing selected content or modifying the file. For the platform-standard per-user state path, the diagnostic may direct the operator to stop Refrain and run `refrain --reset`. For a state path configured outside that standard location, it must identify the path and direct the operator to stop Refrain, back up the file, and manually quarantine or remove only that file; `--reset` does not manage custom paths.

The current state must preserve the selected entry and quotation identities, original quotation text, optional source and attribution, content properties needed to interpret or present the selected quotation, the complete ordered action sequence, effective reveal schedule, display-day and scheduling context, selection revision, repetition history, and highest reached reveal stage. Once resolved, it must also preserve the canonical presentation's stable selections: presentation style, selected background and decoration identifiers or suppression, selected font bundle and role-specific face identifiers, resolved palette identifiers, and canonical QR policy. Attach and persist these canonical selections once for the committed daily selection, independently of destination-specific prepared artifacts. Preserve each action's type, declared audiences, and payload without consumer-specific interpretation. Do not persist destination override requests, destination-specific effective geometry, QR placement or module size, output dimensions, or layer transformation plans solely to reproduce pixels. Canonical presentation persistence must not change the committed quotation, selection revision, repetition history, or reveal progression.

Recovery behavior must be covered by automated tests using controlled failures at meaningful publication boundaries. Verify canonical selections are attached atomically, survive restart, and are reused unchanged across destinations and override changes. A failure before canonical attachment may retry canonical resolution; a successful attachment must never be independently reselected. Valid current-format state must remain recoverable across restarts.

Global selection history is not included in the operational-state document. The configured state-file path must be absolute. A missing state file represents an uninitialized installation.

Automated testing should cover:

- recovery of valid current-format daily selections independently of current content-library availability;
- clear rejection of incompatible current state without modifying the state file; diagnostics for platform-standard paths may direct the operator to stop Refrain and run `refrain --reset`, while diagnostics for configured paths outside the standard location identify that path and require manual backup and quarantine/removal of only that file;
- current selection-record round trips containing selected content, effective schedule, day context, ordered actions, and required repetition/reveal state, without derived rendering decisions; recovery of valid version-1 snapshots with no actions field and rejection of invalid persisted action data;
- recovery of the selected quotation and monotonic reveal progress after image preparation or cache failure;
- no legacy development-schema readers, migrations, normalization, or historical-format recovery tests beyond the explicitly supported missing-actions field in version 1;
- recovery from interrupted writes;
- current daily-selection recovery;

## Global history and retention

Global history is a separate chronological record of committed quotation-selection events, independent of authoritative operational state.

Each record identifies the selection revision and logical display date and preserves:

- the selected quotation text;
- its normalized repetition identity;
- the time at which the selection was made.

Global history records selection events rather than unique display dates. Multiple selections associated with the same logical display date remain distinct records, including selections resulting from clock adjustments.

Global history is independent of the containing entry's identifier, source, attribution, priority, and eligibility rules for repetition purposes.

Global history is append-only during normal recording. Recorded events are not modified or removed when repetition pools are exhausted.

Global history has bounded retention. Its rotation mechanism and fixed retention limits are documented under [Global history and retention](#global-history-and-retention). Discarding older records does not affect operational state or future selection revisions.

Global-history recording is best-effort. Report a recording failure without invalidating the committed selection, preventing image preparation, or stopping ordinary presentation.

An interruption may result in a missing or incomplete historical record. Global-history completeness is not a prerequisite for application recovery.

Do not read global history to determine current selection state, quotation eligibility, repetition eligibility, scheduling, or the next selection revision.

Use append-only UTF-8 JSON Lines (JSONL), containing one complete JSON object per recorded selection event.

Each record includes:

- the committed selection revision;
- the logical display date;
- the UTC timestamp of the selection event;
- the selected quotation's original text;
- its normalized repetition identity;
- any non-rendering selection metadata required by the history contract.

Records must not contain embedded font files or rendered images.

Use compact JSON serialization, with each record terminated by a newline.

Global-history recording occurs only for committed selection events, not reveal updates or display refreshes.

Global-history retention is bounded and does not have operator-configurable limits in Version 0.1. Use size-based rotation with the following fixed limits:

The maximum segment size is 1 MiB (1,048,576 bytes).

The total retention allowance is 20 MiB, represented by one active segment and up to 19 rotated segments.

The active segment contains the newest records. Rotated segments retain older records in chronological order, with the oldest retained segment removed when necessary to maintain the fixed retention allowance.

Rotation occurs between complete records, never within a JSONL record.

Before appending a record that would exceed the 1 MiB active-segment limit, rotate the active segment.

A single record exceeding the segment limit cannot be recorded and must produce a diagnostic without affecting the committed selection.

Rotation must not modify authoritative operational state or reset selection revisions.

Global-history recording is best-effort.

Failure to open, append, flush, rotate, or retain a history segment must produce a diagnostic but must not invalidate a committed selection or prevent ordinary display operation.

An interrupted append may leave an incomplete trailing record. History-reading tools must distinguish such records from complete valid events without affecting application recovery.

The history format does not promise transactional consistency with operational state.

A missing historical record after an interruption is acceptable.

Normal operation should avoid recording the same committed selection repeatedly during ordinary retries or restarts, but no cross-file exactly-once transaction is required.

Global-history storage assumes one writer at a time. Concurrent writers sharing the same history directory require external coordination.

History rotation and retention apply only to global-history files. They do not delete the current prepared images or any future calendar presentation archive.

Automated testing should cover:

- global and repetition-history behavior;

## Calendar archive boundaries

A future calendar presentation archive may preserve the fully revealed presentation image and associated metadata for previously selected display dates.

Calendar history and global history serve different purposes.

Global history records every committed selection event in chronological order, including multiple selections for the same logical display date.

Calendar history provides at most one current archived presentation for each logical display date. When a later committed selection uses a previously recorded display date, that selection supersedes the earlier calendar presentation for that date.

A calendar presentation is associated with the revision that produced it.

The calendar archive is independent of active selection, repetition history, and global-history retention.

Its records need not contain embedded font resources or complete rendering snapshots when the final prepared image and relevant presentation metadata are retained.

Calendar archive publication, retrieval, storage, and retention are deferred until the corresponding interface capability is implemented.
