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

Preparation generates and persists all images required for the committed selection and its configured output specifications.

Scheduling determines which reveal stage should currently be presented.

Display output publishes the prepared image variant appropriate to each configured destination.

Each responsibility must remain independently understandable and testable.

### Preserve future flexibility without implementing future features

The initial architecture must not assume that content can only originate from song lyrics or that a physical display is the only possible presentation destination.

Future web presentation, public publishing, and external actions must be possible without replacing the core quotation-selection model.

These capabilities must not be implemented merely to demonstrate extensibility.

## Target platform

The initial hardware deployment targets:

- Raspberry Pi OS Lite;
- Python;
- Waveshare 13.3-inch e-Paper HAT+ (E), with its native 1600 × 1200 landscape panel.

The Raspberry Pi 3B+ is the minimum supported Raspberry Pi platform for Version 0.1 and the initial hardware-validation platform.

The application must not depend on performance, memory capacity, peripheral availability, or other characteristics exclusive to the Raspberry Pi 3B+.

The display uses Spectra 6 color e-paper technology.

The intended presentation is predominantly black typography on a paper-white background. Color is available for restrained decorative use.

The initial display is a full-frame output device. Refrain must not depend on partial refresh, animation, or frequent screen updates.

The renderer must produce images independently of the display backend and physical display characteristics. Backend-specific orientation and pixel format do not constrain the renderer's supported presentation aspects or requested raster resolutions.

Hardware-independent content, selection, scheduling, persistence, and rendering components must remain portable across operating systems supported by the Python runtime and required dependencies, without unnecessary operating-system-specific assumptions. This permits their development and testing on non-Linux systems but does not imply that full application deployment has been validated or is supported there.

The display backend owns hardware-specific integration, including the Waveshare driver and its platform dependencies.

Support for additional display hardware is not an initial product requirement, although display resolution, supported color capabilities, and hardware-specific operations must remain isolated from core content and scheduling logic.

The runtime should avoid unnecessary memory use and background processing. Quality decisions for infrequent daily image preparation must not be rejected solely because they require additional processing.


## Terminology

**Content Entry:** A uniquely identified collection of one or more quotations and shared configuration metadata.

**Quotation:** An individual message contained within a content entry. Quotations are the units of daily selection and repetition tracking.

**Quotation Identity:** The normalized text of a quotation, used to determine whether the same message has previously been selected.

**Content Library:** The validated collection of available content entries.

**Display Day:** The logical presentation interval determined by host-local time and Refrain's configured day-start time.

**Display Date:** The local calendar date associated with a daily selection. This date determines content eligibility.

**Date Specificity:** The degree to which an eligibility rule identifies a particular calendar date, ordered from most to least specific: year-month-day, month-day, day, month, and ordinary eligibility.

**Selection Pool:** The quotations eligible within the highest matching date-specificity context for a particular display date.

**Priority:** An optional signed integer associated with a content entry and inherited by its quotations. Higher values indicate greater selection preference. The default is zero.

**Selection Revision:** A monotonically increasing identifier assigned to each committed daily selection and maintained in authoritative operational state.

**Global History:** A chronological, retention-bounded record of committed quotation selection events, maintained independently of authoritative operational state.

**Repetition History:** A persistent but selectively resettable collection of quotation identities used to prevent repetition until an eligible selection pool is exhausted. Identities no longer present in the validated content library may also be removed.

**Daily Selection:** The individual quotation assigned to the current display day.

**Daily Selection Record:** A persistent copy of the selected quotation and the content properties needed to interpret it, independent of the original content entry. Rendering resources and settings are resolved during image preparation.

**Selection Commitment:** The successful durable recording of a daily selection, updated repetition history, selection revision, reveal progress, and scheduling context as one consistent authoritative state.

**Reveal Stage:** A cumulative set of content fields eligible for presentation at a particular point in the configured reveal schedule.

**Presentation Aspect Ratio:** The declared ratio that selects the design canvas and determines the exact-ratio dimensions of the presentation canvas.

**Design Canvas:** The high-resolution, aspect-specific graphical composition and authored-layout space selected from the fixed 3840 × 2400 reference envelope. It is independent of requested output resolution.

**Presentation Canvas:** The raster on which literary layout, text, QR, and diagnostic overlays are resolved and rendered for one output specification.

**Output Image:** The completed presentation canvas, optionally resized once as a whole to the exact requested dimensions. It is the image persisted as a prepared PNG and delivered to display backends.

**Output Specification:** The declared presentation aspect ratio and requested output resolution for a configured destination, according to that backend's configuration and defaults.

**Destination Identifier:** The runtime-supplied opaque identifier for one configured output destination. It is used only to route a runtime-control request.

**Prepared Image:** A persisted output image representing one reveal stage of the committed daily selection for one output specification. Destinations with identical output specifications may share it.

**Presentation:** The selected quotation, associated metadata, reveal schedule, and applicable layout configuration used to produce prepared output images.

**Renderer:** The hardware-independent component responsible for composing complete presentation images.

**Display Backend:** The component responsible for presenting the prepared output image matching its configured output specification through a destination, including directly connected display hardware or a network-accessible image service.

**Persistent State:** The authoritative operational state containing the current daily selection, selection revision, active repetition history, reveal progress, and scheduling context required for recovery across application restarts.



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
Daily selection record + updated repetition history
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
Persisted output variants for every reveal stage
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

A new selection becomes authoritative only when its daily selection record, updated repetition history, selection revision, initial reveal progress, and required scheduling context have been durably committed as one consistent operational state.

An interrupted or unsuccessful operational-state commitment leaves the proposed selection incomplete.

Once commitment succeeds, the selection remains authoritative independently of subsequent image preparation, display updates, or global-history recording.

Each committed selection is eligible for recording in global history. Global-history recording is best-effort and does not participate in the authoritative operational-state transaction.

Failure to record global history must not cause a committed quotation to be selected or committed again.


### Preparation

Preparation resolves the unique output specifications required by configured destinations and generates a complete prepared output image for every required reveal stage and output specification.

Destinations with identical output specifications share the same prepared output images. Prepared images are persisted independently of the content library.

Preparation does not modify the committed selection or its selection histories.

### Presentation

The display scheduler determines which reveal stage should currently be presented. Each destination receives the prepared output image matching its output specification.

Normal scheduled reveals do not invoke the renderer or consult the content library.

The display backend owns physical display communication and recovery.

The committed daily selection remains authoritative when prepared images need to be recovered.

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

Logical-date evaluation orders the current instant and resolved display-day boundaries as timezone-aware instants, not solely by their local `HH:MM` values.

Changing the host timezone is an operating-system operation. Refrain does not need to adapt its scheduling while running; restarting afterward is acceptable. At the next scheduling evaluation, the current host-local logical display date determines whether the committed selection remains active. Reveal progression does not move backward while that logical date remains unchanged.

Clock changes must be handled according to the established display-day transition and reveal-progression policies.

### Day-start configuration

The display day begins at a configured local time.

For example, with a configured start time of 06:00, a display day normally begins at 06:00 and remains active until the following configured day-start boundary.

The local calendar date associated with a new selection determines its special-date eligibility.

### Daily selection stability

A committed daily selection remains authoritative while its display date matches the current logical display date.

Whenever the current logical display date differs from the committed selection's display date, Refrain establishes a new selection for the current logical date. This rule applies during continuous operation, after restart, and after either forward or backward clock adjustments. It does not depend on observing a particular boundary crossing.

Repeated scheduling evaluations for the same committed logical date must not generate duplicate selections. Display failures, content-library changes, and missed reveal events do not independently trigger reselection.

When the logical date is unchanged, the existing selection remains authoritative and its reveal progression never moves backward. A transition to another logical date establishes a new selection and reveal progression, even if a quotation was previously selected for that date.

### Forward clock adjustments

The current logical display date is calculated from resolved day-start boundaries as defined under Logical-date evaluation. When the clock advances within that logical date, Refrain advances to the reveal stage appropriate to the new time.

Missed intermediate reveal stages are not presented sequentially.

When the logical display date differs from the committed selection's date, Refrain selects a quotation for the current logical date, including after a forward jump across one or more day-start boundaries.

Skipped display dates do not require retrospective selection or presentation.

For example, if the clock advances from October 17 to November 28, Refrain selects content for November 28 and presents the appropriate reveal stage.

### Backward clock adjustments

Moving the clock backward does not reverse reveal progression while the logical display date remains unchanged.

If the backward adjustment changes the logical display date, Refrain establishes a new selection for that date.

With `day_start: "06:00"`:

- Monday 07:00 to Monday 03:00 changes the logical date from Monday to Sunday and establishes a new selection.
- Monday 15:00 to Monday 10:00 keeps the same logical date and selection; reveal progress is retained.
- Monday 23:00 to Tuesday 02:00 keeps the same logical date and selection.
- Tuesday 02:00 to Tuesday 07:00 changes the logical date from Monday to Tuesday and establishes a new selection.

Moving to another logical date does not reverse or remove prior selection or history records. The new selection has its own reveal progression.

### Logical-date evaluation

The logical display date is the local calendar date associated with the most recent resolved day-start boundary not later than the current instant.

Resolve the configured day-start for the current host-local calendar date using the Local time rules: an ambiguous wall time uses its first occurrence, and a nonexistent wall time uses the first valid local instant after the gap. Compare the current instant with that resolved boundary using timezone-aware instant ordering. At or after the boundary, the logical display date is the boundary's local calendar date; otherwise, it belongs to the preceding resolved display-day boundary. Do not determine whether the boundary has passed using only a local wall-clock-value comparison.

On ordinary dates, this remains equivalent to the intuitive rule: before `day_start`, use the preceding local calendar date; at or after `day_start`, use the current local calendar date.

For example, with `day_start: "06:00"`, Monday 05:00 has logical display date Sunday, and Monday 07:00 has logical display date Monday.

During a fall-back transition with `day_start: "01:30"` inside the repeated interval, the first occurrence of 01:30 is authoritative. Both the interval after that occurrence and before the fold, and the second occurrence of 01:15, belong to the new logical display date: the resolved boundary has already passed in absolute time. The repeated hour must not temporarily regress the logical date or create extra selections or history records. During a spring-forward gap containing the configured day-start, the preceding logical date remains active until the first valid local instant after the gap.

On startup and during ordinary scheduling, compare this date with the committed selection's display date. A mismatch requires one new selection for the current logical date; skipped dates do not require retrospective selections. The committed date and day-start context are sufficient for this comparison. Do not require a boundary-observation event, retain an outdated selection because a boundary was not observed, or persist or infer clock-observation history.

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

When multiple occurrences of the same quotation remain eligible, the selected occurrence determines the metadata included in the daily selection record.

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
13. Preserve the selected occurrence's semantic metadata, effective reveal schedule, presentation style, and declared content preferences needed to interpret or present the quotation.
14. Prepare the daily selection record.
15. Atomically commit the daily selection record, updated repetition history, next selection revision, initial reveal progression, and required scheduling context as authoritative operational state.
16. Record the committed selection in global history on a best-effort basis.

Selection is not complete until operational-state commitment succeeds.

An unavailable or empty effective content library cannot produce a new selection and must not trigger repetition-history cleanup.

A failed or interrupted operational-state commitment permits the selection procedure to run again.

Failure to record global history after commitment does not invalidate the committed selection or permit another selection for the same committed event.

The next selection revision is derived from authoritative operational state, never from global-history contents.

Visual resources and rendering decisions are resolved during preparation, not selection commitment.

Selection policy must not depend on file enumeration order or incidental filesystem behavior.

## Persistent state

### Required persistence

Refrain maintains sufficient durable operational state to preserve:

- the current committed daily selection and its monotonically increasing revision;
- the display date associated with that selection;
- the selected quotation's original text;
- the selected content identity, optional source and attribution, and content properties needed to interpret or present the quotation;
- the effective reveal schedule and scheduling context needed to resume it;
- active repetition history;
- the highest reveal stage reached for the current selection;

Refrain separately maintains a chronological global history of selection events.

Operational state is authoritative for selection, scheduling, reveal progression, and recovery. Global history is historical information and is not required for normal operation.

After commitment, the active selection must not require access to the original YAML content entry.

### Daily selection record

The daily selection record contains a complete copy of the selected quotation and the semantic content properties needed to apply its reveal behavior without consulting the original content library.

It includes the selected entry identity and quotation identity, the selected quotation's original text, optional source and attribution, effective reveal schedule, display date, and any selected content preferences needed to interpret or present the quotation. These captured preferences remain authoritative for this selection; later edits to the source entry do not replace them, and recovery never rereads that entry to obtain them. The record does not contain other quotations from the entry.

The record is not a serialized rendering plan. Do not store output dimensions, design-canvas geometry, resolved literary rectangles, selected fonts or faces, resolved colors, selected background or decoration resources, tintability decisions, resolved QR policy or placement, layer transformation geometry, or other derived rendering values solely to reproduce previously generated pixels. The captured content-level preferences are resolved against current application configuration and available assets when images are prepared.

Only the current prerelease operational-state schema is supported. Do not maintain readers, migrations, rendering branches, or tests for earlier internal schemas. A numeric discriminator is not required unless technically necessary; if retained, its current prerelease value is `1`. Incompatible or invalid state must produce an actionable diagnostic reflecting the effective state-file location; it must not silently replace the selected content or modify the state file. For a platform-standard state path, the diagnostic may direct the operator to stop Refrain and run `refrain --reset`. For a configured state path outside the standard location, identify that path and direct the operator to stop Refrain and manually back up and remove or quarantine only that file; `--reset` does not manage custom paths.

Selection commitment does not depend on resolving visual resources.

Content-level presentation preferences remain part of the selected record when needed to preserve the selected entry's intended behavior. They are preferences for future preparation, not resolved rendering decisions.

The daily selection record is immutable after commitment except for monotonic reveal progress and the scheduling context required by the display-day model.

Prepared images are disposable derived artifacts. Regeneration preserves the selected content and reveal progression but may reflect current configuration, assets, fonts, colors, layout, and QR policy.

### Global history

Global history is a chronological record of committed quotation selection events, independent of authoritative operational state.

Each record identifies the selection revision and logical display date and preserves:

- the selected quotation text;
- its normalized repetition identity;
- the time at which the selection was made.

Selection revisions increase monotonically and are maintained in operational state. They are not derived from global-history records.

Global history records selection events rather than unique display dates. Multiple selections associated with the same logical display date remain distinct records, including selections resulting from clock adjustments.

Global history is independent of the containing entry's identifier, source, attribution, priority, and eligibility rules for repetition purposes.

Global history is append-only during normal recording. Recorded events are not modified or removed when repetition pools are exhausted.

Global history has bounded retention. Its rotation mechanism and fixed retention limits are defined in `docs/ENGINEERING.md`. Discarding older records does not affect operational state or future selection revisions.

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

- the complete daily selection record;
- the updated repetition history;
- the identity and scheduling context of the committed selection;
- initial reveal progression.

These values form one consistent operational-state update.

A new selection revision is derived from the preceding operational-state revision, independently of global history.

An interrupted operational-state update must recover to either the preceding valid selection or the newly committed selection.

A partially written or invalid daily selection record must not be treated as a completed selection.

Once an operational selection has been committed, failure to prepare images, update the display, or append global history must not cause the same selection to be committed again.

Global-history recording follows successful selection commitment but is not part of the authoritative operational-state transaction.

The persistence mechanism must provide reasonable protection against incomplete writes and interrupted replacement.

The exact storage formats, rotation mechanics, and persistence operations belong to engineering.

### Prepared images

After selection commitment, Refrain resolves current presentation configuration, available resources, and the unique output specifications required by configured destinations. It generates every required reveal-stage image for each specification.

Variants for all required output specifications are a coherent prepared presentation. Presentation-wide choices are resolved consistently across variants; raster-dependent layout and rendering results are resolved independently for each variant.

For each output specification, the prepared images form an ordered reveal-stage set. Images within that set have the same expected output dimensions and compatible image mode; different output specifications may have different dimensions and raster-dependent results.

Prepared images are persisted on disk and associated with the committed selection and their output specifications.

They are derived artifacts, not independently authoritative application state.

Prepared images must remain associated with the committed selection revision and expected reveal-stage sequence.

A complete, valid set is reused throughout ordinary operation and after application restart. Changes to configuration or assets do not by themselves invalidate or regenerate it.

If required variants are absent, damaged, incomplete, or unusable, prepare the complete stage sets needed for the current output specifications from the durable current selection using currently available configuration and assets, then safely publish complete usable artifacts. A changed output requirement may therefore add variants to an existing committed presentation.

All output variants prepared together use one consistent set of presentation-wide choices, including selected font identity, background, decoration, and colors. Each variant independently resolves raster-dependent font pixel sizes, line wrapping, geometry, QR viability and module size, and conditional QR/no-QR decoration behavior. Within one output specification, its complete literary composition determines stable geometry for every reveal stage; this does not require different specifications to share geometry.

When output requirements change, any newly required variants are prepared from the existing committed selection without changing the quotation or reveal progress. Variants may share preparation-wide choices; if existing cached variants cannot form a consistent required set with new variants, regenerate the required set coherently. Regeneration may change visual appearance but must not trigger selection, change repetition history, or move reveal progression backward.

The runtime must not require all prepared images to remain decoded in memory.

### Recovery and missing content

On startup, Refrain first attempts to recover the committed operational selection.

The content library does not override a valid committed daily selection record.

If the original YAML entry has been removed, renamed, or modified, the current selection remains unchanged.

Missing or invalid original content does not prevent recovery when the committed daily selection record is valid.

If selection commitment was interrupted, Refrain must recover the last valid operational state and repeat selection when necessary.

If rendering or image persistence was interrupted after commitment, Refrain regenerates the complete stage set using current configuration and available resources. Existing fallback and diagnostic policies apply to unavailable or invalid resources.

If current operational state is incompatible, unavailable, or invalid, report an actionable diagnostic identifying the effective state-file location. For a platform-standard state path, the diagnostic may direct the operator to stop Refrain and run `refrain --reset`. For a configured path outside the standard location, direct the operator to stop Refrain and manually back up and remove or quarantine only that file; do not suggest `--reset` for a custom path. Do not modify the state or silently substitute another quotation. Valid current-format state remains recoverable.

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
- the immutable daily selection record;
- monotonic reveal progress;
- scheduling context needed for recovery.

Global history owns chronological historical selection records but does not determine operational behavior.

Prepared images are disposable cache entries derived from the current daily selection, its reveal stages, the required output specifications, and the configuration and resources available when the variants were prepared.

The appropriate reveal stage is initially determined by the committed schedule and current time.

Within a committed selection, reveal progress must not move backward.

The currently required stage is therefore the later of:

- the stage required by the current time;
- the highest stage already reached for the committed selection.

Reveal progression must survive application restarts while the committed selection's display date matches the current logical display date.

Prepared images are reused without checking for configuration or asset changes. If a set is unusable, regenerate it completely from current inputs; exact visual reproduction is not a requirement.

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

The effective schedule is resolved before the daily selection record is committed.

Subsequent changes to global configuration or the original entry do not alter the committed schedule.

Reveal schedules must be validated to prevent impossible or contradictory behavior.

Reveal timing is evaluated relative to the logical display day associated with the selection.

### Stage preparation

After selection commitment, Refrain prepares all images required by the effective reveal schedule for every required output specification.

Each image represents one cumulative reveal stage for one output specification.

All variants generated together use the same selected content and consistent presentation-wide choices. Raster-dependent layout and rendering results are resolved independently for each variant.

Normal scheduled progression uses these prepared images.

The renderer is not invoked separately for each reveal event during ordinary operation.

If preparation fails, Refrain retains the committed selection and retries preparation without selecting different content.

### Startup and missed events

On startup, Refrain recovers the committed selection and its highest previously reached reveal stage.

The active stage must be at least the previously reached stage.

If the current time requires a later stage, Refrain advances directly to it.

Missed intermediate stages do not need to be displayed sequentially.

A restart retains the committed selection and reveal progression when its display date matches the current logical display date. If the date differs, startup establishes a new selection for the current logical date with its own reveal progression.

### Clock changes

Forward clock adjustments may advance the current reveal stage immediately.

Backward clock adjustments must not cause previously revealed fields to become hidden.

Reveal progression remains monotonic within the lifetime of the committed selection.

When a new daily selection is committed, reveal progress begins according to that selection's applicable schedule and current time.

Clock adjustments that establish a new display day follow the rules defined in the display-day model.

### Scheduling and display

The hardware-independent scheduling evaluator determines whether an initial or new selection is required, the display date for that selection, and the required reveal stage for a committed selection. It accepts an explicit timezone-aware current timestamp, application configuration, and recovered persistent state.

The public interface is `refrain.evaluate_scheduling(current_time, configuration, state)`. It returns an immutable `SchedulingDecision` whose `SchedulingAction` is `INITIAL_SELECTION`, `NEW_SELECTION`, `ADVANCE_REVEAL`, or `NO_ACTION`. Initial and new selections include `display_date`; decisions for a committed selection include `required_reveal_stage`. Invalid inputs raise `SchedulingEvaluationError` rather than producing a guessed date.

The evaluator calculates the current logical display date from resolved host-local day-start boundary instants as defined under Logical-date evaluation, using `general.day_start`. With a committed selection, a different logical date requires a new selection for that date; the same date retains the selection and advances reveal progress monotonically. Repeated evaluation for one committed logical date does not request another selection. Evaluations are pure; they do not select content, persist state, prepare images, or operate a display.

`refrain.resolve_reveal_stages(selection)` returns the canonical ordered `CompositionVisibility` sequence for a committed daily selection. The coordinator uses this same sequence for image preparation and cache validation; scheduling evaluation derives its required stage index from that sequence. Simultaneous reveal times share a stage, fields scheduled at the quotation time appear in stage zero, and source and attribution may reveal in either order. The final stage includes every available optional field.

The former observer-dependent scheduling interface and behavior are superseded: `DisplayDayBoundary`, `DisplayDayBoundaryObserver`, and the `observed_boundary` argument to `evaluate_scheduling()` are not part of the required scheduling contract. Do not replace them with a boundary-history subsystem.

`refrain.next_scheduling_deadline(current_time, configuration, state)` returns the current time immediately when initial selection or a logical-date mismatch requires a selection; otherwise, it returns the next applicable committed reveal time or configured day-start time. `refrain.wait_for_scheduling_event(deadline, wake_event, ...)` waits for that deadline or an external wake event and returns control for reevaluation after a detected wall-clock adjustment. The coordinator remains responsible for calling `evaluate_scheduling()` and executing its decisions; waiting does not select content, mutate persistent state, prepare images, or operate a display.

The application coordinator executes returned decisions through the selection, persistence, preparation, and display components. For a committed selection whose logical date is unchanged, the required reveal stage is the later of the stage implied by its effective schedule in host-local time and the persisted highest stage. A new selection starts its own reveal progression. The scheduling context contains the display date and day-start time. Missing optional fields do not add reveal stages, and missed reveal times can advance directly to the latest applicable stage. A persisted stage beyond the sequence's final index is invalid and evaluation raises `SchedulingEvaluationError`.

When a reveal advancement is required, the coordinator publishes the corresponding prepared variant to each destination. Scheduling evaluation does not determine whether an image was successfully presented.

A failed display update does not invalidate the committed selection or its prepared images.

A subsequent successful update may skip intermediate stages and present the latest required image.

## Presentation and rendering

### Rendering independence

Daily-image preparation accepts a committed daily selection record and an explicit sequence of cumulative reveal stages.

Preparation resolves the selected content and current presentation settings, generates the view-specific background, and uses the shared renderer to produce complete images without accessing physical display hardware.

Neither preparation nor the renderer selects content, modifies selection history, or determines application lifecycle policy.

Rendered output must be testable and inspectable without Raspberry Pi display hardware.

### View composition

Daily-image preparation separates graphical composition from the shared literary renderer. The renderer owns the typography, fitting, positioning, and drawing of the quotation and its optional source and attribution within the resolved literary rectangle. It does not read application configuration, select content or fonts, access selection history, or determine application lifecycle policy.

#### Image spaces and output geometry

The literary presentation pipeline has exactly three primary image spaces: the design canvas, the presentation canvas, and the output image. They have distinct responsibilities and coordinate systems.

The fixed 3840 × 2400 reference envelope defines the maximum design area. The declared presentation aspect selects the corresponding centered design canvas by reducing only the dimension that exceeds the ratio:

| Aspect ratio | Design canvas | Reference-envelope crop |
|---|---:|---|
| 4:3 | 3200 × 2400 | 320 pixels from each horizontal edge |
| 5:3 | 3840 × 2304 | 48 pixels from each vertical edge |
| 16:9 | 3840 × 2160 | 120 pixels from each vertical edge |
| 16:10 | 3840 × 2400 | None |

The design canvas is the high-resolution, aspect-specific graphical composition and authored-layout space. It is independent of requested output resolution. Its operations are creation of the paper-white base; background scaling, cropping, and composition; decoration-layer composition, `contain`, `cover`, and `nine-slice` transformations; decoration tinting; and resolution of configured presentation geometry expressed in design-canvas units. Configured measurements use design-canvas units unless a field explicitly describes source-asset pixels.

Configured destinations resolve to output specifications, each comprising a declared presentation aspect ratio and requested output resolution. Backend-specific configuration and defaults determine these values; do not infer the declared ratio from requested dimensions. The presentation-canvas dimensions are derived from the specification and do not form part of artifact identity. When requested dimensions exactly match the declared ratio, the presentation canvas has those dimensions. Otherwise, it is the nearest positive integer-pixel resolution that exactly matches the declared ratio, using the existing deterministic nearest-raster and tie-breaking rules.

For a mismatched request, reduce the declared ratio to integer dimensions `(rw, rh)`, then compute `k = max(1, round_half_up((rw × requested_width + rh × requested_height) / (rw² + rh²)))`. The presentation canvas is `(rw × k, rh × k)`. This projected scale and half-up tie break define the nearest exact-ratio raster deterministically.

Scale the completed graphical composition from the design canvas as one image to the presentation canvas. Scale design-canvas presentation measurements into presentation-canvas coordinates using deterministic nearest-integer rounding, with exact half-pixel values rounded upward. Map rectangle edges independently; resolve shared boundaries once and assign any rounding remainder to an adjoining region to prevent gaps or overlaps. Reject non-finite, negative, out-of-bounds, or degenerate geometry before rendering.

When the requested resolution already matches the declared aspect, the presentation canvas is also the output image and no final resize is required. Otherwise, after all presentation-canvas composition is complete, resize that complete image once to the exact requested dimensions. This may intentionally distort the presentation. No layout, geometry resolution, text fitting or rendering, QR generation or composition, graphical composition, diagnostic annotation, or element-specific scaling or positioning occurs after this resize. Persist the resulting output image as the prepared PNG artifact and deliver it unchanged to the appropriate display backend, except for backend-owned hardware pixel-format or orientation conversion explicitly permitted by the backend contract.

Any transient geometry retained for diagnostics, including literary bounds, is expressed in presentation-canvas coordinates and is not authoritative application state. It does not become output-image geometry merely because the resulting PNG is persisted. When enabled for an aspect-mismatched output, draw diagnostic overlays on the presentation canvas before applying the same final whole-image resize as the displayed content.

For example, a declared 16:9 aspect and requested 1920 × 1080 resolution use a 3840 × 2160 design canvas, a 1920 × 1080 presentation canvas, and a 1920 × 1080 output image, with no final resize. A declared 4:3 aspect and requested 1600 × 1190 resolution use a 3200 × 2400 design canvas and the nearest exact 4:3 presentation canvas, 1596 × 1197. Background and decoration composition occurs on the design canvas; the completed graphical composition is scaled to the presentation canvas, where literary, QR, and diagnostic composition occurs before one complete-image resize. The output image is 1600 × 1190. No element is laid out or rendered in 1600 × 1190 coordinates.

#### Literary presentation geometry

Literary insets are design-canvas measurements, each measured inward from the corresponding design-canvas edge for the selected aspect ratio. Resolve the literary rectangle in design-canvas coordinates, then map its edges to the presentation canvas using deterministic nearest-integer, half-up rounding. Do not derive literary geometry from aspect-mismatched output-image dimensions.

Global layout insets provide the defaults. A selected decoration may replace them with a complete inset set for the current preparation. The resulting rectangle must have positive width and height and contain the complete literary composition. Resolve and scale the rectangle for the presentation canvas, then keep it unchanged across that output specification's reveal stages. Configured minimum and maximum literary font sizes are also design-canvas measurements; scale the effective bounds to presentation-canvas pixels with deterministic nearest-integer, half-up rounding before fitting and rendering. Quotation fitting and wrapping operate only in presentation-canvas coordinates. This fitting guarantee does not protect text from independently composited artwork or QR output. The renderer follows valid configured geometry without guaranteeing an aesthetically successful composite. The default configuration and bundled artwork must be designed and validated to avoid undesirable overlap; custom configuration and decoration authors are responsible for an acceptable composition.

Presentation insets are independent of decoration slice coordinates, PNG dimensions, and artwork transformations. Neither system determines or modifies the other.

#### Raster composition pipeline

Prepare each literary reveal-stage image in this order:

```text
source assets
    ↓
DESIGN CANVAS
    paper-white base
    background composition
    decoration composition
    authored/configured presentation geometry
    ↓
scale complete graphical composition
scale design-space presentation measurements
    ↓
PRESENTATION CANVAS
    literary-region geometry resolution
    literary fitting and rendering
    QR generation and composition
    diagnostic overlays
    ↓
optional whole-image resize only
    ↓
OUTPUT IMAGE
    persisted/published image
    no further presentation operations
```

For each output specification, resolve design-space QR placement, map its allocation to the presentation canvas, and determine effective QR availability before selecting conditional decoration layers. This decision accounts for the presentation-level QR policy, selected decoration's `qr_ready` value, valid in-bounds placement, and sufficient presentation-canvas pixels for a complete symbol with at least one pixel per module. Then compose the paper-white base, selected background, and conditionally active decoration PNG layers on the design canvas, processing layers in manifest order. Scale the completed graphical composition to the presentation canvas and map presentation measurements there. Resolve literary geometry and font bounds, fit and render the literary fields, then rasterize and composite QR when effectively available; draw diagnostic/debug overlays on the presentation canvas. If requested dimensions differ, resize the completed presentation canvas once as a whole; otherwise use it unchanged as the output image. Persist complete output images for every required reveal stage and output specification, then publish each destination's matching image through the existing backend architecture.

Every decoration PNG is behind all literary text and QR output. This pipeline does not introduce foreground composition phases, arbitrary z-index values, or a general layer-ordering engine. Each output specification's geometry and graphical composition remain stable across its reveal stages. Other views, including the information view, retain their separate composition and QR behavior while observing the same output-specification model.

#### Decoration layers

A selected decoration may contain an ordered sequence of PNG layers. Each layer has a source image, a required rendering method, optional parameters for that method, an optional QR-presence condition, and optional tintability metadata. Layers are composed in manifest order on the design canvas. The methods are `contain`, which aspect-preservingly scales the image to fit that canvas; `cover`, which aspect-preservingly scales the source directly to cover that canvas and crops excess artwork symmetrically around its center; and `nine-slice`, which adapts an image using four explicit source-image pixel distances. Cover does not first scale artwork to the reference envelope and has no positioning or alignment parameters. High-resolution artwork at 3840 × 2400 is preferred for full-canvas layers. Smaller custom PNGs may be enlarged by the selected method, but enlargement cannot restore image detail and may reduce visual sharpness. No alternate reference coordinate system or independent positioning is defined.

For `nine-slice`, the configured `left`, `right`, `top`, and `bottom` distances partition the source image directly into nine regions in its actual source-pixel coordinates. Reject non-integer, negative, overlapping, or out-of-bounds boundaries. Do not first scale the source into the reference envelope or scale its slice boundaries through that envelope. The configured distances are also the preserved edge thicknesses on the design canvas, numerically 1:1, regardless of the source image's overall dimensions.

Preserve corner widths and heights and horizontal- and vertical-edge thicknesses on the design canvas. Adapt only edge lengths according to their configured `stretch` or `crop` behavior; stretch the center region in both dimensions. `stretch` scales an edge segment along its length to fit. `crop` retains the segment's scale, centers it, and crops equally from both ends; it never crops the complete source image. If the requested crop destination is longer than the available source edge segment, reject the transformation instead of stretching it or leaving a gap. Reject a design canvas smaller than the combined opposing preserved edge thicknesses. Edge tiling is not supported.

For example, applying 20-pixel slices to a 1920 × 1200 source on a 3840 × 2400 design canvas preserves four 20 × 20 corners. The top and bottom center regions are 3800 × 20, the left and right center regions are 20 × 2360, and the center is 3800 × 2360. The source center and edge pixels are transformed to fill their destination regions according to the existing stretch/crop policy. Preserve source alpha through scaling and alpha composition.

#### Decoration tinting

Decoration-wide and per-layer `tintable` values both default to `true`. A layer is effectively tintable only when `decoration.tintable AND layer.tintable` is true. If at least one layer is effectively tintable, select one decoration color for the complete preparation using the first level with usable candidates:

1. The content entry's `decoration_color`.
2. The selected decoration's `decoration_color`.
3. The effective global `layout.decorations.colors` pool.
4. The built-in `black` fallback.

Select uniformly among distinct usable identifiers at the first applicable level; do not combine candidates from different levels. A successful color selection activates tinting; there is no separate activation state or configuration field. Apply the selected color to every effectively tintable layer, replacing RGB while preserving authored alpha, including antialiasing and transparency. When no layer is effectively tintable, do not resolve a decoration color. Artwork intended to retain authored RGB must set `tintable: false` at the decoration or layer level.

#### QR generation and conditional artwork

The presentation-level QR policy defaults to enabled and may be disabled. Resolve the QR allocation and placement in design-canvas coordinates, then map its four edges independently to presentation-canvas coordinates using deterministic nearest-integer, half-up rounding. This is a deliberate two-phase dependency:

```text
resolve design-space placement
        ↓
map allocation to presentation canvas
        ↓
evaluate effective QR availability
        ↓
select qr/no-qr conditional decoration layers
        ↓
compose graphical design on design canvas
        ↓
scale complete graphical composition to presentation canvas
        ↓
render literary content
        ↓
rasterize and composite QR
```

Effective QR availability is resolved on the presentation canvas for each output specification before selecting conditional decoration artwork. It is true only when the policy is enabled, the selected decoration's `qr_ready` value (default `true`) permits it, placement metadata is valid and the complete allocation remains within the design canvas, and the mapped allocation is large enough for a complete symbol with at least one pixel per module. A valid `qr_ready: false` or disabled policy suppresses QR without a warning. Invalid placement metadata, conflicting anchors, an allocation outside the design canvas, or insufficient presentation-canvas pixels produce an actionable warning and suppress QR for that output specification without excluding the decoration, changing its other metadata, or failing literary preparation. Never fall back to a different position or clamp the allocation. A layer condition of `always` (the default), `qr`, or `no-qr` selects artwork for both states, available-only, or unavailable-only respectively. Conditions do not change layer order. This availability decision selects artwork but does not rasterize or composite QR pixels; that occurs later on the presentation canvas after literary rendering.

For Version 0.1, an available literary QR code encodes `https://github.com/ControlForgeHQ/refrain`, independently of the selected quotation, entry, display date, or reveal stage. Resolve the destination separately from encoding, rasterization, and placement so a future companion experience can change destination resolution without redesigning those operations. Do not add a configurable destination or depend on the deferred companion experience.

Version 0.1 uses QR version 4, error-correction level M, UTF-8 byte encoding, and a complete four-module quiet zone. The 33 × 33 symbol and eight quiet-zone modules occupy a fixed application-level allocation of 246 × 246 design-canvas pixels. This allocation is independent of aspect ratio, output resolution, decoration, and literary insets; decorations cannot redefine its dimensions. A payload that does not fit the selected version and error-correction level produces an actionable preparation error.

Resolve QR payload independently from encoding, rasterization, and placement. A selected decoration may position the complete allocation with one horizontal method (`qr_from_left`, `qr_from_right`, or `qr_centered: horizontal`) and one vertical method (`qr_from_top`, `qr_from_bottom`, or `qr_centered: vertical`). Directional offsets are nonnegative design-canvas pixels. When an axis has no method, its independent default is 20 pixels from the right or bottom edge. `qr_centered` is one scalar value and cannot center both axes. Positioning fields are mutually exclusive per axis; malformed or conflicting values suppress QR instead of selecting a precedence or silently using defaults. Centering and bounds validation use the design canvas for the variant's declared aspect.

Use the mapped presentation-canvas allocation rectangle as authoritative, including any width or height difference caused by independent edge rounding. Choose the largest fitting module size for each output specification as `min(allocation_width, allocation_height) // 41`. If this is zero, warn and suppress QR for that output specification. Otherwise rasterize square integer-pixel modules and the complete quiet zone without antialiasing. Center the complete square footprint inside the allocation using half-up rounding when unused pixels are odd. Do not generate, position, resize, or rerasterize QR specifically for the output image; if a final resize is required, the complete QR is distorted only as part of the complete-image resize. Resolve the same placement and QR pixels across every reveal stage of one output specification.

QR output is composited after literary text. The literary renderer must fit the complete literary composition within the configured literary rectangle, but this does not protect text from independently composited artwork or QR output. QR placement does not change literary insets, rearrange text, or reserve additional space. Refrain does not detect or correct QR/text overlap. A complete valid prepared-image cache remains reusable without reevaluating QR placement; regeneration may use current configuration without changing committed selection state. The information view remains outside literary QR behavior.

The same quotation renderer serves normal daily presentations, the information view, and potential future diagnostic views.

The renderer does not require a content-library entry or committed daily selection record as its input. Callers supply the resolved content and presentation parameters appropriate to the view. It follows valid configured geometry and does not guarantee that independently composited graphical elements do not overlap.

The architecture does not require a general-purpose layout framework, externally supplied rendering components, a theme engine, or a plugin interface.

### Daily background and decoration selection

Configuration loading owns asset discovery, validation, collision handling, and construction of independent font, background, and decoration registries. Bundled resources are discovered through Python package-resource APIs; user resources are discovered recursively under the corresponding `assets/{fonts,backgrounds,decorations}/` directory beside the effective configuration. Discovery occurs once when configuration is loaded. It does not monitor or modify user directories.

Discovery establishes availability by stable identifier only. It never adds resources to selection pools. The configured default pools remain the sole source of automatic-selection eligibility; any available resource may still be selected explicitly by content or decoration metadata.

Asset manifests are safely parsed and their references are confined to their owning package. Invalid resources are isolated with diagnostics. Custom identifiers cannot shadow reserved bundled identifiers, and every custom resource in an intra-category collision is excluded deterministically.

Application configuration defines a default selection pool for each resource type. Each pool may contain the reserved value `"none"`, representing the intentional absence of that resource.

An omitted resource configuration preserves the plain paper-white, undecorated presentation.

Decoration, font, background, color, layout, and QR decisions are resolved during image preparation using the selected content's declared preferences and current configuration.

For each selected quotation, Refrain resolves the decoration first:

1. Use the content entry's explicit decoration when available.
2. An explicit decoration value of `"none"` suppresses decoration selection.
3. Otherwise, select from the effective default decoration pool.

The selected decoration may provide preferred font and background values and a complete literary-inset override.

Exactly one font bundle is selected during image preparation using this precedence:

1. Use the content entry's explicit font when it is available and usable.
2. Otherwise, use the selected decoration's preferred font when it is available and usable.
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

Font, background, decoration, color, layout, and QR decisions are resolved from current configuration and available resources during image preparation. They are not part of quotation identity or repetition history and are not persisted as daily selection decisions.

After resolving the decoration, Refrain resolves one literary text color using the first level with usable candidates: the content entry's `text_color`, the selected decoration's `text_color`, the effective `layout.text.colors` pool, then built-in `black`. Invalid or unavailable identifiers are diagnosed and excluded at each level. Candidates are not combined across levels, and duplicate identifiers do not add selection weight.

The selected text and decoration colors are resolved for the complete preparation. Color selection is independent of quotation identity and repetition history.

The registries, valid identifiers, image requirements, pool configuration, and content-entry overrides are specified in `docs/CONTENT_FORMAT.md`.

### Background and decoration recovery

Preparation resolves current configuration and available visual resources for the complete required variant collection. Presentation-wide resource choices remain coherent across variants prepared together; output-specification-dependent geometry, QR availability, transformations, and other raster-dependent results are resolved separately for each specification. It applies the documented fallback and diagnostic policies to unavailable or invalid resources without changing the committed quotation or its reveal progression.

Background source dimensions and aspect ratios are independent of configured output dimensions. Preparation applies deterministic, aspect-preserving centered cover scaling and equal-edge cropping on the design canvas, then composites the result over paper-white while preserving source alpha. Decoration layers use the configured rendering method on the design canvas. Their slice coordinates and transformations do not determine the literary insets.

A missing or invalid optional visual resource must not invalidate the committed quotation or its reveal progression. Other preparation errors, including malformed required selection data or an unrenderable literary composition, remain errors.

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

The information view is prepared for the required output specifications, with consistent presentation-wide choices and raster-specific rendering. Each configured backend receives the matching complete image through the normal publication facilities.

Automatic presentation occurs once on each application start, subject to the configured duration. It does not repeat at ordinary display-day boundaries.

The automatic duration defaults to 60 seconds. A duration of zero disables automatic presentation without disabling the information-view capability.

The configured duration is measured using elapsed monotonic time beginning when the first backend successfully publishes the information view.

Publication to other backends remains independent. A slow or unavailable backend must not delay the transition to daily presentation for other destinations.

If no backend successfully publishes the information view within a bounded initial attempt period, the application proceeds toward normal daily presentation rather than waiting indefinitely.

When the duration expires, Refrain determines the currently required daily presentation using the normal scheduling and recovery rules. It does not replay reveal stages that are no longer required.

An information-view preparation or publication failure must not invalidate the committed selection or prevent ordinary daily presentation when a functional display destination remains available.

The information view may be requested independently of automatic startup behavior, but it is not one of the defined runtime-control operations.

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

Presentation insets are design-canvas pixels, measured inward from each edge of the canvas for the declared aspect ratio. Resolve them on the design canvas, then map their edges to the presentation canvas using deterministic nearest-integer, half-up rounding.

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

Application configuration defines an explicit default font pool using stable identifiers. The effective default pool contains only usable fonts from that configured pool and may be empty when none of its configured identifiers is usable.

Unusable or invalid user font registrations are excluded from the effective registry with appropriate warnings. Bundled font identifiers remain reserved and cannot be overridden.

A content entry may specify a preferred font, inherited by every quotation in that entry.

A decoration may also specify a preferred font.

During image preparation, font selection follows this precedence:

1. Use an available and usable explicit content-entry font preference.
2. Otherwise, use an available and usable font preference from the selected decoration.
3. Otherwise, select from the effective default font pool.

An unavailable bundle preference does not invalidate an otherwise valid content entry or decoration. Refrain reports an appropriate warning and proceeds to the next bundle-selection preference.

After selecting the bundle, Refrain independently resolves the `quotation`, `source`, and `attribution` faces within that bundle. For each role, the first defined preference wins in this order: content entry, selected decoration, selected bundle manifest, global `layout.fonts.font_faces`, then implicit `regular`. An explicit `regular` is defined and overrides lower-priority values. If the winning face is unavailable or unusable, that role falls directly to the selected bundle's `regular` face with an actionable warning; lower-priority face preferences are not consulted. No role selects another bundle. Decoration face preferences apply to the selected bundle even when an entry overrides the decoration's bundle preference.

Each distinct font in the effective default pool has equal selection probability when automatic selection is required.

Automatic font selection requires at least one usable member in the effective default font pool. An empty pool is not an error when a usable explicit content-entry or decoration preference applies. If no usable explicit preference applies and the pool is empty, preparation fails with an actionable diagnostic. Refrain must not silently populate the pool with unrelated bundled fonts or use a separate emergency fallback pool.

Font selection is independent for each complete image preparation. Fonts do not have repetition histories, and a font may be used on consecutive days.

Resolve the selected decoration and font bundle, then resolve all role faces once for the complete required output specifications. Preserve those font identities across output images and reveal stages; do not select fonts independently for an output specification or stage.

Reuse a valid complete cached image set without resolving fonts. When regeneration is required, resolve bundle and face preferences from the selected content properties and current decoration, registry, and global configuration, using the precedence and failure behavior above. Font identifiers, paths, face choices, and font contents are not persisted in operational state. Use one consistent bundle and role-face resolution across all variants and stages prepared together.

If the selected font or a required face cannot be loaded during preparation, report an actionable preparation error. Font failure must not authorize reselection of literary content or alter reveal progression.

An existing complete prepared image set is reused during ordinary operation even if font files or preferences subsequently change.

Font registration, default-pool validation, and configuration fallback rules are defined in `docs/CONTENT_FORMAT.md`.

### Stable progressive layout

The renderer resolves the complete literary composition using the quotation and every available source and attribution field, regardless of the current reveal stage. Each role uses its preparation's resolved face while the source and attribution remain components of the existing unified byline.

The effective literary rectangle, resolved from the selected decoration's insets or global insets for the complete preparation, remains unchanged across every stage generated together.

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

Each output specification's reveal stages use the same resolved composition layout.

Content that cannot be rendered legibly within the supported literary rectangle must be handled explicitly rather than silently clipped, truncated, or omitted.

### Daily selection data

The daily selection record contains the selected entry identity, normalized quotation identity, original quotation text, optional source and attribution, effective reveal schedule, display date, and any selected content-level properties or preferences needed to interpret or present the quotation. These captured preferences are authoritative for the committed selection; preparation and recovery do not reread the source entry. Selection revision, repetition history, highest reveal stage, and scheduling context are held in authoritative operational state.

The record does not contain resolved rendering values. Output dimensions, design-canvas and presentation-canvas sizes, inset rectangle, font and face choices, palette RGB values, visual-resource selections, tinting decisions, QR settings or placement, layer transformations, and other derived presentation parameters are resolved during image preparation and are not persisted solely for pixel-identical recovery.

The selected quotation and captured content-level preferences remain available even when the source YAML entry is edited or unavailable. Editing that entry does not change the committed selection. If regeneration is needed, captured preferences are resolved against current application configuration and available assets; those current inputs may change visual output without altering the selected quotation, captured preferences, or effective reveal schedule.

Preparation errors are reported without changing the committed selection, repetition history, or reveal progress.

### Complete stage preparation

Presentation preparation resolves presentation-wide choices consistently and produces every image requested for the committed selection, each required output specification, and every reveal stage. The caller supplies the cumulative stage sequence; preparation does not calculate reveal times or determine the current stage.

Each image represents a cumulative visibility stage for one output specification. The complete fully revealed literary composition determines that specification's stable geometry for every stage. Raster dimensions, wrapping, fitted font pixel sizes, and mapped geometry may differ across specifications.

Within one output specification, all stage images use identical layout geometry, typography, wrapping, and field positions. Only the visibility of fields changes. Across output specifications, selected presentation resources and other presentation-wide choices remain consistent, while presentation-canvas sizes, geometry, wrapping, fitted font pixel sizes, and QR results are resolved independently.

The renderer does not independently recalculate the composition for each reveal stage.

The same preparation facilities may produce a single fully visible image for views that do not require progressive reveals, including the information view.

Every prepared image must be independently displayable without requiring a previous image to have been presented.

Prepared images are persisted as a disposable cache for reuse throughout the current display day and after application restarts.

Normal reveal transitions select an existing prepared image. They do not invoke quotation fitting, layout calculation, or image rendering.

The preparation process must not expose incomplete images as a valid complete set. Cache metadata must associate complete variants with the current selection, output specifications, and expected stages, and detect incomplete or damaged files. Do not require a fingerprint of all rendering decisions.


### Rendering recovery

The durable daily selection record, not the image cache, is authoritative. If required variants are missing, damaged, incomplete, or unusable, regenerate the required complete stage sets using the selected content, effective schedule, current output specifications, configuration, and currently available assets. Prepare variants coherently with shared presentation-wide choices, and safely publish complete usable artifacts.

Regeneration preserves the selected quotation, content identity, schedule, selection revision, and highest reached reveal stage. A changed output requirement may add variants prepared from this existing committed selection; it must not trigger reselection or alter reveal progress. Regeneration does not consult the original content library, modify repetition history, or move reveal progression backward. Visual appearance may differ from the prior cache after configuration or resource changes; exact pixel reproduction is not required.

If image generation fails, the application must report the error and preserve the existing display image where practical.


### Rendered-image comparison

The application should avoid unnecessary physical refreshes when the required prepared image has not changed.

The display scheduler and backend remain independent of the renderer.

Normal scheduled updates select among prepared images rather than invoking image composition.

## Display output

### Backend responsibility

Refrain presents complete rendered images through narrow, hardware-independent display backend interfaces.

A display backend provides two operations:

- A destination-aware publication operation that presents a complete Pillow image through one selected configured destination. The contract must identify the destination generically; an image-only operation is insufficient when one backend instance owns multiple named outputs. The contract does not prescribe a Python method signature.
- `close()` releases resources owned by the backend.

Refrain selects one or more built-in display backends through validated runtime configuration. Each backend type may be configured at most once, but one backend type may own multiple named output destinations.

Backend selection occurs at application startup and does not require modifications to application code or replacement of installed modules.

Version 0.1 provides three built-in display backends:

- `window`: Presents complete images in a graphical desktop window.
- `waveshare-13in3-e`: Presents complete images on the supported Waveshare 13.3-inch e-Paper HAT+ (E).
- `image-server`: Serves one or more named prepared output images to network clients through a read-only HTTP service.

Each configured output destination has its own canonical runtime destination identity and receives the complete prepared output image matching its resolved output specification for each reveal stage. Destinations may share an image when their specifications are identical; destinations with different specifications receive different variants. Sharing an output specification or image does not merge destination identity, publication, or acknowledgement. One backend instance may expose multiple named output destinations. The coordinator and runtime-control clients use generic destination routing and contain no backend-specific routing rules. Backend selection does not introduce independent content selection, reveal scheduling, composition, or presentation policy.

The desktop window backend presents complete images in a graphical window suitable for development and validation on Windows and Linux. Its image-display area matches the supplied image dimensions and presents the image at native pixel size. A later update with different dimensions resizes the display area; it does not resample, crop, or letterbox the image.

The window backend owns its GUI event loop and keeps the window responsive between synchronous image updates. It replaces the existing image in one window and releases that window when `close()` returns.

Closing the desktop window through the window manager intentionally withdraws its destination for the remainder of the resident runtime. The window is recreated only when a new runtime starts.

The backend reports initialization, presentation, and cleanup failures through common display-backend errors. It reports an unavailable graphical environment with guidance to install Tk support and use a graphical session.

Destination visual post-processing occurs only after the complete requested output image has been rendered. The hardware-independent post-processing contract returns destination-final visual pixels without modifying the caller's image; `window` and `image-server` use identity processing. The viewer and configured backend publication paths use this same contract. It does not initialize or require a display backend.

The Waveshare backend owns model-specific hardware operations, including:

- device initialization;
- transport packing and transfer;
- full-screen refresh;
- controller sleep or release where supported;
- hardware error reporting;
- cleanup.

The Waveshare 13.3-inch panel resolves to the fixed 4:3 @ 1600 × 1200 output specification. Its backend receives the matching output image and must not resize it. An update with dimensions other than 1600 × 1200 is invalid and reports a backend update failure as a contract violation; it is not resized to fit. Hardware-independent post-processing converts the complete RGB output image to the vendored driver's active seven palette entries, in index order: black, white, yellow, red, black, blue, and green. The duplicate black entry is retained. The vendored source also contains a commented alternative ordering (black, white, green, blue, red, yellow, orange), which is not the active panel palette and must not be substituted. Pillow palette quantization and dithering are shared with the driver path; packing those palette indices into the 4-bit transfer buffer remains transport-specific. The complete buffer is prepared before initializing the controller and must contain exactly 960,000 packed elements. Each valid update initializes the controller, transfers the complete image, and returns the controller to sleep. It does not clear the display before an update or during shutdown. `close()` is repeatable and sleeps the controller only when an update has left it active.

The image-server backend owns one HTTP service that exposes the most recently accepted image for each configured named output. Its publication and lifecycle responsibilities are defined separately below.

The common interface does not expose hardware-specific initialization, SPI, GPIO, controller commands, refresh mechanisms, or network transport operations. The Waveshare backend owns transfer packing, refresh, sleep, and cleanup, but not visual palette quantization, image resizing, or literary composition. The window backend displays at native pixel size, and the image-server backend exposes each prepared output without resizing or cropping. No backend may mutate the image supplied by the coordinator. A backend unable to perform its required operation reports a backend-specific publication failure; that failure does not alter any output specification, persistent state, selection, or publication to other destinations.

The image-server backend serves each named output's matching prepared variant with its dimensions and pixel content unchanged. Backend adaptation policies and their visual consequences belong to the relevant backend contract, not to the core renderer.

A completed destination publication operation indicates that the operation for that destination completed successfully. For a network image service, this means the replacement image is available to clients, not that any client has retrieved or displayed it.

Failures and uncertain hardware outcomes must remain distinguishable where the underlying implementation permits.

Display backends must not perform quotation selection, reveal scheduling, image preparation, or persistent-state updates.

Backend implementations are built-in application components. Version 0.1 does not define a general display plugin system.

### Multi-backend publication

For normal scheduled publication, Refrain coordinates publication of the current prepared presentation to every participating configured output destination. A backend with multiple named outputs remains one backend instance, while each named output is a distinct publication destination. The independent scheduling, coalescing, and acknowledgement behavior in this section applies to normal scheduled publication; transient push and refresh use the admission and completion rules in [Transient publication and refresh](#transient-publication-and-refresh).

A single committed daily selection and its coherent set of prepared output images are shared by all destinations. Only the selection is authoritative.

For normal scheduled publication, participating destinations are tracked independently. A destination may remain configured but be intentionally withdrawn from publication for the remainder of the resident runtime. Withdrawal is distinct from failure or unavailability: ordinary scheduled publication skips a withdrawn destination, and later publication requests do not restore it. A failure or unavailable backend does not constitute withdrawal. A slow or failed operation on one backend instance must not delay publication through another available backend instance or prevent subsequent scheduling evaluation. Destinations sharing one backend instance share its lifecycle and serialization.

An active publication to one backend instance must not overlap another publication to that instance, including operations for different named destinations. Operations to different backend instances may proceed concurrently.

The persisted highest reveal stage represents the application's globally reached reveal progression. It does not certify successful presentation by any particular backend.

Reveal progression advances monotonically when a later stage becomes required and is durably recorded independently of backend publication outcomes.

The application coordinator maintains independent acknowledgement of the scheduled presentation identity for each participating destination, including every named output, during the application lifetime. It tracks transient operation completion separately from this scheduled acknowledgement. Successful transient publication must not clear or replace the scheduled acknowledgement used to suppress redundant scheduled updates.

For normal scheduled publication, the application must distinguish the currently required variant for each participating destination from the scheduled identity last acknowledged there. A successful scheduled update to one destination does not establish successful publication to another. Literal last-published pixels may instead be a transient preview and do not determine whether the scheduled identity remains acknowledged.

Destination discovery must expose enough publication status to distinguish an intentionally withdrawn destination from a participating destination that is available or failed/unavailable. Withdrawal is runtime-local and is not a general dynamic enable/disable or configuration-mutation facility.

Publication tracking is owned by the application coordinator, not by individual display backends. Backends receive complete images and do not interpret selection revisions, reveal stages, or persistent operational state.

Publication status is transient and does not require separate durable storage. After application restart, the coordinator supplies the currently required prepared image to each available destination.

If a new scheduled presentation or variant becomes required while a backend instance is busy, each affected destination must eventually receive its latest required image rather than replaying obsolete intermediate scheduled updates.

An active hardware update need not be interrupted when a newer presentation becomes available.

Normal scheduled publication does not require simultaneous completion or acknowledgement from every destination. Transient push and refresh use synchronous per-request completion reporting for every requested destination, as defined under [Transient publication and refresh](#transient-publication-and-refresh).

The order of backend declarations does not establish publication priority.

Multi-backend publication must preserve bounded memory use and must not require one complete image copy or an unbounded update queue for every pending presentation.

### Transient publication and refresh

The normal runtime's desired scheduled presentation is distinct from a one-shot transient publication submitted by an external local tool. A transient publication does not replace or invalidate the scheduled desired presentation. It does not modify the committed selection, selection revision, repetition or global history, reveal progression, scheduling state, prepared-image artifacts, or the identity of the normal desired presentation.

The runtime-control interface belongs to the resident Refrain process and is local-machine only, authenticated, and limited to explicitly defined operations. Its initial operations are destination discovery, transient complete-image publication, and refresh of the current scheduled presentation. It is separate from the `image-server` HTTP service and any public or future web presentation. It does not provide arbitrary filesystem access, backend-method invocation, configuration or content mutation, shell execution, or general remote procedure execution.

The runtime is authoritative for configured publication destinations and their output specifications. Discovery returns each canonical runtime-supplied destination identifier, its declared aspect ratio, requested resolution, and whether it supports transient publication. Identifiers are opaque routing values: clients must not infer backend type, hardware, transport, or capabilities from their spelling. Backend-specific publication details remain runtime-owned. Destination discovery does not reserve a destination. Transient-publication capability indicates whether a destination accepts externally supplied completed images; it does not gate normal scheduled publication or refresh.

An external preview contains complete output images rendered by the submitting viewer. The viewer remains authoritative for its pixels, using its own selected configuration, content, assets, and presentation overrides. The runtime does not reconstruct the preview from content or semantic presentation parameters. A viewer first discovers destination output specifications, renders one complete image variant for each unique specification, then submits those images and the specifications against which they were rendered. Presentation-wide choices remain coherent across variants generated together. Variants for identical specifications may share one image and transfer.

Before any backend is accessed, the runtime validates the complete request: each destination still exists, each current output specification matches the discovered specification, every selected destination has an image variant, and every image has the exact required dimensions. Malformed, unsupported, or inconsistent requests are rejected without backend access; the runtime does not infer a replacement destination, adapt a changed specification, or resize an image. Backends continue to receive complete images.

External publication is opportunistic, not queued. Admission is atomic across all requested destinations: if any selected destination is publishing or has work that prevents immediate safe admission, the entire request is rejected as busy before any transient publication begins. `all` means every configured destination still participating in publication is included or none are. An intentionally withdrawn destination is excluded from transient `all`; explicitly naming one is rejected. A failed or unavailable destination is not silently treated as withdrawn and remains included in `all`, where its publication failure contributes to the request result. Normal scheduled work has priority until an external operation is admitted. After admission, transient work is allowed to finish safely; newly required scheduled work may follow it but must not interrupt or replace the admitted operation. Operations against the same backend instance never overlap.

Only one transient publication request may be in transfer, validation, or admitted publication at a time. A second transient request is rejected as busy until the current transient operation reaches a terminal result. This global transient-operation serialization does not prevent destinations within one admitted operation from progressing concurrently through independent backend instances; ordinary per-backend serialization still applies.

Before admission, rejection means no requested publication has begun. After admission, the resident runtime owns the operation; client disconnection does not cancel, roll back, or preempt it. The operation continues under ordinary backend safety, serialization, and shutdown rules. If publication completes or partially completes but the terminal acknowledgement is not delivered, the client must treat the outcome as unconfirmed: it cannot infer that nothing was published, that every destination succeeded, or that every destination failed. The client must not automatically replay the request because the acknowledgement was lost. Publication across destinations is not transactional and cannot be rolled back.

While a transient preview is visible, routine scheduler reevaluation of an unchanged scheduled identity does not repaint it solely because the destination contains different pixels. The preview may remain visible until ordinary scheduling requires a genuine presentation change or an explicit refresh is requested. There is no automatic timeout or restoration of the image that was visible before the preview.

`refrain --refresh` is a one-shot control-client operation that asks the resident normal runtime to republish its own presentation currently required by scheduling to every configured destination still participating in publication using a forced scheduled-publication operation. It skips intentionally withdrawn destinations and does not resurrect them. It is not historical restoration: for example, it publishes the current reveal stage if progression advanced after a preview. Refresh does not require transient-publication capability, so a destination may participate in scheduled publication and refresh without accepting externally supplied transient images. Admission is atomic across the complete participating destination set; ordinary backend availability and busy-admission rules apply. Refresh is rejected as busy rather than queued when the complete operation cannot be safely admitted immediately. Once admitted, it remains owned by the resident runtime even if the client disconnects.

A successful synchronous transient push or refresh reports success only after every requested destination has completed its backend publication operation successfully. A failure at one destination is reported; success at another does not make the complete request successful. If its terminal acknowledgement is lost, the client observes an unconfirmed outcome rather than success or failure. The public commands provide visible progress before waiting on slow publication.

Any future configured destination that supports the ordinary complete-image publication contract participates through runtime-supplied discovery and routing, without viewer-specific backend logic. Transient-publication capability is a backend-generic destination property and is reported as such during discovery; clients do not infer it from identifier spelling or backend type. If the requested destination is unsupported—or `all` includes any participating destination that is unsupported—the request is rejected before rendering or publication. `all` does not silently omit unsupported or failed destinations, but does exclude destinations intentionally withdrawn for the resident runtime.

### Network image service

The `image-server` backend provides network-accessible representations of its named outputs without requiring directly connected display hardware. One backend instance owns one HTTP service and maintains an independent current image representation and entity tag for each configured output ID.

Each named output is available at its own read-only HTTP endpoint:

`GET /display/<output_id>/current`

A successful request returns the complete PNG for that output's resolved specification, with the appropriate HTTP content type. For example, the `default` output is available at `/display/default/current`. The output ID is a path component and must be URL-encoded when necessary.

The endpoint must be usable by standard HTTP clients, including ordinary web browsers, without requiring client-specific software or protocols.

Each output resource supports HTTP entity tags (ETags) derived from its served image content. Clients may submit conditional requests using `If-None-Match`; when that output's current representation matches, the service returns `304 Not Modified` without transferring the image body.

When no image has been accepted for the requested output, the service returns `503 Service Unavailable`.

The backend retains each current encoded PNG and its associated entity tag in memory. It does not create or manage a separate persistent image store.

Publishing a new prepared stage replaces the representation for each named output independently. Concurrent requests must observe a consistent, complete image and entity tag for one output, never partially updated content.

The existing prepared-image persistence and recovery mechanisms remain authoritative. After application startup or recovery, the scheduler supplies the appropriate prepared image through the normal backend interface.

The HTTP service operates independently of individual clients. It does not track display devices, maintain client sessions, queue updates, or require acknowledgement that an image has been physically displayed.

Clients determine when to retrieve images. A client may miss intermediate reveal stages and retrieve only the most recently published image.

The backend does not control client polling intervals, power management, physical display refreshes, or client-side image retention.

The service must remain responsive between image replacement operations without requiring the application scheduler to process HTTP requests.

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

For the image-server backend, publication replaces the available image representation for each named output. Network clients retrieve each output independently of the application's scheduling operations.

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

For the image-server backend, unsuccessful image preparation or replacement must not expose incomplete content or invalidate the previously accepted image for the affected named output.

Individual network-client failures do not constitute display-backend update failures. The backend does not require clients to retrieve or acknowledge published images.

The exact retry parameters and backend lifecycle mechanisms are engineering decisions informed by the relevant output destination.

Backend recovery must not modify committed selection history or cause quotation reselection.

### Retained display content

E-paper retains its visible image without continuous power.

Refrain should preserve useful displayed content across temporary application and hardware failures when possible.

It must not clear a physical display merely because a recoverable software problem occurred or another backend failed.

The image-server backend retains each named output's last successfully accepted image while the backend remains operational. It does not independently persist those representations across application restarts.

Network clients are responsible for retaining their displayed content during temporary network or application unavailability.

## Application lifecycle

### Application paths and initialization

The command-line entry point resolves omitted runtime storage paths to the independently defined platform-standard per-user locations, regardless of the current working directory. Optional state, history, and artifact overrides belong to application configuration; each explicit relative path is resolved from the selected configuration file, while each omitted value retains its own platform-standard default. Selecting another configuration file does not itself relocate storage, and a custom state path does not relocate history. The entry point passes effective paths to application and storage components, which do not infer platform locations.

Normal startup requires the selected configuration file to exist. It does not substitute the packaged default configuration, create an installation directory structure, or copy sample content. Relative content paths remain based on the selected configuration file. Custom visual resources are discovered by category beneath `assets/fonts/`, `assets/backgrounds/`, or `assets/decorations/` beside that effective configuration file and are referenced by registered identifier. Manifest image and font references are relative to their containing package and confined to that package. There is no arbitrary absolute-path custom-resource registration interface.

The explicit, noninteractive `--initialize` operation manages only standard per-user destinations and ignores runtime storage settings in configuration. It reuses existing real directories, preserves an existing regular `config.yaml` byte-for-byte, and copies the packaged default only when that file is absent. It installs packaged sample content only when the standard content directory is missing or empty; ordinary pre-existing nonempty content is left untouched and uninspected. An interrupted sample installation may be resumed only when its installation marker and every existing expected sample file can be positively verified; missing expected files may then be installed without overwriting existing files. Invalid markers, conflicting sample contents, or uncertain ownership require manual inspection rather than automatic repair. It creates missing `assets/`, `assets/fonts/`, `assets/backgrounds/`, and `assets/decorations/` directories while preserving any existing contents. It copies no bundled visual resources into user assets and does not validate files already there. Initialization reuses existing state and cache directories and never modifies existing state, history, or prepared artifacts. New files use exclusive creation, no empty state or history files are created, and failures leave already-created destinations in place for a safe retry. Initialization does not start selection, preparation, or display lifecycle operations.

Configuration and content remain user-owned inputs. Operational state and global history remain authoritative and historical persistence respectively; prepared artifacts remain derived output. Runtime creation of those persistence and artifact files remains owned by their existing components.

`--reset` and `--purge` are separate interactive operations for the standard per-user installation and must be run while Refrain is stopped. Reset removes only the platform-standard operational-state file, global-history records and rotations, and generated cache contents while preserving configuration, content, all user assets, and installation directories; configured custom storage paths are untouched. Purge removes the Refrain-owned standard configuration, operational, and cache directory trees, including configuration, content, and assets stored beneath the standard configuration directory; it does not follow configured storage paths or remove shared application-data parents. Neither operation reads runtime storage settings or starts the application lifecycle. Their deletion checks and confirmation requirements are described in [engineering guidance](ENGINEERING.md#installation-approach).

Platform paths, installation, and service operation are documented in [engineering guidance](ENGINEERING.md#deployment-and-service-operation); public configuration is specified in [the content-format document](CONTENT_FORMAT.md).

### Resident ownership and runtime control

A normal Refrain runtime is the sole owner of its configured backend instances and physical display resources for the lifetime of the process. Only one backend-owning Refrain process may own the per-user installation at a time. A second normal invocation or a concurrent `--demo` invocation fails immediately with an actionable diagnostic rather than starting another runtime. Demo is a standalone backend-owning mode under the same exclusive ownership rule; it does not serve runtime-control requests, and concurrent demo operation is not supported.

Installation-management commands that create, reset, purge, or otherwise mutate the standard installation use the same exclusive-ownership rule and must fail rather than mutate files while a resident runtime owns them. One-shot control clients, including `refrain --refresh`, do not acquire resident ownership; they communicate with the already-running normal runtime.

External tools publishing through the runtime must never construct, initialize, or directly access configured backends. The resident normal runtime exposes the narrowly scoped local runtime-control operations defined under [display output](#transient-publication-and-refresh). The interface is not a network administration API and does not expose the separate `image-server` service as a control channel.

### Startup

Normal startup performs the following logical operations:

1. Load application configuration, accepting documented defaults and recoverable configuration problems while reporting diagnostics.
2. Recover persistent operational state, if available.
3. Evaluate whether an existing committed selection remains active under the display-day transition rules.
4. Load and validate content sources when a new selection is required, constructing an effective library from accepted entries.
5. Perform and commit a new selection when required and when a usable effective content library is available.
6. Verify that all required reveal-stage images are available and valid for the committed selection.
7. Reuse a complete prepared-image cache or regenerate the complete stage set from the current daily selection, configuration, and available resources.
8. Initialize configured display backends independently.
9. If automatic information-view presentation is enabled, prepare and request publication of the information view.
10. Observe the configured information-view duration and transition to daily presentation when it expires, or proceed directly when automatic presentation is disabled or cannot be completed.
11. Determine the currently required daily reveal stage, respecting previously reached progression and the current logical display date.
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
5. Creates the daily selection record.
6. Atomically commits the selection record, updated repetition history, next selection revision, initial reveal progress, and required scheduling context.
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

The optional `--demo SECONDS` operating mode repeatedly selects quotations and presents each canonical reveal stage at an accelerated interval. It bypasses normal time-of-day scheduling without manufacturing clock transitions. The automatic startup information view is suppressed.

The session determines its eligibility display date once from host-local time and the configured day start. Every subsequent selection uses that same date and the normal selection and resource-resolution procedure, including session repetition history. A date does not limit the number of selection revisions in this mode.

Demo progression belongs to the application controller, not the scheduler, renderer, or display backends. Each daily selection is committed before its complete required output-variant set is prepared or reused from cache. `resolve_reveal_stages()` supplies the same cumulative sequence used in normal operation, preserving simultaneous reveals and absent fields.

The initial stage is requested as soon as it is ready. Each stage receives the requested minimum monotonic viewing interval beginning at its first successful backend acknowledgement. After the final stage's interval, the controller commits another selection. Failed preparation or publication does not complete a stage or authorize reselection. Publication remains owned by the existing coordinator, with independent backend workers, coalescing, and backend-owned refresh constraints; not every destination must acknowledge each stage.

Operational state, prepared artifacts, and global history are isolated in fresh temporary session storage using their existing formats. Configured and platform-standard production persistence locations are never used or modified in demo mode. The committed quotation, captured content preferences, and reveal progression remain authoritative within the session. A complete valid prepared set remains stable while reused; after cache loss or invalidation, preparation may resolve current configuration and available resources according to the ordinary regeneration rules. Shutdown releases session resources; demo sessions are neither retained nor resumed. Loss of all display destinations terminates the session.

Lifecycle, retry, timing, and testing implementation guidance belongs in `docs/ENGINEERING.md`.

### Presentation inspection and push with `refrain-viewer`

The installed `refrain-viewer` command owns one-shot presentation inspection and image export. It loads the selected application configuration and content/assets, explicitly selects one entry and one 1-based quotation number, constructs presentation data through the same shared operation as the runtime, and uses the authoritative preparation and rendering pipeline. It does not schedule, select, commit, persist, or reveal progressively.

Viewer-owned transient publication accepts two sources of complete output pixels: a fully rendered image generated from Refrain presentation inputs, or an explicitly supplied finished PNG. The finished-image source is already downstream of the presentation pipeline; its pixels are authoritative and are not passed through presentation construction, preparation, rendering, or output-geometry transformation. Local inspection may fit only a private desktop copy.

The built-in `@preview` pseudo-entry is viewer-owned fixture content, not part of the content library. It supplies short, medium, and long quotations with source and attribution metadata; the default invocation selects `@preview:2`. A normal entry selector ignores eligibility, priority, and repetition history, and does not change ordinary content-entry identifier syntax.

Runtime and viewer share presentation construction, preference resolution, resource fallback, geometry, QR viability, image composition, and rendering. Normal runtime preparation supplies no viewer overrides or diagnostic overlays. The viewer may supply typed explicit overrides as the highest-precedence layer; all properties not explicitly overridden retain normal Refrain precedence and pool selection. Its `--debug-layout` option applies the shared presentation diagnostics to the prepared preview. Optional quotation font-size bounds are design-canvas measurements resolved with configuration values and scaled to the presentation canvas before fitting. An alternate `--config` selects the normal configuration layer and does not elevate it above entry or decoration preferences.

For local Refrain-presentation inspection and export, the viewer creates one viewer-selected output specification independently of configured display-backend specifications. Its default is 16:10 at the full design-canvas dimensions. `--render-as DESTINATION_ID` instead resolves the identifier in the viewer's effective configuration and uses that destination's output specification. Both follow the established design-canvas → presentation-canvas → requested-output pipeline; `--render-as` then applies the shared destination visual post-processing to the complete output image. `--output` writes the final output PNG. The optional simple viewer window displays that same output and may scale only a private desktop copy to fit; it is not a configured display backend. In push mode, output specifications come exclusively from the selected runtime destinations, and the viewer may render one variant for each unique specification. A finished PNG may instead serve every selected specification only when its dimensions exactly match each requested output size; differing declared presentation aspects do not require distinct finished pixels when requested dimensions match.

Refrain-presentation viewer execution loads no operational state, global history, or prepared artifacts, even when the configuration names custom storage paths. Direct finished-image inspection and publication also do not load application configuration, content, assets, or persistence. The viewer never constructs, initializes, or directly accesses configured display backends. In push mode, it only asks the resident runtime to publish complete output images. In Refrain-presentation inspection/export modes, its only filesystem output is an explicitly requested PNG.

Push may use either `refrain-viewer [presentation overrides...] --push TARGET` or `refrain-viewer --image PATH --push TARGET`, where `TARGET` is `all` or one canonical destination identifier discovered from the running normal runtime. The viewer treats identifiers as opaque and uses runtime discovery for destination topology and output geometry. Public command syntax and mode conflicts are specified in the [CLI reference](CLI.md). The runtime owns destination geometry; the viewer owns the selected content and presentation choices, overrides, and complete output pixels.

Push requires a running normal Refrain instance. The viewer discovers selected destination specifications without reserving them, then either renders each unique specification using coherent presentation-wide choices or submits the supplied finished pixels unchanged after exact-size validation for every selected destination. It does not contain backend-specific routing or geometry logic. The runtime validates the current destinations, specifications, and exact image dimensions before publication. A changed or unavailable destination is rejected rather than adapted.

Push is synchronous: the viewer identifies the selected destination set and reports visible progress before waiting for potentially slow publication. It remains attached until publication to every selected destination has completed or failed, and returns success only if every selected destination succeeds. A busy request is rejected in full without queuing or partial publication.

### Recovery

Recovery is performed according to the stage at which an interruption occurred.

An interruption before selection commitment permits selection to be repeated.

An interruption after commitment preserves the committed selection.

Missing or incomplete prepared variants are regenerated as complete stage sets from the durable daily selection and current presentation inputs, without reselection or reveal regression.

Individual display backend failures are handled through independent recovery policies without delaying other available destinations.

After restart, each available backend is supplied with its currently required prepared variant without relying on persisted backend-specific presentation progress.

Recovery must not introduce additional history entries or silently substitute content.

### Shutdown

Normal shutdown must stop new presentation requests and safely release resources owned by every configured display backend.

Backend shutdown must account for active publication operations without permitting unsafe overlapping hardware access.

Shutdown waits for active synchronous publications only for a bounded period. It must not interrupt a backend operation or invoke that backend's cleanup concurrently with an active publication. If a publication remains blocked at the deadline, its worker retains the active image and attempts cleanup if the operation later returns; process termination may ultimately end a still-blocked worker.

Failure to close one backend must not prevent cleanup attempts for other backends.

Shutdown must not intentionally erase retained e-paper images.

Committed selection state remains available for subsequent startup recovery. Prepared images are a disposable cache that may be rebuilt.

### Failure isolation

Display backend failures must remain isolated from other destinations and must not invalidate content selection or persistent history.

Rendering failures must not cause reselection after a daily selection has been committed.

Content-library changes or validation failures must not modify an already committed daily selection.

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
12. A daily selection is authoritative only after its selected content record, updated repetition history, selection revision, reveal progress, and scheduling context have been committed consistently.
13. An interrupted operational-state commitment must not leave a partially committed selection or inconsistent repetition history.
14. Selection revisions increase monotonically and are maintained independently of global history.
15. Global-history recording failures do not invalidate committed selections or prevent ordinary presentation.
16. A committed daily selection preserves the selected content, captured content-level preferences, and effective reveal schedule independently of subsequent content-library changes.
17. Every required reveal-stage image is generated for each unique required output specification.
18. Presentation-wide choices remain consistent across output specifications, while presentation-canvas layout and rendering results are resolved independently for each specification.
19. The declared aspect ratio is distinct from requested output resolution: it selects the design canvas and determines the exact-ratio presentation-canvas dimensions for each output specification.
20. Graphical composition and configured presentation measurements move from the design canvas to the presentation canvas before all literary, QR, and diagnostic composition; only an optional final whole-image resize to the exact requested dimensions may follow.
21. Destinations with identical output specifications may share a prepared output image, and each backend receives it without owning literary composition or presentation policy.
22. Complete prepared-variant sets are disposable caches and are reused rather than regenerated at every scheduled reveal.
23. Missing or unusable variants can be prepared from the committed selection without reselection, history changes, or reveal regression.
24. A restart retains the committed selection and reveal progression only while the current logical display date matches the committed date.
25. Reveal progression never moves backward within a committed selection.
26. The active selection remains authoritative while the current logical display date matches its committed date; a mismatch requires a new selection regardless of clock direction or restart.
27. Within one logical display date, reveal progression is monotonic. A new selection for another logical display date begins its own reveal progression.
28. Hardware failures do not invalidate committed selections.
29. Ordinary operation does not require internet access or external services.
30. Public presentation does not grant privileged local control.
31. Future integrations must not become prerequisites for displaying ordinary quotations.

Architectural changes must be evaluated against these invariants before implementation work is accepted.
