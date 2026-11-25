# Selection and Persistence

## Authoritative and derived state

Refrain maintains three distinct persistent records within the effective `storage.state` directory, as defined by [Storage](../schemas/CONFIGURATION.md#storage).

Authoritative operational state (`state.json`) owns:

- the current committed daily selection and its monotonically increasing revision;
- the immutable selected literary content, captured content preferences, and ordered action declarations;
- the effective reveal schedule, frozen resolved reveal-stage sequence, and scheduling context required for recovery;
- active repetition history;
- the highest reveal stage reached for the committed selection.

Its serialized format is defined in [Operational State and Global History](../schemas/STATE.md).

Operational state is authoritative for selection identity, scheduling, repetition history, and reveal progression. It must not depend on global history, publication checkpoints, or prepared images to establish the current selection or its revision.

The publication checkpoint (`publication.json`) is a single evolving record associated with the current committed selection revision. It has two successive complete forms, defined by [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes):

- A content checkpoint containing the committed literary content, effective reveal schedule, current visibility, complete ordered action declarations, and resolved audience-specific QR payloads.
- A content-and-presentation checkpoint additionally containing the resolved destination-independent artistic choices.

Resolved QR payloads belong exclusively to the publication checkpoint. They are not stored in authoritative operational state or global history.

The completed presentation checkpoint is the sole durable authority for those resolved artistic choices. They must not be duplicated in operational state. A valid checkpoint associated with the current selection preserves those choices across restarts, changes to resource pools or configuration, and preparation for different destinations.

Operational state remains authoritative when the publication checkpoint is missing, invalid, or associated with another selection. Checkpoint loss must not invalidate or replace the committed quotation, change repetition history or selection revision, or regress reveal progress. Lost artistic choices may be resolved again with an actionable warning.

The checkpoint's reveal visibility must reflect committed operational reveal progress. Reveal advancement is committed to operational state before checkpoint visibility is updated. Recovery must reconcile stale checkpoint visibility from operational state without discarding otherwise valid resolved artistic choices.

Destination-specific preparation derives effective presentation values from the shared checkpoint and applicable destination overrides and output requirements. Destination processing uses independent copies and must not modify the shared checkpoint. Completed publication metadata records the visibility and effective presentation applicable to its publication event.

Global history (`global-history.jsonl`) records committed selection events chronologically on a best-effort basis. It is not authoritative for operational behavior, and its completeness or availability must not affect selection recovery or revision assignment.

Prepared images are disposable cache entries derived from the committed selection, its reveal stages, output specifications, and compatible effective presentation requirements. Complete valid cached images remain reusable without reevaluating configuration or asset changes. Unusable sets are regenerated from the committed selection, available persisted artistic choices, and current applicable preparation inputs. Pixel-identical regeneration is not required.

Within a committed selection, the currently required reveal stage is the later of the stage required by the frozen resolved reveal-stage sequence and current time, or the highest stage already reached. Reveal progression must not move backward and must survive restarts while the committed selection's display date matches the current logical display date.

Persistent storage uses ordinary local filesystem facilities. Its representation must remain simple, inspectable, and recoverable after unexpected termination. No database service is required.

## Eligibility and specificity

The content-selection system determines which quotations are eligible for the display date associated with a new selection.

Eligibility rules belong to content entries and are inherited by every quotation within those entries.

The supported eligibility rules are:

- ordinary quotations eligible on any display date;
- quotations matching a particular month;
- quotations matching a particular day of the month;
- quotations matching a particular month and day;
- quotations matching a particular year, month, and day.

An entry may declare multiple eligibility rules.

An entry matches the highest specificity of any of its rules satisfied by the current display date.

Quotations intended only for special occasions do not automatically participate in ordinary selection.

An entry may participate in ordinary and special-date selection only when its eligibility explicitly permits both.

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

Selection is not complete until operational-state commitment succeeds. Subsequent publication checkpoint writes and destination preparation follow [Selection commitment](#selection-commitment) and do not constitute additional selection events.

An unavailable or empty effective content library cannot produce a new selection and must not trigger repetition-history cleanup.

A failed operational-state commitment leaves the proposed selection incomplete. When the outcome of a commitment is uncertain, recover authoritative operational state before attempting another commitment. An already committed selection event must not be committed again.

The next selection revision is derived from authoritative operational state, never from global-history contents.

Destination-independent artistic choices are resolved after selection commitment and before destination-specific preparation, not during quotation selection.

Selection policy must not depend on file enumeration order or incidental filesystem behavior.

## Selection commitment

A new daily selection becomes authoritative only after its complete daily selection record, updated repetition history, next selection revision, initial reveal progress, and required scheduling context have been durably committed as one consistent operational-state revision in `state.json`.

Selection commitment does not require visual-resource resolution, image preparation, destination publication, or global-history recording.

After successful operational-state commitment, Refrain persists the publication checkpoint in the following order:

1. Construct the content checkpoint from the committed operational selection, including the selected literary content, effective reveal schedule, current reveal visibility, complete ordered action declarations, and QR payloads resolved from the accepted content entry and effective configuration. Atomically write this checkpoint to `publication.json`.
2. Resolve destination-independent artistic choices using the committed selection's captured presentation preferences and applicable configuration and resources. Atomically replace `publication.json` with the complete content-and-presentation checkpoint.
3. Begin destination-specific preparation using independent copies of the completed checkpoint.

Each checkpoint must conform to its corresponding complete form in [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes). Both checkpoint forms are associated with the committed selection revision. A checkpoint belonging to another selection must not influence the current committed selection.

The content and presentation checkpoints are successive states of one file, not separate persistent records. Resolved artistic choices must not be attached to operational state. Checkpoint writes must not increment the selection revision, modify repetition history, replace committed literary content, or reset reveal progress.

Operational-state commitment precedes every checkpoint write for a new selection. No cross-file atomic transaction is required. A failed or interrupted checkpoint write does not invalidate the committed selection or authorize reselection. Recovery resumes checkpoint construction or presentation resolution as required by the last valid state and checkpoint.

An interrupted operational-state commitment must recover to either the preceding valid selection or the newly committed selection. A failure before successful commitment leaves the proposed selection incomplete. Once commitment succeeds, subsequent checkpoint, preparation, display, or history failures must not invalidate that selection or cause the same selection event to be committed again.

Global-history recording is best-effort and independent of operational-state and publication-checkpoint persistence. Its failure must not prevent checkpoint completion or ordinary presentation.

Atomic replacement mechanics, revision checks, ambiguous write outcomes, and checkpoint recovery are specified under [Selection revisions and atomic writes](#selection-revisions-and-atomic-writes) and [Recovery and state compatibility](#recovery-and-state-compatibility).

## Committed selection snapshot

The committed daily selection record preserves:

- the selected entry identity and normalized quotation identity;
- the selected quotation's complete original text;
- optional source and attribution;
- the associated logical display date;
- the effective reveal schedule;
- the selected entry's content properties and presentation preferences required to interpret or present the quotation;
- the selected entry's complete ordered action declarations.

At selection commitment, resolve the effective reveal schedule into the complete ordered sequence of absolute UTC reveal instants and associated cumulative field visibility. Persist this sequence as immutable committed selection data alongside the effective authored reveal schedule.

The serialized operational-state fields, validation constraints, and frozen reveal-stage representation are defined in [Operational State and Global History](../schemas/STATE.md).

The record contains only the selected quotation, not other quotations from its containing entry. Actions are preserved as opaque semantic declarations, including their type, declared audiences, and payload. They are not rendering inputs.

Operational state additionally preserves the selection revision, active repetition history, highest reached reveal stage, and scheduling context required for recovery.

Selection commitment captures the selected content and its effective schedule independently of visual-resource resolution. Once committed, the selected content, identities, preferences, actions, and effective reveal schedule remain unchanged for that selection. Subsequent edits, removal, or invalidation of the original content entry must not alter the committed record or prevent its recovery.

The committed record retains the authored presentation preferences needed to resolve artistic choices if the publication checkpoint is lost. Resolved artistic choices belong exclusively to the content-and-presentation checkpoint in `publication.json`, not to operational state. They are resolved after selection commitment and must not change the committed literary content, selection revision, repetition history, scheduling context, or reveal progress.

At selection commitment, preserve the accepted `text_color` and `decoration_color` candidates in their original order, including duplicates. A preference with no candidates remaining after content validation is represented as `null` in the committed snapshot, as is an omitted preference. Syntactically valid candidates must not be discarded solely because they are currently unavailable. Resource availability is resolved during preparation.

Neither operational state nor the shared publication checkpoint stores destination-specific overrides, completed publication events, or raster-dependent rendering plans. Output dimensions, presentation-canvas geometry, fitted literary rectangles, QR placement and module sizes, layer transformations, and other raster-dependent results are derived during destination preparation.

Only the current operational-state schema defined in [Operational State and Global History](../schemas/STATE.md) is supported. Its `format_version` remains `1`. The complete committed snapshot requires `actions` and `resolved_reveal_stages`. Older development-state representations are unsupported, even when they carry the same format-version value. Do not introduce migration readers, fallback reconstruction, or compatibility exceptions for incomplete earlier snapshots.

## Selection revisions and atomic writes

Selection revisions increase monotonically. Derive each new revision from authoritative operational state, never from global history or publication checkpoints. The initial selection uses revision 1; each subsequent new selection uses `current_revision + 1`. Display dates may repeat or move backward after clock adjustments and are not revision keys.

Each `SelectionProposal` carries the base state revision supplied to `select_quotation`. The caller obtains that revision and repetition history from the same recovered operational state.

A selection commitment is accepted only when its base revision matches the current operational revision, except for an exact idempotent retry of an already committed selection event.

An idempotent retry must match the committed selection revision, display date, complete immutable daily selection record, and resulting repetition history. Equality includes the selected occurrence's captured semantic properties and actions, not merely its normalized quotation identity. Subsequent reveal progression and publication checkpoint contents do not participate in this comparison. An idempotent retry does not rewrite operational state or change the committed selection.

The store assumes one writer at a time. Revision checks reject stale proposals and reveal-progress updates but do not provide cross-process compare-and-swap semantics. Callers must serialize writes sharing the same effective state directory. Resident process exclusivity is defined under [runtime ownership](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#resident-ownership-and-authenticated-control). No general transaction framework or additional state-store locking mechanism is required.

Operational-state updates and publication-checkpoint updates use independent atomic file replacements. For each update:

1. Construct and validate the complete replacement document.
2. Write it to a unique temporary file in the target file's directory.
3. Flush and synchronize the temporary file's contents.
4. Atomically replace the target using `os.replace`.
5. Synchronize applicable parent-directory metadata on POSIX where supported.

Temporary and final files must reside on the same filesystem. Temporary files are not recovery candidates. An interruption before replacement leaves the preceding complete document authoritative; an interruption after replacement requires examination of the current document to establish the committed outcome.

The standard-library implementation does not synchronize directory metadata on Windows, so directory-entry durability after sudden power loss is weaker there. If directory synchronization fails after replacement, report that replacement occurred and reload the authoritative document before deciding whether a retry is appropriate. Do not classify an uncertain post-replacement outcome as an unsuccessful pre-replacement write.

Each new selection is committed to `state.json` before either publication checkpoint is written. The content-only and content-and-presentation checkpoints are successive independent replacements of `publication.json`. Before accepting a checkpoint for the current selection, validate its schema form, selection revision, display date, and captured literary content against authoritative operational state. The checkpoint must not establish or replace a committed selection.

`PersistentStateStore.advance_reveal_progress(expected_revision, stage)` requires the current committed selection revision and a nonnegative integer stage ordinal within the committed selection's valid reveal-stage sequence. Boolean values and stage ordinals beyond the final stage are invalid. Validate the requested stage before writing either persistent document.

Missing operational state, stale revisions, and invalid stage values must be rejected without modifying persistent state. Report an invalid requested reveal stage with an actionable warning and continue normal resident operation.

A successful reveal advancement atomically replaces `state.json`, changing only `highest_reveal_stage`. The committed selection record, selection revision, and repetition history remain unchanged. Requests for the current or an earlier stage do not advance progress or rewrite operational state.

After a successful reveal advancement, synchronize `publication.json` visibility with the committed operational reveal stage. Preserve any valid resolved presentation choices and all other checkpoint content. If synchronization fails or is interrupted, operational reveal progress remains authoritative; recovery must reconcile the checkpoint without regressing the committed stage.

Checkpoint writes and reveal advancement must not create new selection events or global-history records. No cross-file transaction is required.

Automated tests must cover:

- revision assignment, stale-proposal rejection, and exact idempotent selection retries;
- atomic operational-state and checkpoint replacement, including interruptions before and after replacement;
- recovery of ambiguous write outcomes using newly initialized application instances;
- rejection of partial, invalid, or incorrectly associated checkpoints;
- valid, repeated, stale, and out-of-range reveal-stage updates;
- state-first reveal progression and recovery of stale checkpoint visibility without loss of valid artistic choices;
- preservation of committed selection and repetition history across checkpoint failures.

## Recovery and state compatibility

On startup, Refrain must recover and validate authoritative operational state before examining the publication checkpoint or prepared images.

A missing `state.json` represents an uninitialized installation.

An operational-state document with an invalid document envelope, unsupported format version, failed integrity check, invalid selection revision, or invalid repetition history cannot be recovered. Report an actionable error, preserve the existing file, and terminate resident operation.

When the document envelope, format version, integrity check, selection revision, and repetition history are valid, but the committed selection snapshot or persisted reveal progression is invalid, recover the selection revision and repetition history independently of the invalid selection. Report an actionable error identifying the invalid selection and attempt a new selection for the current logical display date using the recovered revision and repetition history.

The replacement selection follows ordinary selection and commitment rules, increments the recovered selection revision, and establishes a new committed snapshot, reveal progression, publication checkpoint, and global-history event. Do not modify the existing operational-state document until the complete replacement state can be successfully committed.

Do not use the invalid selection, its publication checkpoint, or its prepared images for scheduled presentation. Existing completed filesystem publication datasets remain unaffected until replaced through ordinary publication.

If replacement selection is unsuccessful, retain the existing operational-state document and follow the ordinary unavailable-library or no-eligible-content behavior for an initialized installation.

The publication checkpoint, global history, and prepared images must not be used to reconstruct authoritative operational state.

Before committing an initial revision 1 when `state.json` is missing, remove any surviving `publication.json` checkpoint and invalidate the installation's existing prepared-image sets. Complete this invalidation before committing the new operational state. If invalidation fails, report an actionable diagnostic and do not commit the new selection.

Completed filesystem publication datasets are unaffected. Once the new selection is committed, checkpoint construction and prepared-image generation follow their normal rules.

An interrupted operational-state commitment must recover to the last valid committed state. If the proposed selection was not committed, normal selection may proceed when required. If commitment succeeded, recovery must retain that selection without repeating its commitment, altering repetition history, or creating another selection event.

A valid committed daily selection remains authoritative independently of the original content library. Removing, renaming, modifying, or invalidating the original YAML entry must not change the selected quotation, captured preferences, actions, or effective reveal schedule.

After recovering valid operational state, Refrain must validate the publication checkpoint against the current committed selection. Validation includes the permitted checkpoint form, selection revision, display date, and consistency of captured literary content, effective reveal schedule, and actions. Checkpoint structure and field constraints are defined by [Publication metadata](../schemas/PUBLICATION.md#metadata-document-shapes).

Recovery follows these rules:

- **Valid content-and-presentation checkpoint:** Reuse its resolved artistic choices without reselection. Changes to current configuration, resource pools, or destination overrides do not invalidate those choices.
- **Valid content-only checkpoint:** Preserve its resolved QR declarations, resume destination-independent artistic resolution from the committed content and captured preferences, then atomically persist the completed presentation checkpoint before destination preparation.
- **Missing, corrupt, stale, or otherwise unusable checkpoint:** Reconstruct the content checkpoint from authoritative operational state with `content.qr: []` and emit an actionable warning that the original QR payloads could not be recovered. Do not recover QR payloads from current configuration, the original content entry, completed publications, global history, or prepared images. Resolve destination-independent artistic choices again and persist the completed presentation checkpoint. When previously resolved artistic choices cannot be recovered, warn that the resulting appearance may differ.
- **Checkpoint visibility inconsistent with operational reveal progress:** Reconcile `content.reveal_stage` from authoritative operational state. Preserve otherwise valid checkpoint content and resolved artistic choices. Do not reduce committed reveal progress or retrospectively alter completed publication metadata.

A valid matching checkpoint preserves its QR declarations across restart and subsequent content-entry or configuration changes. Reconstructed QR absence remains effective until a new selection is committed. Checkpoint recovery must not reuse prepared images incompatible with the recovered QR content.

A checkpoint associated with another selection revision must never override the current committed selection. An invalid checkpoint must not be treated as a valid source of artistic choices or partially repaired by accepting unvalidated presentation data.

Publication checkpoint recovery must preserve the committed selection revision, repetition history, selected literary content, effective reveal schedule, frozen resolved reveal-stage sequence, and highest committed reveal stage. Reconstructing or completing publication checkpoints must not modify those authoritative values.

Checkpoint recovery uses the same state-first ordering and atomic replacement requirements as ordinary processing. Destination-specific preparation must not proceed from newly resolved artistic choices until the completed checkpoint has been durably persisted. A checkpoint persistence failure leaves operational state authoritative and must be reported without triggering literary reselection.

During continuous operation, automatic retry of failed publication checkpoint persistence is permitted but not required. Retry timing and backoff are implementation decisions.

Prepared-image recovery uses the valid completed presentation checkpoint and current applicable destination overrides, output specifications, configuration, and available resources. Missing, damaged, incompatible, or incomplete prepared-image sets are regenerated as complete compatible sets. Healthy compatible cached sets remain reusable. Existing resource fallback and diagnostic policies apply without changing the checkpoint's persisted artistic choices.

If operational state cannot be recovered, report an actionable diagnostic identifying the effective `state.json` path. For a platform-standard state directory, the diagnostic may direct the operator to stop Refrain and run `refrain --reset`. For a configured state directory outside the standard location, direct the operator to stop Refrain and manually back up and quarantine or remove only the affected `state.json` file. Standard-path reset does not manage custom state directories.

Missing, damaged, or inaccessible global history must not prevent operational recovery. Global history must not determine selection revisions, repetition eligibility, or reveal progress.

When recovery cannot safely complete, preserve the existing physical e-paper image rather than replacing it with an unverified presentation.

Automated tests must cover:

- replacement selection following an integrity-valid but invalid committed snapshot or persisted reveal progression, retaining repetition history and incrementing the recovered selection revision;
- rejection of partial operational-state recovery when document integrity, format version, selection revision, or repetition history is invalid;
- preservation of the existing operational-state document when replacement selection is unsuccessful;
- rejection of invalid requested reveal stages without persistent modification or interruption of normal resident operation.
- recovery of a valid committed selection independently of the original content library;
- interrupted operational-state commits and ambiguous replacement outcomes;
- missing-state initialization with an orphan checkpoint whose selection fields match revision 1 but whose QR payloads differ, including restart immediately after commitment without reusing the orphan checkpoint or old prepared images;
- failure to invalidate the orphan checkpoint or prepared images preventing initial commitment;
- recovery from valid content-only and complete presentation checkpoints;
- preservation of resolved QR payloads across restart and content-entry or configuration changes;
- recovery of missing or invalid checkpoints with empty QR declarations, actionable warnings, and rejection of incompatible cached images;
- preservation of resolved artistic choices across restart, resource-pool changes, and destination override changes;
- recovery from missing, corrupt, stale, and mismatched checkpoints without literary reselection or reveal regression;
- actionable warnings and artistic re-resolution when the completed presentation checkpoint is lost;
- checkpoint visibility reconciliation without loss of valid artistic choices;
- failure to persist a recovered checkpoint;
- prepared-image loss, corruption, and regeneration using compatible persisted presentation choices;
- rejection of unrecoverable operational state without modifying it, including correct standard and custom path diagnostics;
- current-schema state round trips, rejection of missing actions or resolved reveal stages, and rejection of invalid persisted actions;
- recovery using newly initialized application instances after controlled interruptions at meaningful persistence boundaries.

## Global history and retention

Global history is a best-effort chronological record of committed quotation-selection events, independent of authoritative operational state and the publication checkpoint.

The active history file is `global-history.jsonl`, located directly within the effective `storage.state` directory. Rotated history segments use the same directory.

Each committed selection event is eligible for one history record containing exactly:

- the committed selection revision;
- the logical display date;
- the UTC timestamp of the selection event;
- the selected quotation's complete original text, under the field name `quotation`;
- the selected quotation's complete committed source, or null when absent;
- the selected quotation's complete committed attribution, or null when absent.

The exact serialized field names, types, and validation constraints are defined in [Operational State and Global History](../schemas/STATE.md). Global history does not store normalized quotation identities.

Global history records selection events rather than unique display dates. Multiple committed selections for the same logical display date remain distinct events, including selections following clock adjustments.

Records use compact UTF-8 JSON Lines (JSONL), with one complete JSON object per line terminated by a newline. Records must not contain embedded font files or rendered images.

Append history only after successful operational-state selection commitment. Reveal advancement, checkpoint updates, display refreshes, and transient publications must not create history records.

Recording is best-effort. Failure to open, append, flush, repair, rotate, or retain history must produce a diagnostic without invalidating a committed selection, preventing preparation, or stopping ordinary presentation.

Global history is not an authority for current selection identity, repetition eligibility, scheduling, reveal progression, or selection revision assignment. History records are not modified or removed when repetition pools reset. Missing or damaged history must not prevent operational recovery.

### Rotation and retention

History retention uses fixed size-based rotation with the following limits:

- Maximum segment size: 1 MiB (1,048,576 bytes).
- Maximum retained storage: 20 MiB, consisting of one active segment and up to 19 rotated segments.

The active segment contains the newest records. Rotated segments retain older records in chronological order. Remove the oldest retained segments as necessary to maintain the retention allowance.

Rotation occurs only between complete records. Before appending a record that would exceed the active segment limit, rotate the active segment.

A single record exceeding the segment limit must not be recorded and must produce a diagnostic without affecting operational state.

Rotation and retention must not modify authoritative operational state, publication checkpoints, or prepared images.

### Interrupted append recovery

Before appending or rotating an existing active history file, inspect its trailing JSONL record.

If an interrupted append left an incomplete trailing record, truncate only the incomplete tail to the last complete record boundary and emit a warning. Preserve all preceding complete records.

A complete, syntactically valid UTF-8 JSON object lacking its terminating newline must be preserved; restore the record delimiter before appending another event. Tail recovery does not validate historical record fields or types against the current global-history schema.

Do not interpret an incomplete trailing record as a committed history event. Do not silently discard complete records or attempt to reconstruct missing history from operational state.

Tail recovery applies to the active history segment. It does not authorize rewriting arbitrary invalid records or repairing historical rotated segments.

### Consistency and concurrency

Global-history persistence does not participate in the atomic operational-state or publication-checkpoint transactions. An interrupted write may leave a committed selection without a corresponding history record.

Ordinary retries and restarts should avoid recording the same committed selection event repeatedly, but cross-file exactly-once recording is not required.

History storage assumes one writer at a time. Concurrent writers sharing the same state directory require external coordination.

Automated tests must cover:

- chronological recording of committed selection events, including repeated logical display dates;
- absence of history writes for reveal advancement, checkpoint updates, refreshes, and transient publications;
- size-based rotation, retention limits, and oversized records;
- recovery of incomplete active-file tails before append and rotation;
- preservation of complete records, including valid records missing a final newline;
- history write, repair, and rotation failures without affecting operational state or ordinary presentation;
- absence of transactional dependencies between global history and authoritative operational state.
