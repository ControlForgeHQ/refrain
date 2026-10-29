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
- 1600 × 1200 display resolution.

The Raspberry Pi 3 B+ is the initial development and hardware-validation platform.

The Raspberry Pi Zero 2 W is a candidate for compact deployments, subject to successful hardware integration and resource validation.

The application must not depend on performance, memory capacity, peripheral availability, or other characteristics exclusive to the Raspberry Pi 3 B+.

The display uses Spectra 6 color e-paper technology.

The intended presentation is predominantly black typography on a paper-white background. Color is available for restrained decorative use.

The initial display is a full-frame output device. Refrain must not depend on partial refresh, animation, or frequent screen updates.

The renderer must produce images independently of the display backend.

Hardware-independent content, selection, scheduling, persistence, and rendering components must remain portable across operating systems supported by the Python runtime and required dependencies, without unnecessary operating-system-specific assumptions. This permits their development and testing on non-Linux systems but does not imply that full application deployment has been validated or is supported there.

The display backend owns hardware-specific integration, including the Waveshare driver and its platform dependencies.

Support for additional display hardware is not an initial product requirement, although display resolution, supported color capabilities, and hardware-specific operations must remain isolated from core content and scheduling logic.

The runtime should avoid unnecessary memory use and background processing, particularly to preserve compatibility with resource-constrained Raspberry Pi models.


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

**Daily Snapshot:** A persistent copy of the selected quotation and committed presentation settings sufficient to prepare its presentation independently of the original content entry. Font resources are resolved separately.

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

The initial runtime loads and validates the content library during startup.

Automatic filesystem watching, interactive editing, and runtime content reloading are not required.

A restart is required to load changes to the content library.

Once a daily selection has been committed, its presentation must not depend on continued access to the corresponding YAML entry.

Changes to the source entry affect subsequent selections, not the already committed selection.

### Content validation

Content must be validated before it becomes available for selection.

Validation must identify errors such as:

- missing required fields;
- empty quotation collections;
- empty or invalid quotation text;
- duplicate entry identifiers;
- invalid field values;
- invalid priority values;
- unsupported eligibility expressions;
- invalid reveal schedules.

Diagnostics must identify the affected entry or source file where possible.

Invalid content must not produce undefined selection or rendering behavior.

A malformed entry must not silently change the meaning of another entry.

Validation must not impose an arbitrary project-specific numerical limit on priority or the number of quotations in an entry.

The runtime must distinguish invalid content-library entries from failures involving an already committed daily snapshot.

## Display-day model

### Local time

Refrain uses an explicitly configured IANA timezone.

All display-day and reveal calculations use timezone-aware local time.

The application must not assume that every local calendar day contains exactly 24 elapsed hours.

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

The current persistent contract records the active selection's display date, timezone, and day-start time, but does not record an observed boundary or clock history. After an interruption, a current timestamp and that context cannot prove whether a transition occurred, how many boundaries were crossed, or whether a clock adjustment caused the date mismatch. Startup evaluation therefore preserves the committed selection unless the runtime supplies a recognized boundary observation. Complete recovery across arbitrary interruptions requires additional boundary observation or persisted scheduling context; this issue does not add a history store or change the persistent format.

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

For each new selection, Refrain uses the successfully loaded and validated complete content library to remove repetition identities that no longer correspond to any quotation in that library.

This cleanup considers all quotations in the content library, regardless of current date eligibility, specificity, priority, or font availability.

An unavailable, incomplete, or invalid content library must not cause repetition-history cleanup.

For each new selection, the application identifies the highest-specificity eligible quotation pool.

Within that pool, quotations already present in repetition history are excluded while unused candidates remain.

When every quotation in the winning pool has been consumed, the application removes the identities of all quotations in that pool from repetition history.

The application then reevaluates the same pool.

Resetting a pool must not clear unrelated quotation identities from repetition history.

For example, exhausting the annual October 17 pool must not reset quotations belonging only to Christmas or the ordinary selection pool.

The applicable pool is determined dynamically from currently eligible quotations rather than from a permanently stored membership list.

Changes to content-library membership therefore affect subsequent selections without invalidating existing committed selections.

Removing a quotation from the content library may cause its repetition identity to be discarded. If that quotation is subsequently restored, its previous repetition status need not be recovered.

When a quotation participates in multiple eligibility contexts, resetting one pool may make that quotation eligible again in another context.

This is an accepted consequence of using one resettable repetition-history collection.

Repetition-history cleanup and pool resets do not modify previously recorded global-history events.

Repetition history is authoritative operational state and must not be reconstructed from global history.


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
2. Load and validate the complete content library.
3. Remove repetition identities no longer present in the validated content library.
4. Identify eligible content entries.
5. Expand eligible entries into individual quotation candidates.
6. Determine the highest matching date specificity.
7. Retain candidates matching that specificity.
8. Exclude quotation identities present in the cleaned repetition history.
9. If no unused quotations remain, remove the identities of the winning pool from repetition history and reevaluate that pool.
10. Retain candidates having the highest priority.
11. Randomly select one remaining distinct quotation identity.
12. Resolve the selected occurrence and its inherited metadata.
13. Resolve the font using the entry's preference or the configured default pool.
14. Prepare the complete daily snapshot.
15. Atomically commit the daily snapshot, updated repetition history, next selection revision, and required scheduling context as authoritative operational state.
16. Record the committed selection in global history on a best-effort basis.

Selection is not complete until operational-state commitment succeeds.

A failed or interrupted operational-state commitment permits the selection procedure to run again.

Failure to record global history after commitment does not invalidate the committed selection or permit another selection for the same committed event.

The next selection revision is derived from authoritative operational state, never from global-history contents.

The random results of an uncommitted selection, including font selection, are not authoritative.

Selection policy must not depend on file enumeration order or incidental filesystem behavior.


## Persistent state

### Required persistence

Refrain maintains sufficient durable operational state to preserve:

- the current committed daily selection and its monotonically increasing revision;
- the display date associated with that selection;
- the selected quotation's original text;
- the resolved presentation metadata and font identifier;
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

The snapshot contains the selected quotation, available source and attribution, selected font identifier, effective presentation style, reveal schedule, and presentation configuration required for rendering.

Font selection occurs before the daily snapshot is committed.

An entry's explicit font preference is used when the font is available in the configured registry. Otherwise, the presentation uses a font selected from the configured default pool according to the content-format specification.

The selected font identifier and presentation settings remain fixed throughout the committed display day.

The snapshot contains resolved presentation values rather than references to mutable content-library entries or configuration that may subsequently change.

The snapshot does not contain font file contents or font file hashes.

The snapshot is immutable after commitment.

The snapshot is authoritative for regenerating the complete set of prepared reveal-stage images. Regeneration preserves the selected content, reveal schedule, and committed presentation settings. Font resources are resolved at preparation time and may differ from those originally used if an installed font has changed or become unavailable.

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

When Refrain successfully loads and validates the complete content library for a new selection, it may also remove repetition identities no longer present in that library.

This cleanup considers all quotations in the validated library, independently of current date eligibility, specificity, priority, or font availability.

An incomplete, unavailable, or invalid content library must not cause repetition-history pruning.

Repetition-history cleanup may be incorporated into the next selection commitment. It does not require a separate maintenance operation or periodic background service.

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

After selection commitment, Refrain generates every required reveal-stage image from the committed snapshot and available font resources.

Prepared images are persisted on disk.

They are derived artifacts, not independently authoritative application state.

Prepared images must remain associated with the snapshot from which they were generated.

A complete, valid set of prepared images should be reused after application restart.

Missing, damaged, or incomplete prepared images must be regenerated using the committed snapshot and the currently available font resources.

If the snapshot's selected font identifier is unavailable or unusable, regeneration may use a supported bundled fallback font.

The same resolved font must be used for every stage prepared together. Font fallback must not introduce different typography between stages of the same prepared presentation.

Regeneration must not trigger a new daily selection or alter repetition or global history.

The runtime must not require all prepared images to remain decoded in memory.

### Recovery and missing content

On startup, Refrain first attempts to recover the committed operational selection.

The content library does not override a valid committed snapshot.

If the original YAML entry has been removed, renamed, or modified, the current selection remains unchanged.

Missing or invalid original content does not prevent recovery when the committed snapshot is valid and its presentation resources can be resolved.

If selection commitment was interrupted, Refrain must recover the last valid operational state and repeat selection when necessary.

If rendering or image persistence was interrupted after commitment, Refrain resumes or repeats preparation using the same committed snapshot.

Image regeneration may use a bundled fallback font if the selected font is no longer available. Exact pixel reproduction is not required when font resources have changed.

If no usable font resource can be resolved, the application must report the preparation failure rather than silently substitute an arbitrary system font.

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

Prepared images remain recoverable from the committed snapshot and available font resources, but pixel-identical reproduction is not guaranteed after changes to installed fonts.

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

Without a committed selection, the evaluator calculates the initial display date in the configured IANA timezone. With a committed selection, a difference between the current date and the snapshot's display date does not authorize reselection. A `DisplayDayBoundary(display_date, state_revision)` observation identifies the resulting display date and the selection revision active when it was observed; after that revision is replaced, the observation is stale. Evaluations are pure; they do not select content, persist state, prepare images, or operate a display.

`refrain.resolve_reveal_stages(snapshot)` returns the canonical ordered `CompositionVisibility` sequence for a committed snapshot. The coordinator must pass this same sequence to image preparation and recovery; scheduling evaluation derives its required stage index from that sequence. Simultaneous reveal times share a stage, fields scheduled at the quotation time appear in stage zero, and source and attribution may reveal in either order. The final stage includes every available optional field.

`refrain.DisplayDayBoundaryObserver` recognizes only transitions observed during the current process lifetime. Its first timestamp establishes a baseline, a backward wall-clock adjustment resets that baseline without creating a boundary, and a forward jump produces at most one boundary for the currently appropriate display date. An already pending observation remains available across a clock adjustment while its associated selection revision remains current; backward adjustments do not replace it with an earlier date, while a later observed forward transition supersedes it with the currently appropriate date. The observer returns the same pending observation on repeated calls while that revision and date remain current; observing a later revision expires it. A failed selection commit therefore leaves the event available for retry, while a successful commit makes it stale to `evaluate_scheduling()`. The observer does not persist clock history; after an interruption, an isolated timestamp cannot establish that a boundary occurred, so startup continues to follow the conservative recovery policy above.

`refrain.next_scheduling_deadline(current_time, configuration, state)` returns the next applicable committed reveal time or configured display-day boundary. `refrain.wait_for_scheduling_event(deadline, wake_event, ...)` waits for that deadline or an external wake event and returns control for reevaluation after a detected wall-clock adjustment. The coordinator remains responsible for calling `evaluate_scheduling()` and executing its decisions; observation and waiting do not select content, mutate persistent state, prepare images, or operate a display.

The application coordinator executes returned decisions through the selection, persistence, preparation, and display components. For a committed selection, the required reveal stage is the later of the stage implied by the snapshot's resolved schedule in its recorded timezone and the persisted highest stage. Missing optional fields do not add reveal stages, and missed reveal times can advance directly to the latest applicable stage. A persisted stage beyond the sequence's final index is invalid and evaluation raises `SchedulingEvaluationError`.

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

Refrain separates view-specific background composition from literary content rendering.

A background generator produces a base image containing the visual elements owned by that view, including decorative elements, branding, diagnostic information, and other content outside the literary composition.

The shared quotation renderer accepts a background image and a literary composition consisting of:

- a required quotation;
- optional source information;
- optional attribution information.

The renderer owns the typography, fitting, positioning, and drawing of all three fields within an explicitly supplied presentation region.

The renderer is independent of the purpose of the background image. It does not read application configuration, select content or fonts, access selection history, or determine application lifecycle policy.

For normal daily presentations, the presentation region is resolved from application configuration. Other views may supply their own presentation region without changing the renderer's behavior.

The same quotation renderer serves normal daily presentations, the information view, and potential future diagnostic views.

The renderer does not require a content-library entry or committed daily snapshot as its input. Callers supply the resolved content and presentation parameters appropriate to the view.

The architecture does not require a general-purpose layout framework, externally supplied rendering components, or a plugin interface.

For daily images, preparation generates a paper-white background independently of literary rendering. The background contains no quotation, source, or attribution text.

### Information view

Refrain will provide an information view presenting application identity and selected diagnostic information in a format consistent with its quotation-based visual design.

The information view contains:

- a curated, application-owned quotation associated with the running release;
- optional source and attribution identifying the quotation's context;
- the Refrain and ControlForge project identity;
- application version and available build or commit information;
- selected runtime and environment details where available;
- an appropriate copyright notice.

The curated literary content is not drawn from the user content library and does not participate in daily selection, priority, repetition history, or global selection history.

The information-view background generator owns branding, diagnostic information, and other non-literary presentation elements.

The shared quotation renderer presents the curated quotation and its optional source and attribution using the same composition and typography facilities as normal daily quotations.

The literary composition remains visually primary. Branding and diagnostic information are subordinate and should not compromise readability.

The information view is independent of the committed daily selection. Displaying it does not create a new selection, modify selection histories, or advance reveal progress.

The information view may be requested independently of automatic presentation behavior.

Application configuration will provide an optional automatic-display duration. A duration of zero disables automatic presentation without disabling the information view itself.

An unavailable optional diagnostic value must not prevent the information view from being rendered.

### Initial visual design

The initial release provides one configurable presentation layout.

Its intended appearance is that of a carefully typeset printed page rather than a conventional electronic interface.

The design prioritizes:

- readable typography;
- generous whitespace;
- restrained visual decoration;
- a predominantly paper-white background;
- dark text with optional color accents.

The layout defines a bounded rectangular presentation region containing the complete literary composition: the quotation and its optional source and attribution.

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

The presentation region is configurable using resolution-independent coordinates.

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

Refrain maintains an effective font registry containing bundled application fonts and fonts explicitly registered in application configuration.

Application configuration defines a nonempty default font pool using stable identifiers from the effective registry.

Bundled font identifiers are reserved and cannot be overridden by application configuration. Every explicitly registered user font must be valid and loadable. An invalid user-registered font is an application configuration error.

A content entry may specify a preferred font, inherited by every quotation in that entry.

When the preferred font is present in the effective registry, Refrain uses it for the selected quotation.

When a content entry requests an unregistered font, Refrain retains the otherwise valid entry, logs an appropriate warning, and selects a font from the configured default pool.

Content entries that omit a font preference also use the default pool.

Each font in the default pool has equal selection probability.

Font selection is independent for each daily selection. Fonts do not have repetition histories, and a font may be used on consecutive days.

The selected font identifier is resolved after quotation selection and before daily snapshot commitment.

The selected font identifier is recorded in the committed snapshot and global selection history. Font contents and font-content hashes are not persisted in operational state.

Image preparation resolves the selected identifier using the available font registry.

If the selected font is no longer available or usable during regeneration, Refrain uses an available bundled fallback font. Fallback selection is deterministic for a given set of available bundled fonts and is consistent across all stages prepared together.

If no usable bundled fallback exists, preparation fails with an actionable diagnostic.

Existing valid prepared images are not invalidated solely because installed font resources have changed.

### Stable progressive layout

The renderer resolves the complete literary composition using the quotation and every available source and attribution field, regardless of the current reveal stage.

The configured presentation region remains unchanged throughout the committed selection.

The resolved layout establishes the positions, typography, wrapping, and spacing of all present fields.

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

Content that cannot be rendered legibly within the supported presentation region must be handled explicitly rather than silently clipped, truncated, or omitted.


### Committed daily presentation data

A daily snapshot must contain the selected quotation, its presentation metadata, effective reveal schedule, selected font identifier, and resolved layout values needed to prepare the presentation without consulting the original content library or current presentation configuration.

`presentation_metadata` contains optional nonempty `source` and `attribution` strings, plus the required built-in `presentation_style` (`centered` or `left-aligned`). An absent optional field is represented by a missing key or `null`.

`layout` contains:

- `image_size`: a two-item sequence of positive integer pixel dimensions in width, height order;
- `presentation_region`: a normalized rectangle with `x`, `y`, `width`, and `height`;
- `min_font_size` and `max_font_size`: positive integer quotation font-size bounds, with the maximum no smaller than the minimum.

The snapshot stores the selected font identifier, not the font's binary contents or a digest of those contents.

Daily preparation uses the shared renderer's `1.20` quotation–byline spacing factor and deterministic `pixel-distortion` concealment; these are not current-configuration fallbacks.

Font resources are resolved through the available registry during preparation. If the selected identifier cannot be used, regeneration may use a deterministic bundled fallback while preserving the committed quotation, metadata, reveal schedule, and layout configuration.

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

Regeneration resolves the selected font identifier through the available font registry and may use a bundled fallback if the originally selected font is unavailable or unusable.

Recovery must not change the selected quotation, presentation metadata, reveal schedule, or committed layout configuration.

Exact pixel reproduction is not required when installed font resources have changed. Existing valid prepared images remain reusable independently of those changes.

If image generation fails, the application must report the error and preserve the existing display image where practical.


### Rendered-image comparison

The application should avoid unnecessary physical refreshes when the required prepared image has not changed.

The display scheduler and backend remain independent of the renderer.

Normal scheduled updates select among prepared images rather than invoking image composition.

## Display output

### Backend responsibility

Refrain presents complete rendered images through a narrow, hardware-independent display backend interface.

A display backend provides two operations:

- `update(image)` presents a complete Pillow image through the configured output destination.
- `close()` releases resources owned by the backend.

The application selects one built-in backend through validated runtime configuration. Backend selection occurs at application startup and does not require modifications to application code or replacement of installed modules.

Version 0.1 provides three built-in display backends:

- `window`: Presents complete images in a graphical desktop window.
- `waveshare-13in3-e`: Presents complete images on the supported Waveshare 13.3-inch e-Paper HAT+ (E).
- `image-server`: Makes the current complete image available to network clients through a read-only HTTP service.

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

The Waveshare backend accepts complete RGB 1200 × 1600 portrait and 1600 × 1200 landscape images; images with alpha or palette transparency are unsupported. It converts the complete image before initializing the controller and verifies that conversion produced exactly 960,000 packed elements. Each valid update initializes the controller, transfers the complete image, and returns the controller to sleep. It does not clear the display before an update or during shutdown. `close()` is repeatable and sleeps the controller only when an update has left it active.

The image-server backend owns an HTTP service that exposes the most recently accepted complete image. Its publication and lifecycle responsibilities are defined separately below.

The common interface does not expose hardware-specific initialization, SPI, GPIO, controller commands, refresh mechanisms, or network transport operations.

The backend validates image compatibility with its destination rather than silently resizing or otherwise changing the prepared presentation.

A completed `update()` indicates that the backend's presentation operation completed successfully. For a network image service, this means the replacement image is available to clients, not that any client has retrieved or displayed it.

Failures and uncertain hardware outcomes must remain distinguishable where the underlying implementation permits.

Display backends must not perform quotation selection, reveal scheduling, image preparation, or persistent-state updates.

Backend implementations are built-in application components. Version 0.1 does not define a general display plugin system.

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

Physical display updates occur at meaningful presentation changes, including:

- the beginning of a new display day;
- scheduled progressive reveals;
- recovery when a valid desired image has not been successfully presented.

Refrain does not require continuous physical refresh or animation.

Display updates must be coordinated so that overlapping operations cannot corrupt communication with the device.

For the image-server backend, an update replaces the currently available image representation. Network clients retrieve that representation independently of the application's scheduling operations.

### Failure handling

A display-update failure must be reported with sufficient diagnostic context.

Transient failures may be retried using a bounded recovery policy.

Retries must not indefinitely block scheduling or prevent the application from recognizing a newer desired presentation.

The application must distinguish a known successful update from a failed or uncertain update where the hardware API permits.

An uncertain hardware result must not be treated as proof that the desired image was successfully displayed.

For the image-server backend, unsuccessful image preparation or replacement must not expose incomplete content or invalidate the previously accepted image.

Individual network-client failures do not constitute display-backend update failures. The backend does not require clients to retrieve or acknowledge published images.

The exact retry parameters and hardware lifecycle behavior are engineering decisions informed by the relevant output destination.

### Retained display content

E-paper retains its visible image without continuous power.

Refrain should preserve useful displayed content across temporary application and hardware failures when possible.

It must not clear a physical display merely because a recoverable software problem occurred.

The image-server backend retains the last successfully accepted image while the backend remains operational. It does not independently persist that representation across application restarts.

Network clients are responsible for retaining their displayed content during temporary network or application unavailability.

## Application lifecycle

### Startup

Normal startup performs the following logical operations:

1. Load and validate configuration.
2. Recover persistent application state.
3. Load and validate the content library as required for future selections.
4. Recover the current committed daily snapshot, if one exists.
5. Evaluate whether the recovered selection remains active under the display-day transition rules.
6. Perform and commit a new selection if required.
7. Verify that all required reveal-stage images are available and valid.
8. Prepare or recover any missing presentation artifacts.
9. Determine the currently required reveal stage, respecting previously reached progression.
10. Initialize the display backend and present the required prepared image when necessary.
11. Continue operating until shutdown.

Recovery of a valid committed selection must not depend on successful reloading of its original content entry.

The implementation may organize these operations differently provided their externally observable behavior is preserved.

### New daily selection

At a recognized display-day transition, the application:

1. Determines the new display date.
2. Performs eligibility, repetition, priority, and random quotation selection.
3. Creates the complete daily snapshot.
4. Atomically commits the snapshot, global-history append, and repetition-history update.
5. Generates and persists every required reveal-stage image.
6. Determines the stage appropriate to the current time.
7. Presents the corresponding prepared image.

The selection is complete at commitment, independently of whether image preparation or display communication subsequently succeeds.

A failure after commitment must not trigger reselection.

### Normal operation

After successful preparation, the application waits for the next meaningful scheduling event.

Scheduled reveal updates select an existing prepared image.

Normal operation must not require repeated content-library access or repeated rendering.

Clock adjustments are evaluated according to the display-day and reveal-progression rules.

The application must not rely on busy waiting to determine ordinary reveal times.

### Recovery

Recovery is performed according to the stage at which an interruption occurred.

An interruption before selection commitment permits selection to be repeated.

An interruption after commitment preserves the committed selection.

Missing or incomplete prepared images are regenerated from the committed snapshot.

Display failures are retried according to the display backend's recovery policy.

Recovery must not introduce additional history entries or silently substitute content.

### Shutdown

Normal shutdown must safely release owned software and hardware resources.

Shutdown must not intentionally erase the retained e-paper image.

Committed selection state and prepared presentation images remain available for subsequent startup recovery.

### Failure isolation

Recoverable hardware failures must not invalidate content selection or persistent history.

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
9. Repetition identities absent from a successfully validated complete content library may be removed without affecting committed selections.
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
