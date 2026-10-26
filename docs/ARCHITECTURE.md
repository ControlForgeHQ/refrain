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

**Global History:** A permanent chronological record of committed quotation selections.

**Repetition History:** A persistent but selectively resettable collection of quotation identities used to prevent repetition until an eligible selection pool is exhausted.

**Daily Selection:** The individual quotation assigned to the current display day.

**Daily Snapshot:** A persistent, self-contained copy of the selected quotation and all resolved information required to prepare its presentation independently of the content library.

**Selection Commitment:** The successful durable recording of a daily snapshot and its corresponding global-history and repetition-history updates.

**Reveal Stage:** A cumulative set of content fields eligible for presentation at a particular point in the configured reveal schedule.

**Prepared Image:** A complete, persisted image representing one reveal stage of the committed daily selection.

**Presentation:** The selected quotation, associated metadata, reveal schedule, and applicable layout configuration used to produce prepared images.

**Renderer:** The hardware-independent component responsible for composing complete presentation images.

**Display Backend:** The component responsible for communicating prepared images to the physical display.

**Persistent State:** The committed daily snapshot, selection histories, reveal progress, and scheduling context required for recovery across application restarts.

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
Daily snapshot + history updates
    |
    v
Atomic selection commitment
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

The flow describes responsibility and ownership, not a required class hierarchy or directory structure.

### Selection and commitment

Selection identifies the individual quotation to be displayed during the next presentation interval.

The selected quotation inherits the eligibility, priority, reveal configuration, and presentation metadata of its containing content entry.

The selection does not become authoritative until its complete daily snapshot and the corresponding history updates have been durably committed.

An interrupted or unsuccessful commitment leaves the new selection incomplete.

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

For each new selection, the application first identifies the highest-specificity eligible quotation pool.

Within that pool, quotations already present in repetition history are excluded while unused candidates remain.

When every quotation in the winning pool has been consumed, the application removes the identities of all quotations in that pool from repetition history.

The application then reevaluates the same pool.

Resetting a pool must not clear unrelated quotation identities from repetition history.

For example, exhausting the annual October 17 pool must not reset quotations belonging only to Christmas or the ordinary selection pool.

The applicable pool is determined dynamically from currently eligible quotations rather than from a permanently stored membership list.

Changes to content-library membership therefore affect subsequent selections without invalidating existing committed selections.

When a quotation participates in multiple eligibility contexts, resetting one pool may make that quotation eligible again in another context.

This is an accepted consequence of using one resettable repetition-history collection.

The permanent global history is not modified when repetition history is reset.

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
2. Identify eligible content entries.
3. Expand eligible entries into individual quotation candidates.
4. Determine the highest matching date specificity.
5. Retain candidates matching that specificity.
6. Exclude quotation identities present in repetition history.
7. If no unused quotations remain, remove the identities of the winning pool from repetition history and reevaluate that pool.
8. Retain candidates having the highest priority.
9. Randomly select one remaining distinct quotation identity.
10. Resolve the selected occurrence and its inherited metadata.
11. Resolve the font using the entry's preference or the configured default pool.
12. Prepare the complete daily snapshot.
13. Atomically commit the snapshot and corresponding history updates.

Selection is not complete until commitment succeeds.

A failed or interrupted commitment permits the selection procedure to run again.

The random results of an uncommitted selection, including font selection, are not authoritative.

Selection policy must not depend on file enumeration order or incidental filesystem behavior.

## Persistent state

### Required persistence

Refrain maintains sufficient durable state to preserve:

- the current committed daily selection;
- the display date associated with that selection;
- the selected quotation's original text;
- the complete resolved presentation metadata;
- the reveal schedule applicable to the selection;
- relevant layout configuration;
- permanent global selection history;
- resettable repetition history;
- the highest reveal stage reached for the current selection;
- scheduling context required to recover correctly after clock adjustments.

The current daily snapshot must be self-contained.

After commitment, the active presentation must not require access to the original YAML content entry.

### Daily snapshot

The daily snapshot contains a complete copy of the selected quotation and all information needed to prepare every reveal stage.

It includes only the selected quotation from its containing content entry, not the entry's other quotations.

The snapshot must contain the resolved font selected for that daily presentation, together with the remaining presentation metadata, reveal schedule, and layout configuration required for rendering.

Font selection occurs before the daily snapshot is committed.

An entry's explicit font preference is used when the font is available in the configured registry. Otherwise, the presentation uses a font selected from the configured default pool according to the content-format specification.

The resolved font remains fixed throughout the committed display day.

The snapshot must contain resolved values rather than references to mutable content-library entries or configuration that may subsequently change.

The snapshot is immutable after commitment.

Presentation changes within the display day are represented by reveal progression and prepared images, not by modifying the selected content or font.

### Global history

Global history is a chronological record of committed quotation selections.

Each selection records:

- the selected quotation text;
- its normalized repetition identity;
- the font actually selected for its presentation.

Global history is independent of the containing entry's identifier, source, attribution, priority, and eligibility rules for repetition purposes.

The selected font is historical presentation metadata. It does not participate in quotation identity or repetition tracking.

Global history is append-only during normal operation.

Its records are not removed or rewritten when repetition pools are exhausted.

Global history provides a permanent record of Refrain's selection decisions, including the typography used for each committed presentation.

A quotation and its selected font are recorded when the daily selection is committed, not when the display backend confirms a physical refresh.

### Repetition history

Repetition history contains normalized identities of quotations consumed within active selection cycles.

It is persistent across application restarts.

Unlike global history, repetition history may have identities removed when the currently eligible highest-specificity pool becomes exhausted.

A reset removes only the identities corresponding to quotations in that pool.

Repetition history must not be independently reconstructed from the entire permanent global history after each restart, since doing so would reverse intentional pool resets.

### Selection commitment

Selection commitment is the durable recording of:

- the complete daily snapshot;
- the corresponding append to global history;
- the updated repetition history;
- the identity and scheduling context of the committed selection.

These changes form one logical transaction.

A selection is authoritative only when the complete transaction has succeeded.

An interrupted transaction must recover to a consistent state in which either:

- the previous committed state remains authoritative; or
- the new snapshot and all corresponding history updates are authoritative.

A partially committed snapshot must not be treated as a completed daily selection.

History must not record a selection without its corresponding committed snapshot.

The persistence mechanism must provide adequate protection against incomplete writes and interrupted replacement.

The exact storage format and transaction implementation belong to engineering.

### Prepared images

After selection commitment, Refrain generates every required reveal-stage image from the committed snapshot.

Prepared images are persisted on disk.

They are derived artifacts, not independently authoritative application state.

Prepared images must remain associated with the snapshot from which they were generated.

A complete, valid set of prepared images should be reused after application restart.

Missing, damaged, or incomplete prepared images must be regenerated from the committed snapshot.

Regeneration must not trigger a new daily selection or alter selection history.

The runtime must not require all prepared images to remain decoded in memory.

### Recovery and missing content

On startup, Refrain first attempts to recover the committed selection.

The content library does not override a valid committed snapshot.

If the original YAML entry has been removed, renamed, or modified, the current selection remains unchanged.

Missing or invalid original content does not prevent recovery when the committed snapshot is valid.

If selection commitment was interrupted, Refrain must recover the last consistent state and repeat selection when necessary.

If rendering or image persistence was interrupted after commitment, Refrain resumes or repeats preparation using the same committed snapshot.

If the snapshot itself is unavailable or invalid, the application must report the failure and must not silently substitute another entry.

The existing physical e-paper image should be preserved when recovery cannot safely complete.

### Persisted and derived state

Persistent state owns:

- committed selection decisions;
- global selection history;
- active repetition history;
- immutable daily content snapshots;
- monotonic reveal progress;
- scheduling context needed for recovery.

The appropriate reveal stage is initially determined by the committed schedule and current time.

Within a committed selection, reveal progress must not move backward.

The currently required stage is therefore the later of:

- the stage required by the current time;
- the highest stage already reached for the committed selection.

Reveal progression must survive application restarts.

Prepared images remain reproducible from the committed snapshot and do not replace it as the source of truth.

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

The display scheduler determines the currently required prepared image.

When the required stage changes, the scheduler submits the corresponding image to the display backend.

The scheduler must not invoke content selection or rendering merely because a reveal stage becomes due.

A failed display update does not invalidate the committed selection or its prepared images.

A subsequent successful update may skip intermediate stages and present the latest required image.

## Presentation and rendering

### Rendering independence

The renderer accepts a committed daily snapshot and its resolved presentation configuration.

It produces complete images without accessing physical display hardware.

The renderer must not select content, modify selection history, or determine application lifecycle policy.

Rendered output must be testable and inspectable without Raspberry Pi display hardware.

### View composition

Refrain separates view-specific background composition from primary quotation typography.

A background generator produces a complete base image containing the visual elements owned by that view, including decorative elements, secondary text, and other non-primary-quotation content.

The shared quotation renderer places a quotation onto the supplied background image within an explicitly resolved rectangular region.

The quotation renderer is independent of the type or purpose of the background image. It does not read application configuration, select quotations or fonts, or generate view-specific metadata.

For normal daily presentations, the quotation region is resolved from the configured layout. Other views may supply a different quotation region without modifying the shared text-fitting and typography behavior.

The initial presentation uses a standard background generator. This composition model also accommodates a separate information view without introducing a general-purpose layout framework or requiring information-view-specific behavior in the quotation renderer.

### Information view

Refrain will provide an information view presenting application identity and selected diagnostic information in a format consistent with its quotation-based visual design.

The information view contains:

- a curated, application-owned quotation associated with the running release;
- the Refrain and ControlForge project identity;
- application version and available build or commit information;
- selected runtime and environment details where available;
- an appropriate copyright notice.

The curated quotation is not drawn from the user content library and does not participate in daily selection, priority, repetition history, or global selection history.

The information-view background generator owns its branding, diagnostic text, and other secondary presentation elements. The shared quotation renderer presents the curated quotation using the same typography and fitting facilities as normal daily quotations.

The quotation remains visually primary. Branding and diagnostic information are subordinate and should not compromise readability.

The information view is independent of the committed daily selection. Displaying it does not create a new selection, modify selection histories, or advance reveal progress.

The information view may be requested independently of automatic presentation behavior.

Application configuration will provide an optional automatic-display duration. A duration of zero disables automatic presentation without disabling the information view itself.

An unavailable optional diagnostic value must not prevent the information view from being rendered.

### Initial visual design

The initial release provides one configurable layout.

Its intended appearance is that of a carefully typeset printed page rather than a conventional electronic interface.

The design prioritizes:

- readable typography;
- generous whitespace;
- restrained visual decoration;
- a predominantly paper-white background;
- dark text with optional color accents.

The layout defines a bounded rectangular region for the primary quotation.

Refrain automatically determines an appropriate font size and line wrapping to fit the selected quotation within that region.

The available region is configurable using resolution-independent coordinates.

Automatic fitting must preserve the quotation's intended text, including explicit line breaks and paragraph structure.

Font-size constraints establish acceptable presentation bounds rather than requiring every quotation to use a fixed size.

The renderer must not silently clip, truncate, or omit quotation text when fitting it to the available area.

The initial release does not require arbitrary layout scripting, multiple layout templates, or automatic font-family selection based on fitting performance.

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

The selected font is resolved after quotation selection and before daily snapshot commitment.

The actual selected font is included in the committed snapshot and permanent global selection history.

### Stable progressive layout

The primary quotation retains stable placement and typography across reveal stages.

Its configured rectangular region remains unchanged for the duration of the committed selection.

The renderer may determine appropriate text wrapping and font size during presentation preparation, but the resulting composition must remain consistent across every reveal-stage image.

Space for later source and attribution information is reserved in the composition.

Revealing a new field must not cause the primary quotation to move, change font, change size, or require the entire page to be reflowed merely because that field becomes visible.

Text layout must accommodate varying quotation lengths within the available presentation regions.

Content that cannot be rendered legibly within the supported layout must be handled explicitly rather than silently clipped or truncated.

### Complete stage preparation

The renderer produces the complete set of images required for a committed selection.

All stages must use consistent content, typography, and layout geometry.

Each prepared image must be suitable for independent presentation without requiring a previous image to have been displayed.

Prepared images are persisted for reuse throughout the current display day and after application restarts.

The preparation process must not expose incomplete images as valid presentation artifacts.

### Rendering recovery

The committed daily snapshot is the authority for regenerating prepared images.

Missing or invalid prepared images may be regenerated without access to the content library.

Recovery must not change the selected quotation or its reveal schedule.

If image generation fails, the application must report the error and preserve the existing display image where practical.

### Rendered-image comparison

The application should avoid unnecessary physical refreshes when the required prepared image has not changed.

The display scheduler and backend remain independent of the renderer.

Normal scheduled updates select among prepared images rather than invoking image composition.

## Physical display output

### Backend responsibility

The display backend owns hardware-specific operations, including:

- device initialization;
- image transfer;
- full-screen refresh;
- controller sleep or release where supported;
- hardware error reporting;
- cleanup.

It must not contain quotation-selection or reveal-scheduling policy.

### Update behavior

The physical display is updated at meaningful presentation changes, including:

- the beginning of a new display day;
- scheduled progressive reveals;
- recovery when a valid desired image has not been successfully presented.

Refrain does not require continuous refresh or animation.

Display updates must be coordinated so that overlapping operations cannot corrupt communication with the device.

### Failure handling

A display-update failure must be reported with sufficient diagnostic context.

Transient failures may be retried using a bounded recovery policy.

Retries must not indefinitely block scheduling or prevent the application from recognizing a newer desired presentation.

The application must distinguish a known successful update from a failed or uncertain update where the hardware API permits.

An uncertain hardware result must not be treated as proof that the desired image was successfully displayed.

The exact retry parameters and hardware lifecycle behavior are engineering decisions informed by real-device testing.

### Retained display content

E-paper retains its visible image without continuous power.

Refrain should preserve useful displayed content across temporary application and hardware failures when possible.

It must not clear the display merely because a recoverable software problem occurred.

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
8. Global selection history is never cleared by repetition-pool resets.
9. Priority determines preference among otherwise eligible unused quotations.
10. Equal-priority distinct quotation candidates have equal selection probability.
11. A daily selection is authoritative only after its complete snapshot and corresponding history updates have been durably committed.
12. An interrupted selection commitment must not leave inconsistent histories.
13. A committed daily snapshot is self-contained and independent of subsequent content-library changes.
14. Every required reveal-stage image is prepared from the committed daily snapshot.
15. Prepared images are persisted and reused rather than regenerated at every scheduled reveal.
16. Missing prepared images can be recovered without selecting new content.
17. A restart does not independently invalidate the committed daily selection or reset its reveal progression.
18. Reveal progression never moves backward within a committed selection.
19. A backward clock adjustment does not independently invalidate the active selection.
20. Forward clock adjustments advance selection and reveal state to the currently appropriate presentation when required.
21. Hardware failures do not invalidate committed selections or their history.
22. Ordinary operation does not require internet access or external services.
23. Public presentation does not grant privileged local control.
24. Future integrations must not become prerequisites for displaying ordinary quotations.

Architectural changes must be evaluated against these invariants before implementation work is accepted.