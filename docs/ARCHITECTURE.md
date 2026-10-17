# Architecture

Refrain is a self-contained, open-source e-paper presentation system for quotations and other short-form content.

The application selects an eligible content entry for each logical display day, progressively reveals information according to a configured schedule, and renders the current presentation to a physical e-paper display.

Refrain is intended primarily for personal and household use while remaining configurable and reusable by others.

This document defines the system architecture, component responsibilities, runtime behavior, persistent state, scheduling semantics, display behavior, and architectural boundaries.

Product scope and release sequencing belong in `docs/ROADMAP.md`.

Engineering standards, dependency selection, testing requirements, and implementation practices belong in `docs/ENGINEERING.md`.

## Architectural principles

### Keep the core independent of presentation hardware

Content loading, eligibility evaluation, daily selection, scheduling, and image composition must be executable without physical display hardware.

The e-paper display is an output device, not an authority over application state or content policy.

Hardware-specific code must not determine which content is selected or what information should be visible.

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

### Separate content, selection, presentation, and output

Content describes the information available for presentation.

Selection determines which entry is assigned to a display day.

Scheduling determines which parts of the selected entry should currently be visible.

Rendering composes the desired presentation image.

Display output communicates that image to physical hardware.

Each responsibility must remain independently understandable and testable.

### Preserve future flexibility without implementing future features

The initial architecture must not assume that content can only originate from song lyrics or that a physical display is the only possible presentation destination.

Future web presentation, public publishing, and external actions must be possible without replacing the core content-selection model.

These capabilities must not be implemented merely to demonstrate extensibility.

## Target platform

The initial deployment targets:

- Raspberry Pi 3 B+;
- Raspberry Pi OS Lite;
- Python;
- Waveshare 13.3-inch e-Paper HAT+ (E);
- 1600 × 1200 display resolution.

The display uses Spectra 6 color e-paper technology.

The intended presentation is predominantly black typography on a paper-white background. Color is available for restrained decorative use.

The initial display is a full-frame output device. Refrain must not depend on partial refresh, animation, or frequent screen updates.

Other Linux hosts may be used for content, scheduling, and rendering development without the physical display.

Support for additional display hardware is not an initial product requirement, although hardware-specific assumptions must remain isolated within the display-output responsibility.

## Terminology

**Content Entry:** A uniquely identified collection of presentation content and associated metadata.

**Content Library:** The validated collection of available content entries.

**Display Day:** A logical daily interval beginning at the configured local day-start time and ending immediately before the next day's start time.

**Display Date:** The local calendar date on which a display day begins. This date determines special-date eligibility.

**Selection Pool:** A collection of entries eligible under a particular selection rule.

**Daily Selection:** The content entry assigned to a display day.

**Reveal Stage:** The set of content fields scheduled to be visible at a given point in the display day.

**Presentation:** The selected content, current reveal stage, and applicable layout configuration.

**Rendered Image:** A complete image produced from the presentation independently of physical hardware.

**Display Backend:** The component responsible for initializing, updating, and recovering the physical display.

**Persistent State:** Information required to preserve daily selections and selection history across application restarts.

## High-level system structure

The primary logical flow is:

```text
Content files
    |
    v
Content library
    |
    v
Selection and persistent state
    |
    v
Scheduling and reveal evaluation
    |
    v
Presentation renderer
    |
    v
Complete rendered image
    |
    v
Display backend
    |
    v
Physical e-paper display
```

The application controller coordinates these responsibilities within one process.

The flow describes responsibility and ownership, not a required class hierarchy or directory structure.

Time and configuration are inputs to the relevant responsibilities. Neither is an independent source of content-selection policy.

## Content model

### General-purpose content

Refrain must support quotations and short-form content without assuming that an entry represents a song.

An entry may refer to a song, book, film, person, event, personal message, or another source.

Source-specific behavior must not be embedded in the core content-selection model.

### Semantic fields

Entries use a defined set of semantic fields rather than arbitrary user-defined presentation fields.

The initial model distinguishes:

- a stable entry identifier;
- the primary quotation or displayed text;
- optional source information;
- optional attribution information;
- eligibility and scheduling metadata;
- optional reveal-schedule overrides.

The primary text is required. Other presentation fields may be omitted when they are not meaningful for an entry.

The complete YAML field definitions, value formats, validation rules, and supported scheduling expressions will be established as part of the content-format specification.

Additional content metadata may be introduced when required by an accepted feature, without changing the meaning of existing fields.

### Entry identity

Every entry has a stable identifier independent of its YAML filename or directory location.

Identifiers must be unique within the content library.

Renaming or moving an entry's file must not create a new logical entry or invalidate its existing selection history.

Duplicate identifiers are invalid.

### Content storage

Content is initially maintained as YAML files, ordinarily with one entry per file.

Directory organization is an authoring convenience and must not determine an entry's identity.

The initial runtime loads and validates the content library during startup.

Automatic filesystem watching, interactive editing, and runtime content reloading are not required.

A restart is required to load changes to the content library.

### Content validation

Content must be validated before it becomes available for selection.

Validation must identify errors such as:

- missing required fields;
- duplicate entry identifiers;
- invalid field values;
- unsupported scheduling expressions;
- invalid reveal schedules.

Diagnostics must identify the affected entry or source file where possible.

Invalid content must not produce undefined selection or rendering behavior.

A malformed entry must not silently change the meaning of another entry.

## Display-day model

### Local time

Refrain uses an explicitly configured IANA timezone.

All display-day and reveal calculations use timezone-aware local time.

The application must not assume that every local calendar day contains exactly 24 elapsed hours.

Daylight-saving transitions and clock corrections must not create duplicate daily selections or cause previously revealed fields to become hidden during an otherwise unchanged display day.

### Day-start configuration

The display day begins at a configured local time.

For example, with a configured start time of 06:00:

- the display day for December 25 begins at 06:00 on December 25;
- it remains active until the next day's configured start;
- special-date eligibility is evaluated against December 25 throughout that interval.

The display date remains stable for the duration of its corresponding display day.

### Daily selection stability

Exactly one content entry is assigned to each display day during normal operation when eligible content is available.

Once selected, the entry remains assigned to that display day.

Application restarts, display failures, and missed reveal events must not independently trigger reselection.

If no valid eligible content is available, the application must report the condition rather than fabricate an entry.

## Content eligibility and selection

### Eligibility

The content-selection system determines which entries are eligible for a given display date.

The initial scheduling model supports:

- ordinary entries eligible on any display date;
- entries associated with recurring calendar dates;
- entries associated with specific calendar dates;
- entries associated with configured calendar periods.

More complex scheduling mechanisms are deferred unless required to represent the agreed initial use cases.

### Special-date precedence

Entries specifically eligible for the current display date take precedence over ordinary entries.

When at least one valid special-date entry is eligible, selection is made from the corresponding special-date pool.

When no special-date entry is eligible, selection uses the ordinary pool.

Entries intended only for special occasions do not automatically participate in ordinary-day selection.

An entry may participate in both contexts only when its eligibility explicitly permits it.

### Selection pools and repetition

Refrain avoids repetition by exhausting eligible entries before selecting an entry again from the same selection cycle.

Ordinary and special-date selections maintain independent selection histories.

An entry participating in one selection context does not consume its availability in another context.

When the eligible entries in a selection cycle have been exhausted, the cycle may begin again.

The exact order within a cycle need not be predictable, but selection must not repeatedly choose an already-used entry while an unused eligible alternative remains available in that cycle.

Changes to pool membership must be handled without invalidating stable daily selections.

### Selection priority

Special-date eligibility overrides ordinary eligibility.

The detailed behavior when several different special-date rules match the same display date must be defined before implementation of overlapping scheduling rules.

Selection policy must not depend on file enumeration order or incidental filesystem behavior.

## Persistent state

### Required persistence

Refrain maintains sufficient state to preserve:

- the selected entry for the active display day;
- the display date associated with that selection;
- selection history required to enforce repetition rules;
- sufficient information to recover the active presentation if its original YAML entry becomes unavailable during a restart.

Persistent state must survive normal application shutdown and unexpected process termination.

State updates must avoid leaving partially written or internally inconsistent records.

### Recovery and missing content

A valid existing daily selection takes precedence over creating a new selection during startup.

If the selected entry is missing or invalid in the newly loaded content library, Refrain should recover the established daily presentation from previously persisted valid information when possible.

It must report the content inconsistency.

It must not silently substitute an unrelated entry for the current display day.

When neither a valid entry nor recoverable presentation information exists, the application must report the failure and avoid presenting fabricated content.

Selection-history inconsistencies must not cause application crashes or uncontrolled repetition.

### Persisted and derived state

Persistent state owns historical decisions and facts.

Reveal state is calculated from the active selection, configured schedule, display date, and current time.

The current reveal stage is not independently authoritative persistent state.

Persisting redundant reveal-stage information must not become necessary for normal restart recovery.

## Progressive reveal

### Cumulative presentation

Refrain progressively reveals information associated with the selected entry.

The primary quotation appears at the first scheduled presentation stage.

Additional information, such as source and attribution, appears at later configured stages.

Reveals are cumulative. Information that has already become visible remains visible for the remainder of the display day.

Optional fields that are absent from an entry are omitted rather than displayed as empty placeholders.

### Schedule configuration

A global reveal schedule defines the default timing for supported semantic fields.

Individual entries may override the default schedule.

Overrides apply only to the entry to which they belong.

Reveal schedules must be validated to prevent impossible or contradictory behavior.

Reveal scheduling is evaluated within the current logical display day.

### Startup and missed events

On startup, Refrain determines the active display day and the reveal stage appropriate to the current time.

It does not restart the reveal sequence merely because the application restarted.

If an update was missed while the application was stopped, the next successful rendering uses the currently appropriate stage.

Missed intermediate stages do not need to be displayed sequentially.

### Clock changes

Time corrections must not cause an earlier reveal stage to replace a later stage within the same uninterrupted display day.

The application must reevaluate scheduling after significant clock changes and prevent duplicate selection at display-day boundaries.

## Presentation and rendering

### Rendering independence

The renderer accepts validated content, the active reveal stage, and layout configuration.

It produces a complete image without accessing the physical display.

The renderer must not select content, modify selection history, or determine application lifecycle policy.

Rendered output must be testable and inspectable without Raspberry Pi display hardware.

### Initial visual design

The initial release provides one configurable layout.

Its intended appearance is that of a carefully typeset printed page rather than a conventional electronic interface.

The design prioritizes:

- readable typography;
- generous whitespace;
- restrained visual decoration;
- a predominantly paper-white background;
- dark text with optional color accents.

Layout configuration may expose meaningful properties such as typography, spacing, alignment, and margins.

A general-purpose theme engine, arbitrary layout scripting, and multiple layout templates are not required.

### Stable progressive layout

The primary content retains stable placement across reveal stages.

Space for later source and attribution information is reserved in the composition.

Revealing a new field must not cause the primary quotation to move or require the entire page to be reflowed merely because that field becomes visible.

Text layout must accommodate varying entry lengths within the available presentation regions.

Content that cannot be rendered legibly within the supported layout must be handled explicitly rather than silently clipped or truncated.

### Rendered-image comparison

The application should avoid unnecessary physical refreshes when the desired rendered image has not changed.

The renderer remains independent of whether or when the display backend decides to submit an image to hardware.

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
2. Load and validate the content library.
3. Read persistent application state.
4. Determine the current display day.
5. Recover the existing daily selection or create a new selection if required.
6. Determine the currently appropriate reveal stage.
7. Render the intended presentation.
8. Initialize and update the display as required.
9. Continue operating until shutdown.

The implementation may organize these operations differently provided their externally observable behavior is preserved.

### Normal operation

The application waits for the next meaningful scheduling event.

It must not rely on frequent polling or busy waiting to determine ordinary reveal times.

At each relevant event, the application reevaluates the desired presentation and updates the display when necessary.

### Shutdown

Normal shutdown must safely release owned software and hardware resources.

Shutdown must not intentionally erase the retained e-paper image.

### Failure isolation

Recoverable hardware failures should not invalidate content selection or persistent history.

Content-validation failures should not produce uncontrolled hardware operations.

An unrecoverable configuration or state error must be reported clearly rather than disguised as normal operation.

## Future interfaces and integrations

### Companion web presentation

A companion web experience is planned for a later release.

It should obtain the information required for presentation without assuming that a browser and e-paper display must consume identical rendered image files.

Web presentation must not become responsible for daily content selection.

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

External actions must remain separate from the core content-selection and rendering responsibilities.

An action is not required to display an entry.

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
3. A valid daily selection survives application restarts.
4. A restart does not restart the day's reveal progression.
5. Reveal progression is cumulative within a display day.
6. Special-date selection takes precedence over ordinary selection.
7. Repetition history is maintained independently for distinct selection contexts.
8. A malformed content entry cannot silently produce a different daily selection.
9. Hardware failure does not automatically invalidate the current content selection.
10. Ordinary operation does not require internet access or external services.
11. Public presentation does not grant privileged local control.
12. Future integrations must not become prerequisites for displaying ordinary quotations.

Architectural changes must be evaluated against these invariants before implementation work is accepted.