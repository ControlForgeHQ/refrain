# Architecture

Refrain is a self-contained, open-source e-paper presentation system for quotations and other short-form content.

The application selects an eligible quotation for each logical display day, progressively reveals information according to a configured schedule, and presents pre-rendered images on a physical e-paper display.

Refrain is intended primarily for personal and household use while remaining configurable and reusable by others.

This document defines the system architecture, component responsibilities, runtime behavior, persistent state, scheduling semantics, display behavior, and architectural boundaries.

Product scope and release sequencing belong in `docs/ROADMAP.md`.

Engineering standards, dependency selection, testing requirements, and implementation practices belong in `docs/ENGINEERING.md`.

The detailed YAML content schema and its validation rules belong in the content-format specification.

## Architectural principles

### Keep the core independent of presentation hardware

Content loading, eligibility evaluation, quotation selection, scheduling, and image composition must be executable without physical display hardware.

The e-paper display is an output device, not an authority over application state or content policy.

Hardware-specific code must not determine which quotation is selected or what information should be visible.

### Keep the runtime self-contained

Refrain operates as a single Python application with internally separated responsibilities.

Ordinary operation must not require:

- an internet connection;
- a cloud service;
- a database server;
- a web server;
- a message broker;
- an external content-management application.

Use existing Linux facilities for process management, logging, and timekeeping where appropriate.

Do not introduce additional long-running services or infrastructure without a demonstrated requirement.

### Separate content, selection, preparation, and presentation

Content entries organize quotations and their shared metadata.

Selection determines which quotation is assigned to a display day.

Commitment makes the selected quotation and its associated presentation information authoritative.

Preparation generates and persists all images required for the committed selection.

Scheduling determines which prepared image should currently be presented.

Display output communicates that image to physical hardware.

Each responsibility must remain independently understandable and testable.

### Preserve future flexibility without implementing future features

The initial architecture must not assume that content can only originate from song lyrics or that a physical display is the only possible presentation destination.

Future web presentation, public publishing, and external actions must be possible without replacing the core quotation-selection model.

These capabilities must not be implemented merely to demonstrate extensibility.

## Target platform

The initial deployment targets:

- Raspberry Pi OS Lite;
- Python;
- Waveshare 13.3-inch e-Paper HAT+ (E);
- Waveshare-native 1600 × 1200 landscape output.

The Raspberry Pi 3B+ is the minimum supported Raspberry Pi platform for Version 0.1 and the initial hardware-validation platform.

The application must not depend on performance, memory capacity, peripheral availability, or other characteristics exclusive to the Raspberry Pi 3 B+.

The display uses Spectra 6 color e-paper technology.

The intended presentation is predominantly black typography on a paper-white background. Color is available for restrained decorative use.

The initial display is a full-frame output device. Refrain must not depend on partial refresh, animation, or frequent screen updates.

The renderer must produce images independently of the display backend.

Hardware-independent content, selection, scheduling, persistence, and rendering components must remain portable across operating systems supported by the Python runtime and required dependencies, without unnecessary operating-system-specific assumptions. This permits their development and testing on non-Linux systems but does not imply that full application deployment has been validated or is supported there.

The display backend owns hardware-specific integration, including the Waveshare driver and its platform dependencies.

Support for additional display hardware is not an initial product requirement, although display resolution, supported color capabilities, and hardware-specific operations must remain isolated from core content and scheduling logic.

The runtime should avoid unnecessary memory use and background processing. Quality decisions for infrequent daily image preparation must not be rejected solely because they require additional processing.


## Terminology

**Content Entry:** A uniquely identified collection of one or more quotations and shared configuration metadata.

**Quotation:** An individual message contained within a content entry. Quotations are the units of daily selection and repetition tracking.

**Quotation Identity:** The normalized text of a quotation, used to determine whether the same message has previously been selected.

**Content Library:** The validated collection of available content entries.

**Display Day:** A logical presentation interval established by Refrain's configured local day-start boundary and ending at the next recognized display-day transition.

**Display Date:** The local calendar date associated with a daily selection. This date determines content eligibility.

**Date Specificity:** The degree to which an eligibility rule identifies a particular calendar date, ordered from most to least specific: year-month-day, month-day, day, month, and ordinary eligibility.

**Selection Pool:** The quotations eligible within the highest matching date-specificity context for a particular display date.

**Priority:** An optional signed integer associated with a content entry and inherited by its quotations. Higher values indicate greater selection preference. The default is zero.

**Selection Revision:** A monotonically increasing identifier assigned to each committed daily selection and maintained in authoritative operational state.

**Global History:** A chronological, retention-bounded record of committed quotation selection events, maintained independently of authoritative operational state.

**Repetition History:** A persistent but selectively resettable collection of quotation identities used to prevent repetition until an eligible selection pool is exhausted. Identities no longer present in the validated content library may also be removed.

**Daily Selection:** The individual quotation assigned to the current display day.

**Daily Snapshot:** A persistent copy of the selected quotation and committed presentation settings sufficient to prepare its presentation independently of the original content entry. Font, background, and decoration resources are resolved separately.

**Selection Commitment:** The successful durable recording of a daily snapshot, updated repetition history, selection revision, and associated operational context as one consistent authoritative state.

**Reveal Stage:** A cumulative set of content fields eligible for presentation at a particular point in the configured reveal schedule.

**Prepared Image:** A complete, persisted image representing one reveal stage of the committed daily selection.

**Presentation:** The selected quotation, associated metadata, reveal schedule, and applicable layout configuration used to produce prepared images.

**Renderer:** The hardware-independent component responsible for composing complete presentation images.

**Display Backend:** The component responsible for presenting prepared images through a configured output destination, including directly connected display hardware or a network-accessible image service.

**Persistent State:** The authoritative operational state containing the committed daily snapshot, selection revision, active repetition history, reveal progress, and scheduling context required for recovery across application restarts.



## High-level system structure

Refrain operates as a single Python application with four primary phases:

1. Selection
2. Commitment
3. Preparation
4. Presentation

The logical flow is:

```text
Content files
    |
    v
Content library
    |
    v
Eligible quotation candidates
    |
    v
Specificity, repetition, and priority
    |
    v
Quotation selection
    |
    v
Daily snapshot + updated repetition history
    |
    v
Atomic operational-state commitment
    |
    +----> Best-effort global-history recording
    |
    v
Presentation preparation
    |
    v
Persisted reveal-stage images
    |
    v
Display scheduler
    |
    v
Display backend
    |
    v
Physical e-paper display
```

The application controller coordinates these responsibilities within one process.

The flow describes responsibility and ownership, not a required class hierarchy, directory structure, or strict ordering between independent post-commit operations.

### Selection and commitment

Selection identifies the individual quotation to be displayed during the next presentation interval.

The selected quotation inherits the eligibility, priority, reveal configuration, and presentation metadata of its containing content entry.

A new selection becomes authoritative only when its complete daily snapshot, updated repetition history, selection revision, and required scheduling context have been durably committed as one consistent operational state.

An interrupted or unsuccessful operational-state commitment leaves the proposed selection incomplete.

Once commitment succeeds, the selection remains authoritative independently of subsequent image preparation, display updates, or global-history recording.

Each committed selection is eligible for recording in global history. Global-history recording is best-effort and does not participate in the authoritative operational-state transaction.

Failure to record global history must not cause a committed quotation to be selected or committed again.


### Preparation

Preparation generates the complete set of images required for the committed quotation's reveal stages.

Prepared images are persisted independently of the content library.

Preparation does not modify the committed selection or its selection histories.

### Presentation

The display scheduler determines which prepared image should currently be presented.

Normal scheduled reveals do not invoke the renderer or consult the content library.

The display backend owns physical display communication and recovery.

The committed daily snapshot remains authoritative when prepared images need to be recovered.

Time and configuration are inputs to the relevant responsibilities. Neither is an independent source of quotation-selection policy.

## Content model

### General-purpose content

Refrain must support quotations and short-form content without assuming that an entry represents a song.

An entry may refer to a song, book, film, person, event, personal message, or another source.

Source-specific behavior must not be embedded in the core quotation-selection model.

### Semantic fields

Entries use a defined set of semantic fields rather than arbitrary user-defined presentation fields.

The initial model distinguishes:

- a stable entry identifier;
- one or more quotations;
- optional source information;
- optional attribution information;
- an optional integer priority;
- eligibility and scheduling metadata;
- optional reveal-schedule overrides.

Each content entry must contain at least one valid quotation.

Source, attribution, priority, eligibility, and reveal configuration belong to the content entry and apply to every quotation it contains.

Individual quotations do not have independent configuration overrides.

A quotation requiring different treatment must be placed in a separate content entry.

Optional presentation fields may be omitted when they are not meaningful for an entry.

Priority defaults to zero when omitted.

Priority is a signed integer with no project-defined minimum or maximum. Higher numerical values indicate higher selection priority.

Priority influences selection only after date specificity and repetition eligibility have been evaluated.

The complete YAML field definitions, value formats, validation rules, and supported scheduling expressions will be established as part of the content-format specification.

Additional content metadata may be introduced when required by an accepted feature, without changing the meaning of existing fields.

### Entry identity

Every content entry has a stable identifier independent of its YAML filename or directory location.

Entry identifiers must be unique within the content library.

Renaming or moving an entry's file must not create a new logical entry.

Individual quotations do not require separately assigned identifiers.

Quotation identity is derived from normalized quotation text rather than from the containing entry's identifier, filename, source, or attribution.

Moving a quotation between entries or changing its associated metadata must not cause it to be treated as a previously unseen message when its normalized text is unchanged.

### Quotation identity

Quotation identity is determined by normalizing the quotation's text.

Normalization consists of:

- applying Unicode NFC normalization;
- replacing consecutive whitespace characters, including line breaks and tabs, with a single space;
- removing leading and trailing whitespace.

Capitalization, punctuation, spelling, and other non-whitespace characters remain significant.

The original quotation text, including its intended formatting, is preserved for presentation.

Normalization is used for identity comparison and history tracking, not for modifying displayed content.

Two quotations with identical normalized text represent the same message for repetition purposes, regardless of their containing entries or associated metadata.

The application is not required to perform fuzzy matching or detect semantically equivalent quotations with different wording.

Duplicate quotations across content entries are treated as a content-authoring concern rather than a separate architectural problem.

### Content storage

Content is initially maintained as YAML files, ordinarily with one entry per file.

Each entry may contain an arbitrary number of quotations.

Directory organization is an authoring convenience and must not determine an entry's identity or selection behavior.

The runtime loads content when a new daily selection is required.

Automatic filesystem watching, interactive editing, and immediate reloading in response to file changes are not required.

Changes to source content affect subsequent selections, not an already committed selection.

Once a daily selection has been committed, its presentation must not depend on continued access to the corresponding YAML entry.

A usable content library may contain rejected files or entries. Refrain must preserve valid content rather than require every discovered source to pass validation.

### Content validation

Content must be validated before it becomes available for selection.

Invalid content files and entries are excluded from the effective content library without invalidating unrelated valid content.

Validation must identify errors such as:

- malformed or unsupported YAML;
- missing required fields;
- empty quotation collections;
- empty or invalid quotation text;
- duplicate entry identifiers;
- unknown fields;
- invalid field values;
- invalid priority values;
- unsupported eligibility expressions;
- invalid reveal schedules.

Diagnostics must identify the affected entry or source file where possible.

A malformed YAML file is excluded in its entirety.

Invalid entries are excluded individually where their source representation permits independent validation.

Conflicting duplicate entry identifiers must not be resolved according to filesystem enumeration order.

The effective content library contains only accepted, validated entries.

A partially accepted library is usable when source discovery has completed successfully and at least one valid quotation remains.

Missing or inaccessible content directories, failed source discovery, and libraries containing no valid quotations cannot support a new selection.

These library-level failures must not trigger repetition-history cleanup.

Invalid content must not produce undefined selection or rendering behavior.

A malformed entry must not silently change the meaning of another entry.

Validation must not impose an arbitrary project-specific numerical limit on priority or the number of quotations in an entry.

Detailed content validation rules and diagnostic severity are defined in `docs/CONTENT_FORMAT.md`.

## Display-day model

### Local time

The host operating system is the sole authority for local timezone and daylight-saving rules. Refrain does not configure or persist a timezone identifier.

Display-day and reveal schedules use host-local civil time. Absolute event timestamps remain timezone-aware, and durations use monotonic elapsed time.

The application must not assume that every local calendar day contains exactly 24 elapsed hours.

An ambiguous scheduled wall time resolves to its first occurrence. A nonexistent scheduled wall time resolves to the first valid local instant after the gap. These rules apply to both reveal deadlines and display-day boundaries, including transitions whose offset changes are not whole hours.

Changing the host timezone is an operating-system operation. Refrain does not need to adapt its scheduling while running; restarting afterward is acceptable. If local-time rules change during observation, that change resets the boundary observer's baseline rather than creating a boundary. A timezone change alone does not invalidate a committed selection or reduce reveal progress.

Clock changes must be handled according to the established display-day transition and reveal-progression policies.

### Day-start configuration

The display day begins at a configured local time.

For example, with a configured start time of 06:00, a display day normally begins at 06:00 and remains active until the following configured day-start boundary.

The local calendar date associated with a new selection determines its special-date eligibility.

### Daily selection stability

A committed daily selection remains authoritative until Refrain recognizes the next display-day transition.

Application restarts, display failures, content-library changes, and missed reveal events must not independently trigger reselection.

The current system date being different from the committed display date does not, by itself, invalidate the selection.

The display date identifies the date for which the selection was made; it is not a condition that must continuously match the system clock.

### Forward clock adjustments

When the clock advances within the active display day, Refrain advances to the reveal stage appropriate to the new time.

Missed intermediate reveal stages are not presented sequentially.

When the clock advances past one or more display-day boundaries, Refrain selects a quotation for the display date appropriate to the new time.

Skipped display dates do not require retrospective selection or presentation.

For example, if the clock advances from October 17 to November 28, Refrain selects content for November 28 and presents the appropriate reveal stage.

### Backward clock adjustments

Moving the clock backward does not invalidate the current committed selection.

Refrain retains that selection until a subsequent configured day-start boundary is reached.

For example, if Refrain selects content at 06:00 on October 17 and the clock is subsequently changed to 04:00 on October 12:

- the October 17 selection remains active;
- no immediate reselection occurs;
- the highest previously reached reveal stage is preserved;
- when the clock subsequently reaches 06:00 on October 12, a new selection is made for October 12.

Refrain must not attempt to reverse previously committed selections or undo history updates because the clock moved backward.

### Boundary recognition

A display-day transition is an observed scheduling event, not merely a disagreement between the current date and the date stored in the active snapshot.

Each newly recognized transition may establish a new daily selection, even when its display date is earlier than a previously committed selection.

A single boundary occurrence must not cause repeated selections.

Refrain must preserve sufficient scheduling context to recover a committed selection after a restart without treating a previously observed backward clock adjustment as an immediate reason for reselection.

When execution resumes after an interruption that spans a forward display-day transition, Refrain advances to the currently appropriate display date without replaying skipped selections.

The implementation must distinguish these conditions using the available persisted scheduling context. Clock discontinuities that cannot be distinguished reliably after an interruption must be handled conservatively rather than silently discarding a valid committed selection.

The current persistent contract records the active selection's display date and day-start time, but does not record an observed boundary or clock history. After an interruption, a current timestamp and that context cannot prove whether a transition occurred, how many boundaries were crossed, or whether a clock adjustment caused the date mismatch. Startup evaluation therefore preserves the committed selection unless the runtime supplies a recognized boundary observation. Complete recovery across arbitrary interruptions requires additional boundary observation or persisted scheduling context; this issue does not add a history store.

## Content eligibility and selection

### Eligibility

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

### Special-date precedence

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

Specificity determines the winning candidate pool before repetition history or priority is considered.

Lower-specificity quotations must not be considered merely because every quotation in a higher-specificity pool has previously appeared.

If a single quotation is assigned to October 17, it remains the selection for that date every year unless a more-specific matching quotation overrides it.

A year-month-day quotation is eligible only on its specified date unless another eligibility rule explicitly applies.

Priority cannot override date specificity.

### Quotation candidates

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

### Selection pools and repetition

Refrain maintains one global repetition-history collection containing normalized quotation identities.

The collection records quotations consumed by committed selections during their active repetition cycles.

Repetition history is persistent but selectively resettable.

For each new selection, the application constructs a nonempty effective content library from successfully discovered sources and accepted entries.

Repetition identities no longer corresponding to any quotation in that effective library are removed from the proposed repetition history.

This cleanup considers all accepted quotations, regardless of current date eligibility, specificity, priority, or font availability.

Rejected entries do not contribute identities to the effective library. Their previously recorded repetition identities may therefore be removed, even if the source entries are subsequently corrected.

Missing or inaccessible content directories, failed source discovery, and an empty effective content library must not cause repetition-history cleanup.

For each new selection, the application identifies the highest-specificity eligible quotation pool.

Within that pool, quotations already present in repetition history are excluded while unused candidates remain.

When every quotation in the winning pool has been consumed, the application removes the identities of all quotations in that pool from repetition history.

The application then reevaluates the same pool.

Resetting a pool must not clear unrelated quotation identities from repetition history.

For example, exhausting the annual October 17 pool must not reset quotations belonging only to Christmas or the ordinary selection pool.

The applicable pool is determined dynamically from currently eligible quotations rather than from a permanently stored membership list.

Changes to content-library membership therefore affect subsequent selections without invalidating existing committed selections.

When a quotation participates in multiple eligibility contexts, resetting one pool may make that quotation eligible again in another context.

This is an accepted consequence of using one resettable repetition-history collection.

Repetition-history cleanup and pool resets do not modify previously recorded global-history events.

Repetition history is authoritative operational state and must not be reconstructed from global history.

Cleanup of obsolete identities is persisted only as part of a successful new selection commitment.

### Selection priority

Priority is evaluated only after date specificity and repetition eligibility.

Among unused quotations within the winning pool, Refrain retains candidates having the highest numerical priority.

Lower-priority quotations remain eligible for subsequent selections while unused.

Priority must not permit repetition of a previously consumed quotation while an unused candidate remains in the winning pool.

When multiple candidates remain tied for the highest priority, one is selected randomly.

An entry with negative priority remains eligible and may be selected once higher-priority unused alternatives have been exhausted.

When a pool resets, priority is evaluated again using the complete pool.

Equal-priority candidates must have equal selection probability.

### Duplicate quotation candidates

Quotation identity depends only on normalized text.

Multiple candidate occurrences containing the same normalized quotation may have different inherited metadata.

Such occurrences share repetition-history identity.

When multiple occurrences of the same quotation remain eligible, the selected occurrence determines the metadata included in the daily snapshot.

Refrain is not required to detect or resolve unintended duplicate content entries beyond applying the established selection and quotation-identity rules.

The selection process must not allow duplicate occurrences to distort equal-probability selection among distinct quotation messages.

### Selection procedure

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
13. Resolve the decoration using the entry's preference or the effective default decoration pool.
14. When at least one layer is effectively tintable and decoration-colour selection applies, resolve and commit one colour from the entry preference, decoration preference, effective decoration-colour pool, or built-in `black` fallback. Tintability alone does not require selecting a tint.
15. Select one font bundle using the entry preference, selected decoration preference, or effective default font pool, in that precedence order; resolve and commit each role's face within that bundle.
16. Resolve the background using the entry's preference, the selected decoration's background preference, or the effective default background pool, in that precedence order.
17. Resolve output geometry, effective literary insets, QR enablement, ordered layer conditions, and all required rendering transformations.
18. Prepare the complete daily snapshot.
19. Atomically commit the daily snapshot, updated repetition history, next selection revision, and required scheduling context as authoritative operational state.
20. Record the committed selection in global history on a best-effort basis.

Selection is not complete until operational-state commitment succeeds.

An unavailable or empty effective content library cannot produce a new selection and must not trigger repetition-history cleanup.

A failed or interrupted operational-state commitment permits the selection procedure to run again.

Failure to record global history after commitment does not invalidate the committed selection or permit another selection for the same committed event.

The next selection revision is derived from authoritative operational state, never from global-history contents.

The random results of an uncommitted selection, including decoration, font, and background selection, are not authoritative.

Selection policy must not depend on file enumeration order or incidental filesystem behavior.

## Persistent state

### Required persistence

Refrain maintains sufficient durable operational state to preserve:

- the current committed daily selection and its monotonically increasing revision;
- the display date associated with that selection;
- the selected quotation's original text;
- the resolved presentation metadata and font identifier;
- configured output dimensions and effective literary geometry;
- selected visual resource identifiers and colors;
- resolved QR enablement and, when enabled, the URL, version, error-correction level, integer module size, quiet zone, and final-resolution placement offsets;
- effective decoration layer order, conditions, rendering methods, and transformation geometry;
- the committed decoration tinting decision and, when enabled, palette identifier and resolved RGB value;
- the reveal schedule applicable to the selection;
- relevant layout configuration;
- active repetition history;
- the highest reveal stage reached for the current selection;
- scheduling context required to recover correctly after clock adjustments.

Refrain separately maintains a chronological global history of selection events.

Operational state is authoritative for selection, scheduling, reveal progression, and recovery. Global history is historical information and is not required for normal operation.

After commitment, the active presentation must not require access to the original YAML content entry.

### Daily snapshot

The daily snapshot contains a complete copy of the selected quotation and the committed presentation settings needed to prepare every reveal stage.

It includes only the selected quotation from its containing content entry, not the entry's other quotations.

The snapshot contains the selected quotation, available source and attribution, selected font identifier, selected background and decoration identifiers, effective presentation style, reveal schedule, and presentation configuration required for rendering. New snapshots also preserve output dimensions, effective literary insets, resolved QR enablement and generation parameters, and the effective ordered decoration layers with their conditions, rendering methods, and transformation geometry.

New snapshots use format version 7 and contain resource identifiers and resolved scalar parameters, not PNG bytes. Existing version-6 snapshots remain legacy snapshots: valid prepared artifacts may be reused unchanged, and regeneration must honor their committed dimensions, normalized presentation region, QR parameters, and single-image decoration semantics. Do not convert an old normalized region to insets or infer legacy QR behavior from current preferences. Earlier unsupported snapshot versions retain their existing handling; do not silently replace or reinterpret them.

Font, background, decoration, and applicable decoration-colour selection occurs after quotation selection and before the daily snapshot is committed.

An entry's explicit resource preferences take precedence according to the selection rules defined in the presentation and rendering section. Unavailable preferences do not invalidate otherwise usable quotations.

The selected resource identifiers and effective presentation settings remain fixed throughout the committed display day.

The decoration tinting decision is also fixed in the snapshot. The effective tintability of each layer and, if selected, the single decoration tint color are committed, so later palette or manifest changes cannot recolour the presentation. If no tint is selected, every layer retains its authored colors.

The snapshot contains resolved presentation values rather than references to mutable content-library entries or configuration that may subsequently change.

The snapshot does not contain font or image resource bytes, filesystem paths, or content hashes.

The snapshot is immutable after commitment.

The snapshot is authoritative for regenerating the complete set of prepared reveal-stage images. Regeneration preserves the selected content, reveal schedule, output dimensions, effective literary geometry, resolved QR policy, ordered decoration layers, transformations, and committed resource identifiers.

Presentation resources are resolved at preparation time. Missing fonts use the documented bundled-font fallback policy. Missing background or decoration images use the documented visual-resource recovery policy.

Presentation changes within the display day are represented by reveal progression and prepared images, not by modifying the selected content or committed presentation configuration.

### Global history

Global history is a chronological record of committed quotation selection events, independent of authoritative operational state.

Each record identifies the selection revision and logical display date and preserves:

- the selected quotation text;
- its normalized repetition identity;
- the selected font identifier;
- the time at which the selection was made.

Selection revisions increase monotonically and are maintained in operational state. They are not derived from global-history records.

Global history records selection events rather than unique display dates. Multiple selections associated with the same logical display date remain distinct records, including selections resulting from clock adjustments.

Global history is independent of the containing entry's identifier, source, attribution, priority, and eligibility rules for repetition purposes.

The selected font identifier is historical presentation metadata. It does not participate in quotation identity or repetition tracking.

Global history is append-only during normal recording. Recorded events are not modified or removed when repetition pools are exhausted.

Global history has configurable bounded retention. Older records may be discarded according to the configured retention policy without affecting operational state or future selection revisions.

Global-history recording is best-effort. Failure to record an event must be reported but must not invalidate an otherwise committed selection, prevent image preparation, or stop ordinary presentation.

An interruption may result in a missing or incomplete historical record. Global-history completeness is not a prerequisite for application recovery.

Global history is not consulted to determine quotation eligibility, repetition, scheduling, or the next selection revision.

### Repetition history

Repetition history contains normalized identities of quotations consumed within active selection cycles.

It is maintained in authoritative operational state and persists across application restarts.

Unlike global history, repetition history may have identities removed when the currently eligible highest-specificity pool becomes exhausted.

A reset removes only the identities corresponding to quotations in that pool.

For a new selection, Refrain also removes identities no longer represented in the nonempty effective content library.

The effective library may exclude rejected content files or entries. Quotations belonging exclusively to those rejected sources may lose their repetition status.

Repetition-history pruning must not occur when the content directory is missing or inaccessible, source discovery fails, or no valid quotations remain.

Cleanup considers every accepted quotation independently of current date eligibility, specificity, or priority.

Repetition-history cleanup is incorporated into the next successful selection commitment. It does not require a separate maintenance operation or periodic background service.

Repetition history must not be reconstructed from global history after each restart, since doing so would reverse intentional pool resets and introduce a dependency on historical-log retention.

### Selection commitment

Selection commitment establishes a new authoritative operational-state revision containing:

- the complete daily snapshot;
- the updated repetition history;
- the identity and scheduling context of the committed selection;
- initial reveal progression.

These values form one consistent operational-state update.

A new selection revision is derived from the preceding operational-state revision, independently of global history.

An interrupted operational-state update must recover to either the preceding valid selection or the newly committed selection.

A partially written or invalid snapshot must not be treated as a completed selection.

Once an operational selection has been committed, failure to prepare images, update the display, or append global history must not cause the same selection to be committed again.

Global-history recording follows successful selection commitment but is not part of the authoritative operational-state transaction.

The persistence mechanism must provide reasonable protection against incomplete writes and interrupted replacement.

The exact storage formats, rotation mechanics, and persistence operations belong to engineering.

### Prepared images

After selection commitment, Refrain generates every required reveal-stage image from the committed snapshot and available presentation resources.

Prepared images are persisted on disk.

They are derived artifacts, not independently authoritative application state.

Prepared images must remain associated with the snapshot from which they were generated.

A complete, valid set of prepared images should be reused after application restart.

Missing, damaged, or incomplete prepared images must be regenerated using the committed snapshot and currently available presentation resources.

Regeneration applies the documented font, background, and decoration recovery policies without changing committed identifiers or layout values.

The same resolved resources and effective presentation region must be used for every stage prepared together.

Regeneration must not trigger a new daily selection or alter repetition or global history.

The runtime must not require all prepared images to remain decoded in memory.

### Recovery and missing content

On startup, Refrain first attempts to recover the committed operational selection.

The content library does not override a valid committed snapshot.

If the original YAML entry has been removed, renamed, or modified, the current selection remains unchanged.

Missing or invalid original content does not prevent recovery when the committed snapshot is valid.

If selection commitment was interrupted, Refrain must recover the last valid operational state and repeat selection when necessary.

If rendering or image persistence was interrupted after commitment, Refrain resumes or repeats preparation using the same committed snapshot.

Image regeneration may use a bundled fallback font if the selected font is no longer available.

If no usable font resource can be resolved, the application must report the preparation failure rather than silently substitute an arbitrary system font.

Missing or unusable committed background and decoration resources are omitted according to their documented recovery policies. They do not cause visual-resource reselection or alteration of the effective presentation region.

Exact pixel reproduction is not required when installed presentation resources have changed.

If the committed snapshot itself is unavailable or invalid, the application must report the failure and must not silently substitute another quotation.

Missing, damaged, or inaccessible global history must not prevent operational recovery.

The existing physical e-paper image should be preserved when recovery cannot safely complete.

### Calendar presentation archive

A future calendar presentation archive may preserve the fully revealed presentation image and associated metadata for previously selected display dates.

Calendar history and global history serve different purposes.

Global history records every committed selection event in chronological order, including multiple selections for the same logical display date.

Calendar history provides at most one current archived presentation for each logical display date. When a later committed selection uses a previously recorded display date, that selection supersedes the earlier calendar presentation for that date.

A calendar presentation is associated with the revision that produced it.

The calendar archive is independent of active selection, repetition history, and global-history retention.

Its records need not contain embedded font resources or complete rendering snapshots when the final prepared image and relevant presentation metadata are retained.

Calendar archive publication, retrieval, storage, and retention are deferred until the corresponding interface capability is implemented.

### Persisted and derived state

Authoritative operational state owns:

- the current committed selection and its monotonically increasing revision;
- active repetition history;
- the immutable daily content snapshot;
- monotonic reveal progress;
- scheduling context needed for recovery.

Global history owns chronological historical selection records but does not determine operational behavior.

Prepared images are derived from the current snapshot and available presentation resources.

The appropriate reveal stage is initially determined by the committed schedule and current time.

Within a committed selection, reveal progress must not move backward.

The currently required stage is therefore the later of:

- the stage required by the current time;
- the highest stage already reached for the committed selection.

Reveal progression must survive application restarts.

Prepared images remain recoverable from the committed snapshot and available presentation resources. Pixel-identical reproduction is not guaranteed after changes to installed fonts, backgrounds, or decorations.

The future calendar archive is a separate historical presentation resource and is not authoritative for the active display.

## Progressive reveal

### Cumulative presentation

Refrain progressively reveals information associated with the committed daily selection.

The primary quotation appears at the first presentation stage.

Additional information, such as source and attribution, appears at later configured stages.

Reveals are cumulative.

Information that has become eligible for presentation must remain visible for the remainder of the committed selection.

Optional fields absent from an entry are omitted rather than displayed as empty placeholders.

### Schedule configuration

A global reveal schedule defines the default timing for supported semantic fields.

Individual content entries may override that schedule.

The effective schedule is resolved before the daily snapshot is committed.

Subsequent changes to global configuration or the original entry do not alter the committed schedule.

Reveal schedules must be validated to prevent impossible or contradictory behavior.

Reveal timing is evaluated relative to the logical display day associated with the selection.

### Stage preparation

After selection commitment, Refrain prepares all images required by the effective reveal schedule.

Each image represents one cumulative reveal stage.

All images are generated using the same committed content and layout configuration.

Normal scheduled progression uses these prepared images.

The renderer is not invoked separately for each reveal event during ordinary operation.

If preparation fails, Refrain retains the committed selection and retries preparation without selecting different content.

### Startup and missed events

On startup, Refrain recovers the committed selection and its highest previously reached reveal stage.

The active stage must be at least the previously reached stage.

If the current time requires a later stage, Refrain advances directly to it.

Missed intermediate stages do not need to be displayed sequentially.

A restart must not reset the progressive reveal sequence.

### Clock changes

Forward clock adjustments may advance the current reveal stage immediately.

Backward clock adjustments must not cause previously revealed fields to become hidden.

Reveal progression remains monotonic within the lifetime of the committed selection.

When a new daily selection is committed, reveal progress begins according to that selection's applicable schedule and current time.

Clock adjustments that establish a new display day follow the rules defined in the display-day model.

### Scheduling and display

The hardware-independent scheduling evaluator determines whether an initial or transition-driven selection is required, the display date for that selection, and the required reveal stage for a committed selection. It accepts an explicit timezone-aware current timestamp, application configuration, recovered persistent state, and optionally a boundary observed by the running application.

The public interface is `refrain.evaluate_scheduling(current_time, configuration, state, observed_boundary=None)`. It returns an immutable `SchedulingDecision` whose `SchedulingAction` is `INITIAL_SELECTION`, `NEW_SELECTION`, `ADVANCE_REVEAL`, or `NO_ACTION`. Initial and transition-driven selections include `display_date`; decisions for a committed selection include `required_reveal_stage`. Invalid or insufficient inputs raise `SchedulingEvaluationError` rather than producing a guessed transition.

Without a committed selection, the evaluator calculates the initial display date using host-local civil time. With a committed selection, a difference between the current date and the snapshot's display date does not authorize reselection. A `DisplayDayBoundary(display_date, state_revision)` observation identifies the resulting display date and the selection revision active when it was observed; after that revision is replaced, the observation is stale. Evaluations are pure; they do not select content, persist state, prepare images, or operate a display.

`refrain.resolve_reveal_stages(snapshot)` returns the canonical ordered `CompositionVisibility` sequence for a committed snapshot. The coordinator must pass this same sequence to image preparation and recovery; scheduling evaluation derives its required stage index from that sequence. Simultaneous reveal times share a stage, fields scheduled at the quotation time appear in stage zero, and source and attribution may reveal in either order. The final stage includes every available optional field.

`refrain.DisplayDayBoundaryObserver` recognizes only transitions observed during the current process lifetime. Its first timestamp establishes a baseline, a backward wall-clock adjustment resets that baseline without creating a boundary, and a forward jump produces at most one boundary for the currently appropriate display date. An already pending observation remains available across a clock adjustment while its associated selection revision remains current; backward adjustments do not replace it with an earlier date, while a later observed forward transition supersedes it with the currently appropriate date. The observer returns the same pending observation on repeated calls while that revision and date remain current; observing a later revision expires it. A failed selection commit therefore leaves the event available for retry, while a successful commit makes it stale to `evaluate_scheduling()`. The observer does not persist clock history; after an interruption, an isolated timestamp cannot establish that a boundary occurred, so startup continues to follow the conservative recovery policy above.

`refrain.next_scheduling_deadline(current_time, configuration, state)` returns the next applicable committed reveal time or configured display-day boundary. `refrain.wait_for_scheduling_event(deadline, wake_event, ...)` waits for that deadline or an external wake event and returns control for reevaluation after a detected wall-clock adjustment. The coordinator remains responsible for calling `evaluate_scheduling()` and executing its decisions; observation and waiting do not select content, mutate persistent state, prepare images, or operate a display.

The application coordinator executes returned decisions through the selection, persistence, preparation, and display components. For a committed selection, the required reveal stage is the later of the stage implied by the snapshot's resolved schedule in host-local time and the persisted highest stage. The scheduling context contains only the display date and day-start time. Missing optional fields do not add reveal stages, and missed reveal times can advance directly to the latest applicable stage. A persisted stage beyond the sequence's final index is invalid and evaluation raises `SchedulingEvaluationError`.

The coordinator presents the corresponding prepared image when a reveal advancement is required. Scheduling evaluation does not determine whether an image was successfully presented.

A failed display update does not invalidate the committed selection or its prepared images.

A subsequent successful update may skip intermediate stages and present the latest required image.

## Presentation and rendering

### Rendering independence

Daily-image preparation accepts a committed daily snapshot and an explicit sequence of cumulative reveal stages.

Preparation resolves the snapshot's literary content and presentation settings, generates the view-specific background, and uses the shared renderer to produce complete images without accessing physical display hardware.

Neither preparation nor the renderer selects content, modifies selection history, or determines application lifecycle policy.

Rendered output must be testable and inspectable without Raspberry Pi display hardware.

### View composition

Daily-image preparation separates graphical composition from the shared literary renderer. The renderer owns the typography, fitting, positioning, and drawing of the quotation and its optional source and attribution within the resolved literary rectangle. It does not read application configuration, select content or fonts, access selection history, or determine application lifecycle policy.

#### Output and working canvases

Output dimensions are configured once per application instance. All configured display backends receive the same complete final-resolution image; a backend does not select or resize an independent resolution. A backend that cannot accept the configured dimensions reports that incompatibility. The Waveshare 13.3-inch HAT+ (E) uses its native 1600 × 1200 landscape or 1200 × 1600 portrait dimensions.

The initial supported aspect ratios are 4:3, 16:9, and 16:10, within a maximum 3840 × 2400 raster envelope. The reference canvas is 1600 pixels wide, with height derived from the selected ratio: 1200, 900, or 1000 pixels respectively. The reference canvas expresses design measurements; it is not an output or working image.

The working canvas is the largest integer-sized canvas within the envelope that preserves the configured aspect ratio. Its dimensions are 3200 × 2400 for 4:3, 3840 × 2160 for 16:9, and 3840 × 2400 for 16:10. Raster background and decoration composition takes place at working-canvas resolution, then is reduced to final output dimensions when necessary. Do not upscale a raster resource beyond what its destination geometry requires.

Reference measurements are mapped with one uniform scale for each resolved canvas. Convert each nonnegative measurement to the nearest integer pixel, with exact half-pixel values rounded upward. Compute opposing edges independently, then derive the remaining width or height by subtraction so the resolved rectangle has no rounding gap. Reject non-finite, negative, out-of-range, or degenerate geometry before rendering.

#### Literary presentation geometry

The literary region is defined by four independent reference-canvas insets: `left`, `right`, `top`, and `bottom`. Each inset is measured inward from its corresponding edge and is multiplied by the uniform reference-to-canvas scale. The effective rectangle is the area remaining after those resolved insets are removed.

Global layout insets provide the defaults. A selected decoration may replace them with a complete inset set for the committed presentation. The resulting rectangle must have positive width and height and contain the complete literary composition. It remains unchanged across every reveal stage.

Presentation insets are independent of decoration slice coordinates, PNG dimensions, and artwork transformations. Neither system determines or modifies the other.

#### Raster composition pipeline

Prepare each literary reveal-stage image in this order:

1. Resolve configured output geometry and its working canvas.
2. Compose a paper-white base, the selected background, and selected decoration PNG layers at working resolution, processing layers in manifest order.
3. Downsample the graphical composition to final output dimensions.
4. Fit and render all literary text at final resolution using the stable effective rectangle.
5. When QR generation is enabled, generate and composite the QR code at final resolution.
6. Persist the complete prepared reveal-stage images and publish them through the existing backend architecture.

Every decoration PNG is behind all literary text and QR output. This pipeline does not introduce foreground composition phases, arbitrary z-index values, or a general layer-ordering engine. The same geometry and graphical composition are used for every reveal stage. Other views, including the information view, retain their separate composition and QR behavior.

#### Decoration layers

A selected decoration may contain an ordered sequence of PNG layers. Each layer has a source image, a required rendering method, optional parameters for that method, an optional QR-presence condition, and optional tintability metadata. Layers are composed in manifest order. The initial methods are `contain`, which aspect-preservingly scales the image to fit the working canvas, and `nine-slice`, which adapts an image using four explicit source-pixel slice insets. No other methods or independent positioning are defined.

For `nine-slice`, source dimensions are mapped into the reference canvas using one uniform contain scale; that same uniform reference-space scale preserves corner proportions on the working canvas. Four source-pixel boundaries (`left`, `right`, `top`, `bottom`) partition the PNG into nine regions. Reject non-integer, negative, overlapping, or out-of-bounds boundaries.

Place the four corner regions at the corresponding destination canvas corners without changing their proportions. Horizontal edges preserve their thickness and adapt along their horizontal length; vertical edges preserve their thickness and adapt along their vertical length. `stretch` scales an edge segment along its length to fit. `crop` retains the segment's scale, centers it, and crops equally from both ends of that edge segment; it never crops the complete source image. If the requested crop destination is longer than the available source edge segment, reject the transformation instead of stretching it or leaving a gap. The center region stretches in both dimensions to fill its destination rectangle. Edge tiling is not supported.

Use the deterministic reference-space scaling and nearest-integer, half-up rounding rule defined above for all slice boundaries and corner dimensions. Resolve shared destination boundaries once and assign any rounding remainder to the adjoining edge, so regions meet without gaps or overlaps. Reject a destination smaller than the combined preserved corner dimensions with an actionable diagnostic. Preserve source alpha through scaling and alpha composition.

#### Decoration tinting

Decoration-wide and per-layer `tintable` values both default to `true`. A layer is tintable only when `decoration.tintable AND layer.tintable` is true. This permission does not require a tint to be selected. If tinting is selected, one effective decoration tint color is committed and applied only to effectively tintable layers; do not select separate colors per layer. Preserve each source pixel's alpha, including antialiasing and transparency.

#### QR generation and conditional artwork

The presentation-level QR policy defaults to enabled and may be disabled. Effective enablement is the logical AND of that policy and the selected decoration's `qr_ready` value; omission of `qr_ready` means `true`. A selected decoration with `qr_ready: false` therefore suppresses QR generation even when the presentation policy enables it. Resolve and commit effective QR enablement before image preparation rather than inferring it from available artwork. A layer condition of `always` (the default), `qr`, or `no-qr` selects artwork for both states, enabled-only, or disabled-only respectively. Conditions do not change layer order.

When enabled, generate a black QR symbol at final output resolution with square integer-pixel modules and its complete opaque-white quiet zone. Composite it without subsequent resize or resampling. Resolve its dimensions and offsets from final output geometry and commit the resolved generation parameters. Do not automatically modify literary insets or image slicing to accommodate QR placement; QR overlap is not automatically avoided. The standalone information view remains outside literary QR behavior.

The same quotation renderer serves normal daily presentations, the information view, and potential future diagnostic views.

The renderer does not require a content-library entry or committed daily snapshot as its input. Callers supply the resolved content and presentation parameters appropriate to the view.

The architecture does not require a general-purpose layout framework, externally supplied rendering components, a theme engine, or a plugin interface.

### Daily background and decoration selection

Configuration loading owns asset discovery, validation, collision handling, and construction of independent font, background, and decoration registries. Bundled resources are discovered through Python package-resource APIs; user resources are discovered recursively under the corresponding `assets/{fonts,backgrounds,decorations}/` directory beside the effective configuration. Discovery occurs once when configuration is loaded. It does not monitor or modify user directories.

Discovery establishes availability by stable identifier only. It never adds resources to selection pools. The configured default pools remain the sole source of automatic-selection eligibility; any available resource may still be selected explicitly by content or decoration metadata.

Asset manifests are safely parsed and their references are confined to their owning package. Invalid resources are isolated with diagnostics. Custom identifiers cannot shadow reserved bundled identifiers, and every custom resource in an intra-category collision is excluded deterministically.

Application configuration defines a default selection pool for each resource type. Each pool may contain the reserved value `"none"`, representing the intentional absence of that resource.

An omitted resource configuration preserves the plain paper-white, undecorated presentation.

Decoration, font, and background selection occurs after quotation selection and before committing the daily snapshot.

For each selected quotation, Refrain resolves the decoration first:

1. Use the content entry's explicit decoration when available.
2. An explicit decoration value of `"none"` suppresses decoration selection.
3. Otherwise, select from the effective default decoration pool.

The selected decoration may provide preferred font and background values and a complete literary-inset override.

Exactly one font bundle is selected using this precedence:

1. Use the content entry's explicit font when available.
2. Otherwise, use the selected decoration's preferred font when available.
3. Otherwise, select from the effective default font pool.

Background selection follows this precedence:

1. Use the content entry's explicit background when available.
2. An explicit background value of `"none"` suppresses all background selection, including a decoration's preferred background.
3. Otherwise, use the selected decoration's preferred background when specified and available.
4. Otherwise, select from the effective default background pool.

A decoration may explicitly prefer `"none"` as its background. This suppresses automatic background selection unless the content entry supplies its own background preference.

When a requested resource is unavailable, Refrain retains an otherwise valid content entry and proceeds to the next applicable preference, with an appropriate diagnostic.

Invalid decoration registrations must not make unrelated fonts, backgrounds, or decorations unavailable.

Each effective background and decoration default pool has equal-probability selection among its distinct members. Neither pool has repetition history or weighting in Version 0.1.

The selected font, background, and decoration identifiers, output dimensions, effective literary insets, resolved QR enablement, ordered layers, and rendering transformations are committed with the daily presentation. They are not part of quotation identity or repetition history.

These selections remain fixed throughout the committed display day, including after restarts.

After resolving the decoration, Refrain resolves one literary text color using the first level with usable candidates: the content entry's `text_color`, the selected decoration's `text_color`, the effective `layout.text.colors` pool, then built-in `black`. Invalid or unavailable identifiers are diagnosed and excluded at each level. Candidates are not combined across levels, and duplicate identifiers do not add selection weight.

The selected palette identifier and its resolved RGB value are committed in the daily snapshot. Color selection is independent of quotation identity and repetition history. The effective text color is fixed for the committed display day and is not reconsidered during reveal progression or recovery.

The registries, valid identifiers, image requirements, pool configuration, and content-entry overrides are specified in `docs/CONTENT_FORMAT.md`.

### Background and decoration recovery

The committed daily snapshot identifies the selected background and decoration, contains the effective literary insets and output dimensions, and records the ordered decoration layers and resolved transformation geometry.

The snapshot does not embed background or decoration image bytes, filesystem paths, or content hashes.

Image preparation resolves the committed identifiers against available resources. Existing valid prepared images remain reusable when installed resources change.

When prepared images must be regenerated, Refrain uses the committed identifiers rather than repeating background or decoration selection.

If a committed background becomes unavailable, preparation uses the paper-white base with an appropriate diagnostic. It does not randomly select another background.

If a committed decoration or one of its required layer images becomes unavailable, preparation omits that decoration with an appropriate diagnostic. It retains the committed effective literary insets rather than recalculating them from the current decoration registry or global configuration.

The committed tinting decision and RGB value are used during regeneration; preparation does not recalculate tintability or colour from the current manifest or palette. Snapshots predating tint metadata preserve legacy untinted rendering, including when a current decoration manifest marks the resource tintable.

The same rule applies when a decoration's preferred background was selected and subsequently becomes unavailable.

Background source dimensions and aspect ratios are independent of configured output dimensions. Preparation applies deterministic, aspect-preserving centered cover scaling and equal-edge cropping at working resolution, then composites the result over paper-white while preserving source alpha. Decoration layers use the configured rendering method at working resolution. Their slice coordinates and transformations do not determine the literary insets.

A recoverable missing image resource must not invalidate the committed quotation or its reveal progression. Other preparation errors, including malformed required snapshot data or an unrenderable literary composition, remain errors.

Resource substitution during regeneration may alter appearance, but it must not modify the committed snapshot.

The daily background and decoration system does not alter the independent composition or recovery policies of the information view.

### Information view

Refrain provides an information view presenting application identity and selected runtime information in a format consistent with its quotation-based visual design.

The information view contains:

- a curated, application-owned quotation associated with the running release;
- optional source and attribution identifying the quotation's context;
- the Refrain and ControlForge project identity;
- application version and available build or commit information;
- basic platform and Python runtime
- the configured display backend types;
- an appropriate copyright notice.

The curated quotation is supplied by the application rather than selected from the user content library. It remains consistent for a given release and does not participate in daily selection, priority, repetition history, or global selection history.

The information-view background generator owns branding, runtime information, and other non-literary presentation elements.

The shared quotation renderer presents the curated quotation and its optional source and attribution using the same composition and typography facilities as normal daily quotations.

The literary composition remains visually primary. The initial design favors approximately 70% literary presentation and 30% supporting information, without prescribing rigid layout proportions.

Branding and runtime information must remain visually subordinate and must not compromise readability.

The initial information view uses one application-owned layout. Multiple configurable information-view styles are not required.

Runtime information is a snapshot of available information at the time the view is prepared, not a continuously updated monitoring interface.

Version information should identify the running application release. Build or commit information may be included when available without requiring access to a Git checkout at runtime.

Configured display backend types are reported without attempting to represent their current health or publication status.

Optional runtime details must be omitted gracefully when unavailable. Missing diagnostic information must not prevent preparation of the information view.

The information view is independent of the committed daily selection. Preparing or displaying it must not create a new selection, modify selection histories, or advance reveal progress.

The same complete information-view image is supplied to all configured display backends through the normal publication facilities.

Automatic presentation occurs once on each application start, subject to the configured duration. It does not repeat at ordinary display-day boundaries.

The automatic duration defaults to 60 seconds. A duration of zero disables automatic presentation without disabling the information-view capability.

The configured duration is measured using elapsed monotonic time beginning when the first backend successfully publishes the information view.

Publication to other backends remains independent. A slow or unavailable backend must not delay the transition to daily presentation for other destinations.

If no backend successfully publishes the information view within a bounded initial attempt period, the application proceeds toward normal daily presentation rather than waiting indefinitely.

When the duration expires, Refrain determines the currently required daily presentation using the normal scheduling and recovery rules. It does not replay reveal stages that are no longer required.

An information-view preparation or publication failure must not invalidate the committed selection or prevent ordinary daily presentation when a functional display destination remains available.

The architecture permits the information view to be requested independently of automatic startup behavior. Version 0.1 does not require an external trigger, interactive interface, or runtime control mechanism for requesting it.

### Initial visual design

The initial release provides one configurable presentation layout.

Its intended appearance is that of a carefully typeset printed page rather than a conventional electronic interface.

The design prioritizes:

- readable typography;
- generous whitespace;
- restrained visual decoration;
- a predominantly paper-white background;
- dark text with optional color accents.

The effective literary rectangle derived from the four presentation insets contains the complete literary composition: the quotation and its optional source and attribution.

The shared quotation renderer determines the arrangement of all present fields within that region.

The quotation remains visually dominant. Source and attribution use subordinate typography and are presented together as a compact byline beneath the quotation.

When both fields are present, the byline presents the attribution first, followed by the source:

`— Attribution, Source`

The attribution uses a restrained, visually distinct text treatment. The source is preferably italicized where an appropriate resolved font variant is available.

Version 0.1 does not require italic font support or automatic font substitution. The byline must remain legible and correctly arranged when only the regular resolved font is available.

When only attribution is present, the byline uses the form `— Attribution`. When only source is present, it uses `— Source`. Absent fields do not introduce unnecessary separator punctuation.

The complete byline is horizontally centered beneath the quotation for the `centered` presentation style and right-aligned within the presentation region for the `left-aligned` style.

Unrevealed source and attribution fields remain visibly represented within the byline rather than leaving blank space or displaying literal placeholder characters.

Their representation must be sufficiently obscured that the original text is not legible, while preserving the visual footprint and placement of the eventual revealed content.

Suitable treatments include aggressive blurring or dense pixel-level distortion. The initial implementation should select a deterministic treatment appropriate to the target e-paper display rather than expose configurable concealment styles.

The byline retains its applicable leading dash and separator punctuation throughout progressive reveal.

Automatic fitting determines suitable text wrapping and font sizes within the supported bounds. All present fields must fit within the presentation region without overlapping, clipping, truncation, or omission.

The presentation insets are configured in reference-canvas pixels and uniformly scaled to resolved canvas dimensions.

Fitting must preserve the quotation's intended text, including explicit line breaks and paragraph structure.

For quotations with explicit line breaks, fitting prioritizes the largest permitted font size that preserves authored lines without additional wrapping while fitting the complete composition. If authored lines cannot fit at the minimum permitted quotation font size, automatic word wrapping remains available. Quotations without explicit line breaks retain automatic wrapping and largest-fitting-font behavior.

The renderer supports named presentation styles that determine how literary content is arranged within the presentation region.

Version 0.1 provides two built-in styles:

- `centered`: Each rendered quotation line is independently centered horizontally. The quotation block is vertically centered within its allocated space, with the byline centered beneath it.
- `left-aligned`: Rendered quotation lines share a common left edge. The resulting text block remains horizontally centered according to its widest rendered line, rather than anchored to the region's left edge, with the quotation block vertically centered within its allocated space and the byline right-aligned.

The selected presentation style is defined at the content-entry level and applies to every quotation in that entry. The default is `centered`.

The rendering design must accommodate additional built-in presentation styles without changes to content-selection policy, persistence mechanisms, reveal scheduling, or physical display integration.

Future styles may control line positioning, spacing, and the arrangement of source and attribution, provided they preserve required content, respect the presentation region, and maintain stable geometry across reveal stages.

The initial release does not require additional styles, arbitrary layout scripting, externally supplied style implementations, or a general-purpose styling framework.

### Font selection

Bundled fonts, backgrounds, and decorations are package-owned resources accessed through package-resource mechanisms. User-provided resources belong under the `assets/` directory beside the effective configuration file, separated into `fonts/`, `backgrounds/`, and `decorations/`; they are not generated cache data. The configuration loader discovers and validates resources in these locations when effective configuration is loaded.

Refrain maintains an effective font registry containing usable bundled and discovered font bundles.

Application configuration defines an explicit default font pool using stable identifiers. The effective default pool contains only usable fonts from that configured pool.

Unusable or invalid user font registrations are excluded from the effective registry with appropriate warnings. Bundled font identifiers remain reserved and cannot be overridden.

A content entry may specify a preferred font, inherited by every quotation in that entry.

A decoration may also specify a preferred font.

Font selection follows this precedence:

1. Use an available explicit content-entry font preference.
2. Otherwise, use an available font preference from the selected decoration.
3. Otherwise, select from the effective default font pool.

An unavailable bundle preference does not invalidate an otherwise valid content entry or decoration. Refrain reports an appropriate warning and proceeds to the next bundle-selection preference.

After selecting the bundle, Refrain independently resolves the `quotation`, `source`, and `attribution` faces within that bundle. For each role, the first defined preference wins in this order: content entry, selected decoration, selected bundle manifest, global `layout.fonts.font_faces`, then implicit `regular`. An explicit `regular` is defined and overrides lower-priority values. If the winning face is unavailable or unusable, that role falls directly to the selected bundle's `regular` face with an actionable warning; lower-priority face preferences are not consulted. No role selects another bundle. Decoration face preferences apply to the selected bundle even when an entry overrides the decoration's bundle preference.

Each font in the effective default pool has equal selection probability.

The effective default pool must be nonempty when a new selection requires automatic font selection. Refrain must not silently populate it with unrelated bundled fonts.

Font selection is independent for each daily selection. Fonts do not have repetition histories, and a font may be used on consecutive days.

The selected decoration is resolved before font selection. The selected font identifier is resolved before daily snapshot commitment.

The selected bundle identifier and all three effective face identifiers are recorded in the committed snapshot before preparation. Font contents, paths, and font-content hashes are not persisted in operational state. Existing format-6 snapshots without face metadata remain valid and continue to render every role with `regular`; no state migration or rewrite is needed. This absence is not interpreted as a request to apply newly configured face preferences.

Image preparation resolves the committed bundle and face identifiers using available font resources. It does not reconsider the original entry, decoration, bundle-manifest, or global preferences.

If a committed face is no longer available or usable during regeneration, that role uses `regular` from the resolved bundle without changing the snapshot. If the entire committed bundle is unavailable or unusable, Refrain uses an available bundled fallback font, selected deterministically; it applies the committed face identifiers against that fallback bundle and uses its `regular` face for any unavailable face. The resolved bundle and role faces remain consistent across all stages prepared together.

If no usable bundled fallback exists, preparation fails with an actionable diagnostic.

Existing valid prepared images are not invalidated solely because installed font resources have changed.

Font registration, default-pool validation, and configuration fallback rules are defined in `docs/CONTENT_FORMAT.md`.

### Stable progressive layout

The renderer resolves the complete literary composition using the quotation and every available source and attribution field, regardless of the current reveal stage. Each role uses its committed face while the source and attribution remain components of the existing unified byline.

The effective literary rectangle, resolved from the selected decoration's insets or global insets and recorded in the committed snapshot, remains unchanged throughout the committed selection.

The resolved layout establishes the positions, role-specific typography, wrapping, and spacing of all present fields. Byline measurement and baseline placement account for each face's metrics, advances, and glyph bounds. The prefix and separator use the quotation face, with fixed positions determined from the complete composition.

The byline is laid out using its complete final content, including both attribution and source when available, regardless of which fields are currently revealed.

Its punctuation, alignment, and geometry are determined from the complete composition rather than recalculated for each reveal stage.

The complete byline determines the positions and visual footprints of its individual fields.

An unrevealed field displays a visibly obscured representation within its allocated position. Concealment must prevent the original text from being legible while retaining an apparent visual presence comparable to the revealed field.

Revealing a field replaces its obscured representation with readable text without changing the field's allocated position or the surrounding composition.

The leading dash and applicable separator punctuation remain visible throughout the reveal sequence.

Previously visible quotation text, revealed byline fields, and punctuation must not move, resize, or reflow when another field is revealed.

Absent optional fields do not require reserved space, concealment, or separator punctuation.

The selected presentation style remains fixed throughout the committed selection.

Version 0.1 requires a deterministic visual concealment treatment suitable for the target e-paper display. The choice between techniques such as aggressive blurring and dense pixel distortion is an implementation decision informed by rendered-image inspection and hardware validation.

The treatment must not reveal readable text through insufficient distortion or introduce visual artifacts outside the field's allocated area.

Additional configurable concealment styles are not required.

All reveal stages use the same resolved composition layout.

Content that cannot be rendered legibly within the supported literary rectangle must be handled explicitly rather than silently clipped, truncated, or omitted.

### Committed daily presentation data

A daily snapshot must contain the selected quotation, its presentation metadata, effective reveal schedule, selected font, background, and decoration identifiers, and resolved layout values needed to prepare the presentation without consulting the original content library or current presentation configuration.

`presentation_metadata` contains optional nonempty `source` and `attribution` strings, the required built-in `presentation_style` (`centered` or `left-aligned`), and the effective `font_faces` identifiers for `quotation`, `source`, and `attribution`. New snapshots also contain `text_color_identifier` and `text_color_rgb`, the committed palette identifier and its three resolved integer RGB channels. Older valid snapshots may omit `font_faces`; preparation interprets that legacy absence as `regular` for every role and does not apply current preferences. Snapshots omitting both text-color values retain legacy literary colors, including muted attribution.

`layout` contains:

- `output_size`: configured final dimensions as positive integer width and height;
- `working_size`: the resolved high-resolution composition dimensions;
- `reference_size`: the reference-canvas dimensions associated with the selected aspect ratio;
- `presentation_insets`: the four resolved reference-pixel inset values;
- `literary_region`: the effective integer-pixel rectangle at final output resolution;
- `min_font_size` and `max_font_size`: positive integer quotation font-size bounds, with the maximum no smaller than the minimum.

The committed presentation metadata also contains effective QR enablement and, when enabled, its complete generation and placement parameters. It records the effective ordered decoration layers, layer conditions, rendering methods, source identifiers, source-pixel slice boundaries, and resolved transformation geometry. Snapshot format 7 includes these values in its canonical fingerprint; dimensions, geometry, conditions, and transformations therefore cannot be changed by later configuration or manifest edits.

The snapshot also preserves the resolved background and decoration identifiers. The reserved value `"none"` represents the absence of the corresponding resource.

The snapshot stores resource identifiers, not font or image contents or their digests. Effective role-face identifiers are part of the snapshot fingerprint used to associate prepared images, so typography changes cannot be mistaken for the same presentation. For snapshots predating face metadata, omission remains part of their canonical fingerprint, preserving reuse of their already prepared artifacts.

The committed RGB channels are part of snapshot metadata and its fingerprint. Image regeneration uses those channels rather than current palette configuration, so a later palette edit cannot recolor a committed presentation.

Daily preparation uses the shared renderer's `1.20` quotation–byline spacing factor and deterministic `pixel-distortion` concealment; these are not current-configuration fallbacks.

Presentation resources are resolved using the available registries during preparation. Font and image recovery follow their separately documented fallback policies without changing the committed quotation, metadata, reveal schedule, resource identifiers, or effective layout.

Missing or invalid required presentation data, failure to resolve any usable font, or a composition that does not fit is a preparation error.

Preparation does not change the committed snapshot or persistent selection state.

### Complete stage preparation

Presentation preparation resolves the complete literary composition once and produces every image requested for the committed selection. The caller supplies the cumulative stage sequence; preparation does not calculate reveal times or determine the current stage.

Each image represents a cumulative visibility stage of the same composition.

All stage images use identical layout geometry, typography, wrapping, and field positions. Only the visibility of fields changes.

The renderer does not independently recalculate the composition for each reveal stage.

The same preparation facilities may produce a single fully visible image for views that do not require progressive reveals, including the information view.

Every prepared image must be independently displayable without requiring a previous image to have been presented.

Prepared images are persisted for reuse throughout the current display day and after application restarts.

Normal reveal transitions select an existing prepared image. They do not invoke quotation fitting, layout calculation, or image rendering.

The preparation process must not expose incomplete images as valid presentation artifacts.


### Rendering recovery

The committed daily snapshot is the authority for regenerating prepared images.

Missing or invalid prepared images may be regenerated without access to the original content library.

Regeneration resolves the committed font bundle and role-face identifiers through the available font registry. Missing role faces use the resolved bundle's regular face; a missing bundle uses the deterministic bundled fallback policy and applies committed face identifiers against that bundle. Neither recovery path changes the snapshot or consults current preferences.

Committed background and decoration identifiers are resolved through the available resource registries. Missing or unusable image resources are omitted according to the background and decoration recovery policy. Regeneration retains the committed output dimensions, effective literary geometry, QR decision, and ordered layer transformations; it does not select replacement resources or derive new decisions from current preferences.

Regeneration uses the committed text-color RGB value without consulting the current palette. If both text-color fields are absent, it preserves the historical renderer behavior and attribution-color distinction; it does not infer a color from current configuration.

Recovery must not change the selected quotation, presentation metadata, reveal schedule, committed resource identifiers, or committed layout configuration.

Exact pixel reproduction is not required when installed font resources have changed. Existing valid prepared images remain reusable independently of those changes.

If image generation fails, the application must report the error and preserve the existing display image where practical.


### Rendered-image comparison

The application should avoid unnecessary physical refreshes when the required prepared image has not changed.

The display scheduler and backend remain independent of the renderer.

Normal scheduled updates select among prepared images rather than invoking image composition.

## Display output

### Backend responsibility

Refrain presents complete rendered images through narrow, hardware-independent display backend interfaces.

A display backend provides two operations:

- `update(image)` presents a complete Pillow image through the configured output destination.
- `close()` releases resources owned by the backend.

Refrain selects one or more built-in display backends through validated runtime configuration. Each backend type may be configured at most once.

Backend selection occurs at application startup and does not require modifications to application code or replacement of installed modules.

Version 0.1 provides three built-in display backends:

- `window`: Presents complete images in a graphical desktop window.
- `waveshare-13in3-e`: Presents complete images on the supported Waveshare 13.3-inch e-Paper HAT+ (E).
- `image-server`: Makes the current complete image available to network clients through a read-only HTTP service.

All configured backends receive the same prepared presentation image. Backend selection does not introduce independent content selection, reveal scheduling, rendering, layout, or resolution.

The desktop window backend presents complete images in a graphical window suitable for development and validation on Windows and Linux.

The window backend owns its GUI event loop and keeps the window responsive between synchronous image updates. It replaces the existing image in one window and releases that window when `close()` returns.

The backend reports initialization, presentation, and cleanup failures through common display-backend errors. It reports an unavailable graphical environment with guidance to install Tk support and use a graphical session.

The Waveshare backend owns model-specific hardware operations, including:

- device initialization;
- image conversion and transfer;
- full-screen refresh;
- controller sleep or release where supported;
- hardware error reporting;
- cleanup.

The Waveshare backend accepts complete RGB images at its native 1200 × 1600 portrait and 1600 × 1200 landscape resolutions; images with alpha or palette transparency are unsupported. It rejects other dimensions rather than independently rescaling a backend image. It converts the complete image before initializing the controller and verifies that conversion produced exactly 960,000 packed elements. Each valid update initializes the controller, transfers the complete image, and returns the controller to sleep. It does not clear the display before an update or during shutdown. `close()` is repeatable and sleeps the controller only when an update has left it active.

The image-server backend owns an HTTP service that exposes the most recently accepted complete image. Its publication and lifecycle responsibilities are defined separately below.

The common interface does not expose hardware-specific initialization, SPI, GPIO, controller commands, refresh mechanisms, or network transport operations.

Each backend validates image compatibility with its destination rather than silently resizing or otherwise changing the prepared presentation.

A completed `update()` indicates that the individual backend's presentation operation completed successfully. For a network image service, this means the replacement image is available to clients, not that any client has retrieved or displayed it.

Failures and uncertain hardware outcomes must remain distinguishable where the underlying implementation permits.

Display backends must not perform quotation selection, reveal scheduling, image preparation, or persistent-state updates.

Backend implementations are built-in application components. Version 0.1 does not define a general display plugin system.

### Multi-backend publication

Refrain coordinates publication of the current prepared presentation independently to every configured display backend.

A single committed daily snapshot and set of prepared reveal-stage images remain authoritative for all destinations.

Each backend operates independently. A slow or failed update must not delay publication to another available backend or prevent the application from recognizing subsequent scheduling events.

An active update to one backend must not overlap another update to the same backend. Updates to different backends may proceed concurrently.

The persisted highest reveal stage represents the application's globally reached reveal progression. It does not certify successful presentation by any particular backend.

Reveal progression advances monotonically when a later stage becomes required and is durably recorded independently of backend publication outcomes.

The application coordinator maintains independent successful-publication status for each backend during the application lifetime.

The application must distinguish the currently required prepared presentation from the presentation last successfully published to each backend. A successful update to one destination does not establish successful publication to another.

Publication tracking is owned by the application coordinator, not by individual display backends. Backends receive complete images and do not interpret selection revisions, reveal stages, or persistent operational state.

Backend-specific publication status is transient and does not require separate durable storage. After application restart, the coordinator supplies the currently required prepared image to each available backend.

If a new presentation becomes required while a backend is busy, the backend must eventually receive the latest required image rather than replaying obsolete intermediate updates.

An active hardware update need not be interrupted when a newer presentation becomes available.

Publication does not require simultaneous completion or acknowledgement from every destination.

The order of backend declarations does not establish publication priority.

Multi-backend publication must preserve bounded memory use and must not require one complete image copy or an unbounded update queue for every pending presentation.

### Network image service

The `image-server` backend provides a network-accessible representation of the current prepared image without requiring directly connected display hardware.

The backend exposes one read-only HTTP endpoint:

`GET /display/current`

A successful request returns the complete current image in PNG format with the appropriate HTTP content type.

The endpoint must be usable by standard HTTP clients, including ordinary web browsers, without requiring client-specific software or protocols.

The service supports HTTP entity tags (ETags) derived from the served image content. Clients may submit conditional requests using `If-None-Match`; when the current representation matches, the service returns `304 Not Modified` without transferring the image body.

When no image has been accepted, the service returns `503 Service Unavailable`.

The backend retains the current encoded PNG and its associated entity tag in memory. It does not create or manage a separate persistent image store.

Each successful `update(image)` produces a complete replacement representation before making it available to clients. Concurrent requests must observe a consistent, complete image and entity tag, never partially updated content.

The existing prepared-image persistence and recovery mechanisms remain authoritative. After application startup or recovery, the scheduler supplies the appropriate prepared image through the normal backend interface.

The HTTP service operates independently of individual clients. It does not track display devices, maintain client sessions, queue updates, or require acknowledgement that an image has been physically displayed.

Clients determine when to retrieve images. A client may miss intermediate reveal stages and retrieve only the most recently published image.

The backend does not control client polling intervals, power management, physical display refreshes, or client-side image retention.

The service must remain responsive between calls to `update(image)` without requiring the application scheduler to process HTTP requests.

The backend owns its listening resources and concurrent request handling. Initialization must report failures that prevent the service from becoming available. Shutdown must release its listening resources and terminate backend-owned execution without leaving the HTTP service running independently of Refrain.

The configured listening address controls network accessibility. The service is intended for explicitly trusted local-network deployments and must not expose application configuration, content-library files, persistent state, or privileged operations.

The image-server backend is distinct from future local or public web publishing functionality. It provides rendered image data for clients rather than a general-purpose web presentation or content-management interface.

### Update behavior

Display updates occur at meaningful presentation changes, including:

- the beginning of a new display day;
- scheduled progressive reveals;
- recovery when a backend has not successfully presented the required image.

Refrain does not require continuous physical refresh or animation.

Presentation requests are distributed independently to configured backends.

Backend updates must be coordinated so that overlapping operations cannot corrupt communication with an individual destination.

A backend that has already successfully presented the required image should not repeat an expensive update merely because the scheduler reevaluates its state.

For the image-server backend, an update replaces the currently available image representation. Network clients retrieve that representation independently of the application's scheduling operations.

### Failure handling

Display backend failures are isolated by destination.

Failure to initialize, update, or recover one backend must be reported without preventing otherwise functional backends from presenting the current image.

Transient failures may be retried using a bounded recovery policy.

Retries must not indefinitely block scheduling, other destinations, or recognition of newer presentation requirements.

A backend instance that can no longer accept updates must be released or disabled safely. Failure of that instance does not require termination of the entire application while another destination remains operational.

An unavailable backend must not be silently replaced with a different backend type.

When no configured destination is operational, Refrain must report the condition clearly and continue bounded recovery where recovery remains possible. An unrecoverable failure of every configured destination may terminate the application so that external service supervision can respond.

The application must distinguish a known successful update from a failed or uncertain update where the backend permits.

An uncertain hardware result must not be treated as proof that the desired image was successfully displayed.

For the image-server backend, unsuccessful image preparation or replacement must not expose incomplete content or invalidate the previously accepted image.

Individual network-client failures do not constitute display-backend update failures. The backend does not require clients to retrieve or acknowledge published images.

The exact retry parameters and backend lifecycle mechanisms are engineering decisions informed by the relevant output destination.

Backend recovery must not modify committed selection history or cause quotation reselection.

### Retained display content

E-paper retains its visible image without continuous power.

Refrain should preserve useful displayed content across temporary application and hardware failures when possible.

It must not clear a physical display merely because a recoverable software problem occurred or another backend failed.

The image-server backend retains the last successfully accepted image while the backend remains operational. It does not independently persist that representation across application restarts.

Network clients are responsible for retaining their displayed content during temporary network or application unavailability.

## Application lifecycle

### Application paths and initialization

The command-line entry point resolves omitted paths to platform-standard per-user locations independently of the current working directory. Explicit configuration, state, artifact, and history paths override their corresponding defaults; an omitted history path is placed beside the effective state file. The entry point passes these effective locations to the existing application and storage components, which do not infer home-directory paths.

Normal startup requires the selected configuration file to exist. It does not substitute the packaged default configuration, create an installation directory structure, or copy sample content. Relative content paths remain based on the selected configuration file. Relative custom-resource paths use their category-specific directory under `assets/` beside that effective configuration file; absolute custom-resource paths remain direct references.

The explicit, noninteractive `--initialize` operation manages only standard per-user destinations. It reuses existing real directories, preserves an existing regular `config.yaml` byte-for-byte, and copies the packaged default only when that file is absent. It installs packaged sample content only when the standard content directory is missing or empty; any existing entry makes the directory nonempty, so initialization preserves it without validating or reorganizing its contents. It creates missing `assets/`, `assets/fonts/`, `assets/backgrounds/`, and `assets/decorations/` directories while preserving any existing contents. It copies no bundled visual resources into user assets and does not validate files already there. Initialization reuses existing state and cache directories and never modifies existing state, history, or prepared artifacts. New files use exclusive creation, no empty state or history files are created, and failures leave already-created destinations in place for a safe retry. Initialization does not start selection, preparation, or display lifecycle operations.

Configuration and content remain user-owned inputs. Operational state and global history remain authoritative and historical persistence respectively; prepared artifacts remain derived output. Runtime creation of those persistence and artifact files remains owned by their existing components.

`--reset` and `--purge` are separate interactive operations for the standard per-user installation and must be run while Refrain is stopped. Reset removes the standard operational-state file, global-history records and rotations, and generated cache contents while preserving configuration, content, all user assets, and installation directories. Purge removes the Refrain-owned standard configuration, operational, and cache directory trees, including configuration, content, and assets stored beneath the standard configuration directory; it does not follow configured paths or remove shared application-data parents. Neither operation accepts runtime path overrides or starts the application lifecycle. Their deletion checks and confirmation requirements are described in [engineering guidance](ENGINEERING.md#installation-approach).

Platform paths, installation, and service operation are documented in [engineering guidance](ENGINEERING.md#deployment-and-service-operation); public configuration is specified in [the content-format document](CONTENT_FORMAT.md).

### Startup

Normal startup performs the following logical operations:

1. Load application configuration, accepting documented defaults and recoverable configuration problems while reporting diagnostics.
2. Recover persistent operational state, if available.
3. Evaluate whether an existing committed selection remains active under the display-day transition rules.
4. Load and validate content sources when a new selection is required, constructing an effective library from accepted entries.
5. Perform and commit a new selection when required and when a usable effective content library is available.
6. Verify that all required reveal-stage images are available and valid for the committed selection.
7. Prepare or recover any missing presentation artifacts using available presentation resources and the committed snapshot's resolved layout.
8. Initialize configured display backends independently.
9. If automatic information-view presentation is enabled, prepare and request publication of the information view.
10. Observe the configured information-view duration and transition to daily presentation when it expires, or proceed directly when automatic presentation is disabled or cannot be completed.
11. Determine the currently required daily reveal stage, respecting previously reached progression and any scheduling events that occurred during startup.
12. Independently publish the corresponding prepared image to available destinations.
13. Continue operating until shutdown.

The application may prepare or recover the committed daily presentation before or during information-view publication. Information-view presentation does not defer required selection commitment or alter authoritative reveal progression.

The information-view duration begins with the first successful publication acknowledgement, not with process launch or the beginning of image preparation.

An unsuccessful initial information-view publication attempt must not indefinitely delay ordinary presentation.

The transition to daily presentation requests the image appropriate to the current scheduling state. Missed intermediate reveal stages are not replayed.

Recoverable configuration problems and individual invalid content files or entries must not prevent otherwise valid operation.

A valid committed selection does not require its original content entry or a currently usable content library to remain available.

If no committed selection exists and a usable effective content library cannot be constructed, startup cannot establish a daily presentation and must report an actionable error.

If a new selection is required during continuous operation but the content library is unavailable or unusable, Refrain must not clear repetition history, commit an empty selection, or replace the previously committed presentation.

The application must preserve existing committed state and prepared images where practical.

Failure to initialize an individual display backend must not prevent other configured destinations from becoming operational.

The implementation may organize these operations differently provided their externally observable behavior is preserved.

### New daily selection

At a recognized display-day transition, the application:

1. Determines the new display date.
2. Constructs a nonempty effective content library from successfully examined sources and accepted entries.
3. Removes obsolete repetition identities based on the effective library.
4. Performs eligibility, repetition, priority, and random quotation selection.
5. Creates the complete daily snapshot.
6. Atomically commits the snapshot, updated repetition history, next selection revision, and required scheduling context.
7. Records the committed selection in global history on a best-effort basis.
8. Generates and persists every required reveal-stage image.
9. Determines the stage appropriate to the current time.
10. Independently requests presentation of the corresponding prepared image through each configured backend.

A missing, inaccessible, or empty effective content library prevents a new selection without modifying committed operational state.

The selection is complete at operational-state commitment, independently of whether global-history recording, image preparation, or display communication subsequently succeeds.

A failure after commitment must not trigger reselection.

Presentation completion is tracked independently for each backend and does not change the committed selection.

### Normal operation

After successful preparation, the application waits for the next meaningful scheduling event.

Scheduled reveal updates select an existing prepared image.

Normal operation must not require repeated content-library access or repeated rendering.

Clock adjustments are evaluated according to the display-day and reveal-progression rules.

The application must not rely on busy waiting to determine ordinary reveal times.

### Accelerated demo operation

The optional `--demo SECONDS` operating mode repeatedly selects quotations and presents each canonical reveal stage at an accelerated interval. It bypasses normal time-of-day scheduling and boundary observation without manufacturing clock transitions. The automatic startup information view is suppressed.

The session determines its eligibility display date once from host-local time and the configured day start. Every subsequent selection uses that same date and the normal selection and resource-resolution procedure, including session repetition history. A date does not limit the number of selection revisions in this mode.

Demo progression belongs to the application controller, not the scheduler, renderer, or display backends. Each complete snapshot is committed before its canonical image set is prepared or recovered through the existing facilities. `resolve_reveal_stages()` supplies the same cumulative sequence used in normal operation, preserving simultaneous reveals and absent fields.

The initial stage is requested as soon as it is ready. Each stage receives the requested minimum monotonic viewing interval beginning at its first successful backend acknowledgement. After the final stage's interval, the controller commits another selection. Failed preparation or publication does not complete a stage or authorize reselection. Publication remains owned by the existing coordinator, with independent backend workers, coalescing, and backend-owned refresh constraints; not every destination must acknowledge each stage.

Operational state, prepared artifacts, and global history are isolated in fresh temporary session storage using their existing formats. Normal persistence locations are never read or modified, even if supplied on the command line. Committed resources remain authoritative within a quotation, and selection revisions and repetition history work normally within the session. Shutdown releases session resources; demo sessions are neither retained nor resumed. Loss of all display destinations terminates the session.

Lifecycle, retry, timing, and testing implementation guidance belongs in `docs/ENGINEERING.md`.

### One-shot diagnostic entry presentation

The optional `--show-entry ENTRY_ID` mode presents one targeted image without entering normal selection, commitment, scheduling, or recovery. For ordinary IDs, it loads the validated content library, matches the entry ID exactly, and uses that entry's first quotation, independently of date eligibility, priority, repetition history, or random quotation selection. It resolves presentation resources using the same rules as normal selection and renders the final canonical reveal stage, with every supplied field visible.

The diagnostic mode does not read or modify operational state, global history, or prepared-artifact storage. It constructs presentation data in memory and prepares one image through the shared renderer. Before initializing display backends, it saves that exact image as `refrain-<entry_id>.png` in the current working directory using exclusive creation. Existing files are never overwritten. The output is independent of the configuration file location and is not production state.

The reserved target `information` is recognized before content-library loading. It uses `prepare_information_view()` directly, without constructing a content snapshot, evaluating a reveal schedule, waiting for the configured information-view duration, or transitioning to a daily quotation. A content entry with that ID remains valid for ordinary selection but cannot override this diagnostic target.

After saving the PNG, the mode publishes one image through the existing display publication coordinator. It waits until every configured backend acknowledges the image or reaches a terminal publication failure, reports each result, and exits nonzero if any destination fails. It closes the backends after the attempts complete and does not start the continuous loop or hold serving backends open. A physical e-paper panel normally retains its image after process exit; the window and image-server backends are process-scoped and stop serving when Refrain exits. Publication failure does not remove the diagnostic PNG or alter production state.

### Standalone QR calibration

The optional `--test-qr` mode generates a final-resolution RGB calibration image using the configured output dimensions, without loading the content library or entering selection, scheduling, persistence, history, information-view, debug-layout, or prepared-artifact workflows. QR generation and pixel-aligned composition are hardware-independent; calibration parameters are supplied only through the command line.

The complete symbol and quiet-zone footprint is placed at the requested integer-pixel right and bottom offsets without rescaling or cropping. The image is atomically saved as `refrain-qr-test.png` in the current working directory, replacing only that diagnostic output, and the same image is published through the existing coordinator to every configured backend. Publication failures are reported without changing daily state or removing the saved diagnostic. Successful generation or publication does not establish physical scanning reliability.

### Recovery

Recovery is performed according to the stage at which an interruption occurred.

An interruption before selection commitment permits selection to be repeated.

An interruption after commitment preserves the committed selection.

Missing or incomplete prepared images are regenerated from the committed snapshot.

Individual display backend failures are handled through independent recovery policies without delaying other available destinations.

After restart, each available backend is supplied with the currently required prepared image without relying on persisted backend-specific presentation progress.

Recovery must not introduce additional history entries or silently substitute content.

### Shutdown

Normal shutdown must stop new presentation requests and safely release resources owned by every configured display backend.

Backend shutdown must account for active update operations without permitting unsafe overlapping hardware access.

Shutdown waits for active synchronous updates only for a bounded period. It must not interrupt a backend operation or invoke that backend's cleanup concurrently with an active update. If an update remains blocked at the deadline, its worker retains the active image and attempts cleanup if the operation later returns; process termination may ultimately end a still-blocked worker.

Failure to close one backend must not prevent cleanup attempts for other backends.

Shutdown must not intentionally erase retained e-paper images.

Committed selection state and prepared presentation images remain available for subsequent startup recovery.

### Failure isolation

Display backend failures must remain isolated from other destinations and must not invalidate content selection or persistent history.

Rendering failures must not cause reselection after a daily snapshot has been committed.

Content-library changes or validation failures must not modify an already committed daily snapshot.

An unrecoverable configuration or state error must be reported clearly rather than disguised as normal operation.

## Future interfaces and integrations

### Companion web presentation

A companion web experience is planned for a later release.

It should obtain the information required for presentation without assuming that a browser and e-paper display must consume identical rendered image files.

Web presentation must not become responsible for daily quotation selection.

The initial application does not require an HTTP server or web framework.

### Public publishing

Optional public presentation is deferred.

The architecture distinguishes public presentation information from privileged local operations.

A future public deployment may operate on a separate device or service outside the trusted local network.

Public publishing must not require exposing privileged local application interfaces.

An outbound-only publication path is preferred where it satisfies the future requirements.

The exact publication mechanism and trust boundaries will be specified before that feature is implemented.

### External actions

Content may eventually be associated with optional actions, including playback through Music Assistant.

External actions must remain separate from the core quotation-selection and rendering responsibilities.

An action is not required to display a quotation.

Privileged actions must not become available to anonymous public viewers merely because associated content is publicly visible.

External integrations must be explicitly configured and must not introduce mandatory cloud or network dependencies into ordinary display operation.

## Architectural non-goals

The initial architecture does not require:

- multiple application services;
- a general plugin framework;
- a database server;
- a content-editing interface;
- a browser-based management console;
- public network exposure;
- remote administration;
- arbitrary layout templates;
- animated display content;
- multiple synchronized e-paper displays;
- external music or media playback;
- background content retrieval from internet services.

These capabilities may be reconsidered when a concrete use case justifies them.


## Architectural invariants

The following must remain true as the project evolves:

1. Content selection does not depend on physical display hardware.
2. Rendering can be tested without physical display hardware.
3. Content entries own shared configuration, while individual quotations are the units of selection.
4. Quotation repetition identity depends on normalized text rather than entry metadata.
5. Date specificity takes absolute precedence over priority and repetition status.
6. Unused quotations take precedence over previously consumed quotations within the highest-specificity eligible pool.
7. Exhausting a selection pool resets only the repetition identities belonging to that pool.
8. Repetition-history resets and cleanup do not alter previously recorded global selection history.
9. Repetition identities absent from a nonempty effective content library may be removed during a new selection, but failed source discovery or an empty effective library must never trigger repetition-history cleanup.
10. Priority determines preference among otherwise eligible unused quotations.
11. Equal-priority distinct quotation candidates have equal selection probability.
12. A daily selection is authoritative only after its complete snapshot, updated repetition history, selection revision, and scheduling context have been committed consistently.
13. An interrupted operational-state commitment must not leave a partially committed selection or inconsistent repetition history.
14. Selection revisions increase monotonically and are maintained independently of global history.
15. Global-history recording failures do not invalidate committed selections or prevent ordinary presentation.
16. A committed daily snapshot preserves its selected content and presentation settings independently of subsequent content-library changes, while font resources may be resolved again during image regeneration.
17. Every required reveal-stage image is prepared from the committed daily snapshot and available presentation resources.
18. Prepared images are persisted and reused rather than regenerated at every scheduled reveal.
19. Missing prepared images can be recovered without selecting new content.
20. A restart does not independently invalidate the committed daily selection or reset its reveal progression.
21. Reveal progression never moves backward within a committed selection.
22. A backward clock adjustment does not independently invalidate the active selection.
23. Forward clock adjustments advance selection and reveal state to the currently appropriate presentation when required.
24. Hardware failures do not invalidate committed selections.
25. Ordinary operation does not require internet access or external services.
26. Public presentation does not grant privileged local control.
27. Future integrations must not become prerequisites for displaying ordinary quotations.

Architectural changes must be evaluated against these invariants before implementation work is accepted.
