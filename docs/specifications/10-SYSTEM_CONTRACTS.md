# System Contracts

## Operating model and boundaries

Refrain is a self-contained, open-source presentation system for quotations and other short-form literary content.

The normal resident application selects an eligible quotation for each logical display day, progressively reveals associated information according to its committed schedule, prepares complete images, and publishes the currently required presentation to configured destinations.

Refrain is intended primarily for personal and household use while remaining configurable and reusable by others.

Refrain supports physical e-paper and other presentation destinations, and accepts quotations beyond song lyrics.

Content discovery, validation, eligibility, selection, persistence, scheduling, artistic resolution, and rendering must operate independently of physical display hardware.

The resident application coordinates these responsibilities within one Python process.

Independent publication consumers are separately executed and supervised. They are not part of the resident process and are not required for ordinary resident operation.

Ordinary operation must not require:

- Internet connectivity.
- A cloud service.
- A database server.
- An HTTP server.
- A message broker.
- An external content-management application.
- An independent publication consumer.

Use existing operating-system facilities for process management, logging, local timekeeping, filesystem storage, and service supervision where appropriate.

Do not introduce additional mandatory infrastructure, a custom service manager, or general-purpose extensibility frameworks without a demonstrated requirement.

### Responsibility boundaries

Maintain separation between:

- Content discovery and validation.
- Quotation eligibility and selection.
- Authoritative operational-state commitment.
- Publication checkpoint construction and recovery.
- Reveal scheduling.
- Artistic resolution and image preparation.
- Literary rendering and destination visual conversion.
- Publication coordination and acknowledgement.
- Backend delivery and filesystem publication.
- Application lifecycle and resource ownership.

Components must communicate through narrow, explicit interfaces.

Content selection must not depend on physical hardware, network delivery, or publication consumers.

Rendering and artistic preparation must not determine literary eligibility, choose a new committed quotation, or advance authoritative reveal progression.

Backends must not perform literary selection, scheduling, or artistic resource resolution.

Independent consumers must not modify resident operational state, publication checkpoints, prepared-image caches, or Refrain-owned publication datasets.

An explicitly selected daily quotation remains authoritative independently of image preparation or destination delivery success.

Do not introduce capabilities solely to demonstrate extensibility.

Material architectural changes require approval before implementation establishes new behavior.

## Supported platform and portability

The primary deployment target is Raspberry Pi OS Lite, 64-bit, on Raspberry Pi hardware using Python 3.13 or newer.

The Raspberry Pi 3B+ is the minimum supported Raspberry Pi platform and the hardware-validation baseline.

The supported Waveshare 13.3-inch e-Paper HAT+ (E) has a fixed 1600 × 1200 landscape output and uses Spectra 6 color technology.

The hardware backend owns the vendor driver, SPI/GPIO integration, controller lifecycle, and physical transfer requirements.

The renderer and other hardware-independent components must not depend on Raspberry Pi-specific drivers or interfaces.

The system must not rely on hardware characteristics exclusive to the Raspberry Pi 3B+ when those assumptions are unrelated to the supported device contract.

The Waveshare backend uses full-frame updates. Refrain must not require partial refresh, animation, or frequent screen updates.

The intended presentation emphasizes readable dark typography, a predominantly paper-white background, generous whitespace, and restrained decorative color.

### Platform commitments

Raspberry Pi OS Lite is the primary supported deployment platform.

Windows is a supported hardware-independent development and resident-testing platform. Its applicable functionality includes content processing, selection, scheduling, persistence, rendering, desktop presentation, filesystem publication, and local runtime control.

Windows does not provide the Raspberry Pi-specific Waveshare hardware interface.

Other Linux distributions may work with compatible system facilities but are not individually validated or maintained as supported deployments.

macOS is not a supported or maintained platform. Existing harmless path conventions or portable code may remain, but their presence does not establish a support or testing commitment.

Hardware-independent components must avoid unnecessary operating-system assumptions and remain testable on the supported Windows and Linux environments.

Backend-specific dependencies must be isolated so that ordinary imports, rendering, configuration, persistence, and non-hardware destinations do not require GPIO, SPI, a vendor driver, or a graphical desktop environment.

Requested presentation aspect ratios and output resolutions are independent of the physical Waveshare panel's fixed geometry, subject to the supported finished-image limits.

The output backend owns only its defined delivery and hardware-format responsibilities.

Physical hardware validation is distinct from hardware-independent testing. Mocked driver success does not establish correct physical display behavior.

The runtime must use bounded memory and avoid unnecessary background processing. Quality requirements for infrequent daily image preparation must not be rejected solely because preparation requires additional computation.

Platform paths, deployment requirements, service supervision, and permissions belong to [Installation and Service Operation](80-INSTALLATION_AND_SERVICE_OPERATION.md).

## Shared terminology

**Content Entry:** A uniquely identified collection of one or more quotations and shared authored metadata.

**Quotation:** One individual literary message within a content entry. Quotations are the units of daily selection.

**Quotation Identity:** The normalized quotation text used for repetition tracking. Identical normalized text has one repetition identity across content-entry occurrences.

**Content Library:** The collection of content entries accepted through completed discovery and validation. Incomplete source enumeration does not establish a usable effective library for new selection.

**Display Day:** The logical presentation interval determined by host-local civil time and the configured day-start boundary.

**Display Date:** The local calendar date associated with the logical display day. It determines content eligibility and identifies the committed daily selection's date.

**Date Specificity:** The priority of a matching calendar eligibility context, from highest to lowest: year-month-day, month-day, day, month, and ordinary eligibility.

**Selection Pool:** The quotations eligible within the highest applicable date-specificity context for a display date.

**Priority:** An optional signed integer inherited by quotations from their content entry. Higher values receive selection preference. The default is zero.

**Repetition History:** Persistent, selectively resettable quotation identities used to avoid repetition until the relevant eligible pool is exhausted.

**Global History:** A retention-bounded, best-effort chronological record of committed selection events. It is not authoritative for recovery, current selection, repetition eligibility, or reveal progression.

**Daily Selection:** The quotation committed for one logical display date.

**Selection Revision:** A monotonically increasing identifier assigned to each successful operational-state selection commitment.

**Daily Selection Record:** The authoritative operational-state snapshot of the committed quotation, complete selected literary content, captured content preferences and actions, effective schedule, display date, and selection revision. It does not contain resolved artistic presentation choices or output-specific raster data.

**Selection Commitment:** The successful atomic persistence of a daily selection, its revision, updated repetition history, initial reveal progression, and scheduling context in authoritative operational state.

**Persistent State:** The authoritative `state.json` operational record containing the current committed selection, selection revision, repetition history, scheduling context, and highest reveal stage reached.

**Publication Checkpoint:** The single evolving `publication.json` record associated with a committed selection. Its content-only form records committed literary data; its completed content-and-presentation form additionally records destination-independent artistic choices.

**Canonical Presentation:** The resolved destination-independent artistic choices persisted in the completed publication checkpoint, including style, visual resources, font and role faces, colors, presentation geometry settings, and QR policy.

**Effective Presentation:** The resolved presentation used to prepare one destination's image after applying applicable destination overrides, resource recovery, and output-dependent decisions. It does not replace or modify the persisted canonical presentation.

**Reveal Stage:** One cumulative visibility state in the committed selection's ordered reveal sequence. Fields resolved to the same absolute reveal instant share a stage.

**Presentation Aspect Ratio:** The declared ratio selecting the aspect-specific design canvas and determining the exact-ratio presentation canvas.

**Design Canvas:** The high-resolution, aspect-specific graphical-composition and authored-layout space derived from the fixed 3840 × 2400 reference envelope.

**Presentation Canvas:** The raster on which literary text, QR, and diagnostic overlays are laid out and rendered for one output specification.

**Output Specification:** One declared presentation aspect ratio and requested output resolution, independently supplied by the applicable destination or viewer operation.

**Output Image:** The completed presentation image, optionally resized exactly once as a whole from the presentation canvas to the requested output dimensions.

**Prepared Image:** A complete, persisted output image representing one reveal stage for a committed selection, output specification, and compatible effective presentation requirements.

**Prepared Stage Set:** The independently committed complete collection of compatible reveal-stage images for one preparation group and output specification.

**Destination:** One configured publication target with its own identity, output specification, audience, effective presentation requirements, participation state, and acknowledgement.

**Destination Identifier:** The globally unique, opaque configured ID identifying one destination for runtime routing, publication metadata, and applicable filesystem storage. Its spelling does not imply backend type or capabilities.

**Display Backend:** A resident-owned component that synchronously publishes a complete image through a configured destination. Direct backends present images on local hardware or desktop windows; `publish` commits completed filesystem datasets.

**Publication Event:** One completed destination publication attempt identified by its publication ID, timestamp, destination, type, and output specification. Completed scheduled events additionally describe literary content and effective presentation.

**Publication Metadata:** A versioned JSON document following the checkpoint, completed scheduled, or completed transient forms defined by the Publication schema.

**Filesystem Publication Dataset:** One complete image and completed metadata document referenced by a verified current manifest in a Refrain-owned destination directory.

**Independent Consumer:** A separately supervised process that reads validated filesystem publications without participating in resident selection, scheduling, backend ownership, or publication commitment.

**Renderer:** The hardware-independent literary rendering component that measures, fits, positions, and draws the quotation and optional literary fields within resolved presentation geometry.

**Presentation:** The literary content, visibility, and resolved artistic requirements used to construct a complete output image. Scheduled publication derives its effective presentation from the committed selection and its canonical publication checkpoint.

## Component responsibilities and processing flow

The normal resident coordinates four primary phases:

1. Selection.
2. Commitment.
3. Preparation.
4. Publication.

A committed selection has one authoritative literary identity and reveal schedule, regardless of the number or types of configured destinations.

The normal logical flow is:

```text
Content discovery and validation
        |
        v
Eligibility, specificity, repetition, and priority
        |
        v
Quotation selection
        |
        v
Atomic operational-state commitment
(state.json: content, revision, history, reveal, schedule)
        |
        +----> Best-effort global-history recording
        |
        v
Content-only publication checkpoint
(publication.json)
        |
        v
Destination-independent artistic resolution
        |
        v
Complete presentation checkpoint
(publication.json)
        |
        v
Destination overrides and effective requirements
        |
        v
Complete compatible reveal-stage image sets
        |
        v
Scheduling and publication coordinator
        |
        +----> Direct display backends
        |       window / waveshare-13in3-e
        |
        +----> publish backend
                |
                v
        Image + completed publication metadata
                |
                v
        Verified filesystem manifest commit
                |
                v
        Independent read-only consumers
```

The diagram describes logical ownership and required dependencies rather than a mandatory class hierarchy or strictly sequential execution of independent activities.

Operational-state commitment precedes publication checkpoint construction. The content-only checkpoint precedes completion of destination-independent artistic resolution. The completed presentation checkpoint precedes destination-specific scheduled image preparation.

The publication checkpoint is a single evolving file, not separate durable canonical and effective presentation records.

Global-history recording is best-effort and does not participate in operational-state or checkpoint atomicity.

A failed post-commit operation must not cause quotation reselection or erase a valid committed selection.

A successful reveal advancement updates authoritative operational state before synchronizing checkpoint visibility. Destination publication acknowledgement is independent of reveal progression.

For each destination, image preparation uses the committed selection and completed checkpoint, then derives its effective presentation without modifying canonical artistic choices.

Complete compatible stage sets are cached independently. Destinations share images only when their output specifications and effective presentation requirements are compatible.

The coordinator selects the currently required prepared stage and maintains acknowledgement separately for each destination.

A direct backend receives the corresponding complete image. A `publish` destination receives its complete image and independently finalized metadata, then commits a verified filesystem dataset.

The application supplies each scheduled publication's actual effective presentation, output specification, event identity, timestamp, and audience-filtered actions.

Independent consumers read verified publication datasets. They do not participate in the resident's selection, commitment, or acknowledgement.

Externally submitted transient finished images bypass scheduled literary selection and artistic preparation. They are published through the resident's existing coordinator without modifying committed selection, checkpoint, history, or reveal progression.

Startup information views and the no-eligible-content fallback follow their separately specified lifecycle behavior. Neither creates a synthetic daily selection.

The detailed contracts belong to the applicable subsystem specifications.

## Ownership of mutable state

Every mutable application resource must have one identifiable authoritative owner.

The principal ownership boundaries are:

| Resource | Owner |
|---|---|
| Authored content and resource files | User or installed package |
| Validated content and resource registries | Content and resource-loading components |
| Committed selection, revision, repetition history, schedule, and reveal progress | Operational state (`state.json`) |
| Destination-independent resolved artistic choices | Completed publication checkpoint (`publication.json`) |
| Global selection-event history | Best-effort global-history recorder |
| Complete prepared image sets and integrity associations | Derived prepared-image cache |
| Effective destination presentation and completed metadata construction | Preparation and application publication-finalization components |
| Desired scheduled presentation and per-destination acknowledgements | Resident publication coordinator |
| Backend resources and active publication operations | Resident backend instances and their coordinator |
| Current filesystem publication datasets | Resident `publish` backend |
| HTTP serving and other consumer-side state | Independent consumer processes |

Validated source content and committed selection snapshots should be represented with immutable values where practical.

Components must not modify state owned by another responsibility merely because a mutable object reference is available.

The current committed selection remains authoritative until a different logical display date requires and successfully commits another selection.

A valid completed publication checkpoint preserves canonical artistic choices across restart, configuration changes, and resource-pool changes.

Losing derived prepared images does not invalidate the selection or authorize canonical reselection.

Losing the artistic checkpoint permits reconstruction from authoritative operational state with an actionable warning that resolved appearance may differ.

Destination-specific effective values and publication acknowledgements must not become competing authorities for literary selection or canonical presentation.

Completed publication metadata represents the event at which it was finalized and is not retroactively rewritten when later reveal progress occurs.

Independent consumers cannot acquire resident authority by reading a publication dataset.

## Failure isolation and recovery boundaries

Failure handling must preserve the ownership boundaries above.

The following behaviors are required:

- Failed content discovery or validation must not create an incomplete committed selection.
- A healthy effective library with no eligible quotation uses the approved literary fallback without synthetic selection or history changes.
- A failed publication checkpoint update must not invalidate a successfully committed quotation.
- A damaged or missing checkpoint must not replace committed literary content or reduce reveal progress.
- A rendering or prepared-image cache failure must not trigger literary reselection.
- An invalid reveal-stage value must not be committed or silently treated as valid progression.
- Global-history failure must not prevent ordinary committed selection recovery or presentation.
- A failed destination must not invalidate successful publication to independent destinations.
- A failure affecting one shared backend instance must be reported for the destinations actually dependent on that instance.
- A slow or blocked backend operation must not prevent independent backend instances or scheduling evaluation from progressing.
- An uncertain publication outcome must not be reported as confirmed success or failure.
- A failed independent consumer must not invalidate a completed filesystem publication.
- Restart must preserve valid current-format committed selection state and nonregressing reveal progression.
- Unsafe operational recovery must not intentionally clear retained physical e-paper content.

Use bounded retries and explicit recovery opportunities where applicable. Do not introduce a general transaction framework, replay journal, or complex recovery subsystem without an established requirement.

Scheduled destination acknowledgement, transient admission, backend retry, and shutdown behavior belong to [Destinations and Runtime Control](60-DESTINATIONS_AND_RUNTIME_CONTROL.md) and [Scheduling and Application Lifecycle](40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md).

Persistent recovery belongs to [Selection and Persistence](30-SELECTION_AND_PERSISTENCE.md).

Filesystem dataset commitment and consumer recovery belong to [Filesystem Publication and Consumers](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md).

## Architectural guarantees

The following invariants must remain true as the project evolves:

1. One normal resident owns the configured backend instances and protected runtime resources for a per-user installation.
2. Literary selection and scheduling are independent of physical hardware, publication delivery, and independent consumer availability.
3. Authoritative operational state owns committed literary selection, repetition history, revision, scheduling context, and highest reveal progress.
4. The completed publication checkpoint is the sole durable authority for destination-independent resolved artistic choices.
5. A committed quotation must not be reselected because checkpoint construction, artistic preparation, cache regeneration, global-history recording, or destination delivery failed.
6. Reveal progression never regresses within one committed selection; destination acknowledgement does not determine authoritative reveal progress.
7. Every destination has independent identity, output requirements, participation, publication status, and acknowledgement, even when images or backend instances are shared.
8. Destination-specific preparation and completed publication metadata must reflect effective rendering decisions without modifying canonical artistic choices.
9. Transient publications do not mutate scheduled selection, persistent checkpoints, repetition history, reveal progression, or scheduled publication acknowledgement.
10. The resident has no HTTP-service responsibility. Filesystem `publish` is its sole non-direct backend, and independent consumers do not own resident scheduling or publication commitment.
11. Completed scheduled publication actions are filtered to the destination's explicitly configured audience before exposure; filtering does not grant filesystem or operational access.
12. Failures and uncertain results must remain isolated and accurately reported without fabricating success, silently substituting content, or damaging unrelated committed state.

Architectural changes must be evaluated against these invariants before implementation is accepted.

