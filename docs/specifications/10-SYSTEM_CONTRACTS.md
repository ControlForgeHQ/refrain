# System Contracts

## Operating model and boundaries

Refrain is a self-contained, open-source e-paper presentation system for quotations and other short-form content.

The application selects an eligible quotation for each logical display day, progressively reveals information according to a configured schedule, and presents pre-rendered images on a physical e-paper display.

Refrain is intended primarily for personal and household use while remaining configurable and reusable by others.

Content loading, eligibility evaluation, quotation selection, scheduling, and image composition must be executable without physical display hardware.

The e-paper display is an output device, not an authority over application state or content policy.

Hardware-specific code must not determine which quotation is selected or what information should be visible.

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

Content entries organize quotations and their shared metadata.

Selection determines which quotation is assigned to a display day.

Commitment makes the selected quotation and its associated presentation information authoritative.

Preparation generates and persists all images required for the committed selection and its configured output specifications.

Scheduling determines which reveal stage should currently be presented.

Display output publishes the prepared image variant appropriate to each configured destination.

Each responsibility must remain independently understandable and testable.

The initial architecture must not assume that content can only originate from song lyrics or that a physical display is the only possible presentation destination.

Future web presentation, public publishing, and external actions must be possible without replacing the core quotation-selection model.

These capabilities must not be implemented merely to demonstrate extensibility.

Content selection does not depend on physical display hardware.

Rendering can be tested without physical display hardware.

Ordinary operation does not require internet access or external services.

Implementations must conform to the applicable authoritative system and subsystem specifications under `docs/specifications/`.

Maintain separation between:

- content loading and validation;
- quotation eligibility and selection;
- persistent state and commitment;
- reveal scheduling;
- image preparation and rendering;
- display output;
- application lifecycle coordination.

Components should communicate through narrow, explicit interfaces.

Do not move content-selection policy into the renderer or display backend.

Do not introduce hardware dependencies into code that is intended to run without physical display hardware.

If an implementation appears to require a material architectural change, the change must be reviewed before the implementation establishes new behavior.

## Supported platform and portability

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

## Shared terminology

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

**Daily Selection Record:** A persistent copy of the selected quotation, its captured content properties, and its resolved canonical presentation, independent of the original content entry. Destination-specific effective values and raster geometry are resolved during image preparation.

**Canonical Presentation:** The destination-independent artistic presentation resolved once for a committed daily selection, including its presentation style, selected visual resources, font and faces, colors, and QR policy.

**Effective Presentation:** The canonical presentation after applying one destination's supported overrides and resolving any resulting geometry defaults.

**Selection Commitment:** The successful durable recording of a daily selection, updated repetition history, selection revision, reveal progress, and scheduling context as one consistent authoritative state.

**Reveal Stage:** A cumulative set of content fields eligible for presentation at a particular point in the configured reveal schedule.

**Presentation Aspect Ratio:** The declared ratio that selects the design canvas and determines the exact-ratio dimensions of the presentation canvas.

**Design Canvas:** The high-resolution, aspect-specific graphical composition and authored-layout space selected from the fixed 3840 × 2400 reference envelope. It is independent of requested output resolution.

**Presentation Canvas:** The raster on which literary layout, text, QR, and diagnostic overlays are resolved and rendered for one output specification.

**Output Image:** The completed presentation canvas, optionally resized once as a whole to the exact requested dimensions. It is the image persisted as a prepared PNG and delivered to display backends.

**Output Specification:** The declared presentation aspect ratio and requested output resolution for a configured destination, according to that backend's configuration and defaults.

**Destination Identifier:** The runtime-supplied opaque identifier for one configured output destination. It is used only to route a runtime-control request.

**Prepared Image:** A persisted output image representing one reveal stage of a committed daily selection for one output specification and its effective presentation requirements. Destinations may share it only when both the output specification and preparation requirements match.

**Presentation:** The selected quotation, associated metadata, reveal schedule, and applicable layout configuration used to produce prepared output images. A scheduled presentation has one canonical presentation and a derived effective presentation for each destination.

**Renderer:** The hardware-independent component responsible for composing complete presentation images.

**Display Backend:** The component responsible for presenting the prepared output image matching its configured output specification through a destination, including directly connected display hardware or a network-accessible image service.

**Persistent State:** The authoritative operational state containing the current daily selection, selection revision, active repetition history, reveal progress, and scheduling context required for recovery across application restarts.

## Component responsibilities and processing flow

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

## Ownership of mutable state

Mutable application state must have an identifiable owner.

Distinguish between:

- validated source content;
- uncommitted selection candidates;
- authoritative operational state, including the current daily selection, selection revision, active repetition history, and reveal progress;
- independently retained global selection history;
- prepared presentation artifacts;
- backend-owned presentation state.

Components must not modify state owned by unrelated responsibilities merely because a reference to that state is available.

Prefer immutable values for validated content, committed selections, and resolved presentation configuration where practical.

## Failure isolation and recovery boundaries

Recoverable failures should not require manual intervention.

Failure handling must respect the boundaries established by the architecture.

In particular:

- selection failure must not create an incomplete committed selection;
- rendering failure must not trigger reselection;
- display failure must not alter quotation history;
- restart must not discard valid current-format selection state;
- recovery must not hide previously reached reveal stages.

Do not add an elaborate recovery framework when a simple, bounded retry or restart-safe operation is sufficient.

## Architectural guarantees

The following must remain true as the project evolves:

Architectural changes must be evaluated against these invariants before implementation work is accepted.

## Integration limits and non-goals

The initial Version 0.1 implementation does not require:

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

The target architecture does include separately supervised publication consumers, but no general service-registration or service-management framework. Other capabilities may be reconsidered when a concrete use case justifies them.

Future integrations must not become prerequisites for displaying ordinary quotations.
