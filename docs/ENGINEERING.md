# Engineering

This document defines how Refrain is developed, implemented, tested, deployed, and maintained.

It is authoritative for engineering principles, coding standards, dependency management, persistent-storage implementation expectations, logging, validation, reviews, and release practices.

Runtime architecture and behavioral contracts belong in `docs/ARCHITECTURE.md`.

Product direction and release sequencing belong in `docs/ROADMAP.md`.

The content-format specification owns the public YAML configuration and content contracts.

## Engineering principles

### Prefer correctness over convenience

Refrain is intended to operate unattended for extended periods.

An incorrect selection, inconsistent persistent state, missed reveal, or unnecessary display refresh can undermine the intended experience.

Prefer behavior that can be demonstrated correct over behavior that is merely convenient to implement.

Test assumptions where possible rather than encoding speculative behavior into the application.

### Keep the implementation small

Prefer straightforward Python code and a limited dependency set.

Avoid unnecessary frameworks, background services, abstractions, and configuration options.

Do not introduce complexity solely to accommodate hypothetical future features.

A small amount of duplication is preferable to introducing an abstraction without a demonstrated benefit.

### Preserve architectural boundaries

Implementations must conform to `docs/ARCHITECTURE.md`.

Maintain separation between:

- content loading and validation;
- quotation eligibility and selection;
- persistent state and commitment;
- reveal scheduling;
- image preparation and rendering;
- physical display output;
- application lifecycle coordination.

Components should communicate through narrow, explicit interfaces.

Do not move content-selection policy into the renderer or display backend.

Do not introduce hardware dependencies into code that is intended to run without physical display hardware.

If an implementation appears to require a material architectural change, the change must be reviewed before the implementation establishes new behavior.

### Make state ownership explicit

Mutable application state must have an identifiable owner.

Distinguish between:

- validated source content;
- uncommitted selection candidates;
- committed daily snapshots;
- permanent selection history;
- active repetition history;
- persisted reveal progress;
- prepared presentation artifacts;
- physical display state.

Components must not modify state owned by unrelated responsibilities merely because a reference to that state is available.

Prefer immutable values for validated content, committed selections, and resolved presentation configuration where practical.

### Design for unattended recovery

Recoverable failures should not require manual intervention.

Failure handling must respect the boundaries established by the architecture.

In particular:

- selection failure must not create an incomplete committed selection;
- rendering failure must not trigger reselection;
- display failure must not alter quotation history;
- restart must not discard a valid committed snapshot;
- recovery must not hide previously reached reveal stages.

Do not add an elaborate recovery framework when a simple, bounded retry or restart-safe operation is sufficient.

### Respect resource-constrained hardware

The initial development target is the Raspberry Pi 3 B+.

The Raspberry Pi Zero 2 W is a candidate for compact deployment.

Favor implementations that can operate within modest memory, CPU, and storage budgets.

Avoid unnecessary resident data, polling, heavyweight dependencies, and background processing.

Do not retain all decoded reveal-stage images in memory merely because they were generated together.

Use measurements from representative hardware to justify performance-related changes.

Correctness and maintainability take precedence over speculative micro-optimization.

### Prefer existing platform facilities

Use ordinary Linux facilities where they satisfy the requirement.

In particular:

- use systemd for supervised service operation;
- use standard process streams for application logging;
- use the local filesystem for ordinary application storage;
- use standard timezone facilities for local scheduling.

Avoid creating a custom service manager, log daemon, database service, or scheduler without a demonstrated need.

## Documentation model

Each project document has one authoritative responsibility.

### README.md

The project README is the user-facing entry point.

It describes what Refrain does, its current capabilities, installation, basic usage, and links to deeper documentation.

It does not own runtime architecture or future release requirements.

### docs/ROADMAP.md

The roadmap owns release goals, planned capabilities, sequencing, and future product scope.

It must not prescribe implementation details.

### docs/ARCHITECTURE.md

The architecture owns runtime responsibilities, behavior, lifecycle, state semantics, scheduling rules, and architectural invariants.

It answers:

> Where does this behavior belong, and how must the system behave?

### docs/ENGINEERING.md

This document owns coding conventions, implementation standards, dependency practices, validation expectations, and contributor requirements.

It answers:

> What standards must an implementation meet?

### Content-format specification

The content-format specification owns the supported YAML structure, field names, value types, defaults, validation rules, and examples.

Changes to the public content format must be documented in that specification.

### AGENTS.md

`AGENTS.md` routes automated contributors to the authoritative documentation and defines agent-specific guardrails.

It must not duplicate architecture, engineering standards, or roadmap requirements.

### Issues and pull requests

Issues define specific requested changes.

They should identify:

- the problem and desired result;
- the scope of the work;
- relevant constraints;
- explicit non-goals;
- observable acceptance criteria;
- additional validation requirements.

Pull requests record what was implemented, how it was validated, and any known limitations.

Do not duplicate project-wide engineering requirements in every issue.

### Maintaining documentation

When a change affects documentation:

1. Identify the document that owns the information.
2. Update that authoritative document.
3. Check other documents for stale or contradictory statements.
4. Replace duplicated requirements with references where appropriate.

A normal change should require edits to as few authoritative documents as practical.

## Python development

### Language and runtime

Refrain is implemented in Python 3.

Use a Python version supported by the targeted Raspberry Pi OS release.

Do not require a separately installed interpreter when the operating system's supported Python version meets the project's needs.

Avoid language features or third-party packages that unnecessarily exclude supported deployment platforms.

The project's minimum supported Python version must be established in the project metadata once implementation begins.

### Cross-platform development and testing

Hardware-independent components should use platform-neutral Python interfaces and avoid unnecessary operating-system-specific assumptions. Use `pathlib.Path` or other standard path APIs rather than constructing filesystem paths with hard-coded separators.

Tests should compare paths using native `Path` values or strings derived from them, not assume a particular separator in diagnostics. When testing intentionally platform-specific behavior, make the platform assumption explicit and keep that coverage scoped to the affected behavior.

Run hardware-independent tests on the development platforms available and record the operating system and Python version. Passing tests on a non-Linux system does not establish that full application deployment or hardware-specific behavior is supported or validated there.

### Coding style

Use:

- descriptive module, function, and variable names;
- standard Python naming conventions;
- explicit, readable control flow;
- small functions with clear responsibilities;
- type annotations for public and significant internal interfaces;
- ordinary exceptions for exceptional failures;
- context managers for resource ownership where appropriate.

Prefer the standard library unless an external dependency provides substantial value.

Avoid unnecessary classes when functions and simple data structures express the responsibility clearly.

Do not introduce a generic framework merely to avoid a few direct dependencies between well-defined components.

### Formatting and linting

Use Black for Python formatting and Ruff for linting.

The project uses a target line length of 120 characters.

Line length is a readability guideline rather than an absolute restriction. Prefer keeping a clear expression on one line when splitting it would make the code harder to understand.

Do not introduce artificial line breaks solely to satisfy historical terminal-width conventions.

Configuration belongs in `pyproject.toml` and must be applied consistently by contributors and automated checks.

Source files should not require editor-specific configuration to maintain consistent formatting.

Do not suppress diagnostics without a documented reason.

Formatting-only changes should not be mixed with unrelated behavior changes.

### Type annotations

Use Python type annotations to clarify interfaces and important data structures.

Type annotations should make the code easier to understand and maintain.

Do not introduce complicated generic types, protocols, or abstract class hierarchies solely to satisfy static typing.

A static type checker may be introduced when it provides demonstrated value.

### Error handling

Errors should be identified at the lowest layer that can accurately describe them.

Recovery and lifecycle decisions belong to the component with sufficient context to make those decisions.

For example:

- the content loader reports invalid YAML or content fields;
- the selection component reports the absence of eligible quotations;
- the persistence component reports an unsuccessful commit;
- the renderer reports image-preparation failure;
- the display backend reports communication or refresh failure;
- the application controller determines whether to retry, continue, or terminate.

Do not hide materially different failures behind a generic success/failure result when the distinction affects correct recovery.

Conversely, avoid creating elaborate exception hierarchies without a demonstrated need.

### Comments and documentation strings

Comments should explain intent, architectural constraints, or non-obvious behavior.

Do not write comments that simply restate the code.

Document public interfaces and complex behavior where that documentation materially improves understanding.

Use precise terminology consistent with the architecture.

## Dependencies

### Dependency policy

Keep the runtime dependency set small and explicit.

Dependencies must be justified by required functionality.

Prefer maintained libraries with clear licensing and support for the target Python and Linux environments.

Do not introduce dependencies for deferred roadmap features.

Development and testing dependencies must be distinguishable from production runtime dependencies.

### Dependency isolation

Use a project-local Python virtual environment for development.

A virtual environment is also preferred for deployed application dependencies when practical.

The virtual environment must not be committed to the repository.

Runtime dependencies should be installed using a reproducible, documented process.

Avoid modifying the operating system's Python package environment through unrestricted global `pip` installations.

### Dependency versions

Declare the supported dependency versions or ranges in project metadata.

Dependencies should be installed reproducibly for validation and deployment.

Updates must be tested against the supported Python version and target platform.

Avoid unnecessarily restricting compatible patch releases unless compatibility evidence justifies the restriction.

### Hardware-specific dependencies

Keep hardware-specific imports and dependencies isolated within the display backend.

Content loading, selection, persistence, scheduling, and rendering tests must not require Raspberry Pi GPIO or SPI libraries.

The hardware-independent application must remain importable on development systems without the physical display attached.

## Content and configuration handling

### YAML processing

Use a maintained YAML parser with safe loading behavior.

Do not deserialize arbitrary Python objects from content files.

Validate parsed content against the supported content-format contract before making it available for selection.

Do not depend on YAML mapping order or filesystem enumeration order for selection policy.

### Configuration

Configuration must be explicit, documented, and validated.

Both application configuration and content entries use YAML, with separate schemas defined in `docs/CONTENT_FORMAT.md`.

Use sensible defaults where the product requirements establish them.

Do not silently substitute defaults for invalid user-supplied values when doing so could alter scheduling, selection, or presentation behavior.

Application configuration must strictly validate explicitly registered resources, including fonts.

An unavailable font preference in an otherwise valid content entry is not an application configuration failure. Report the unavailable preference and apply the documented default-font fallback.

Resolve effective per-entry configuration, including font selection, before committing a daily snapshot.

After commitment, the selected presentation must not depend on changes to the original content or configuration files.

### File paths

Use `pathlib` for filesystem path handling.

Do not assume that application files, content files, persistent state, and generated images are located in the same directory.

Support clearly defined locations for configuration, content, and persistent state.

Avoid assumptions tied to a particular username, home directory, mount point, or installation path.

Resolve relative paths consistently and document their interpretation.

## Persistent storage

### Storage approach

Use ordinary local filesystem storage for Refrain's initial persistent state.

A database service is not required.

The storage representation should remain simple, inspectable, and suitable for recovery after unexpected termination.

The architectural commitment and recovery requirements determine the storage design.

Do not select a persistence format solely because it is convenient to serialize individual objects.

### Atomic selection commitment

A daily selection becomes authoritative only when its snapshot, global-history update, repetition-history update, and required scheduling context have been committed consistently.

The implementation must provide one logical commit point for this state.

Independent file writes without an appropriate transaction or recovery mechanism do not satisfy this requirement.

A suitable approach is to construct a complete next-state generation and publish it through one atomic filesystem operation.

When atomic replacement is used, temporary and final artifacts must reside on a filesystem that supports the required replacement semantics.

Where durability across sudden power loss is required, the implementation must also account for flushing file data and relevant directory metadata.

Do not equate a successful file close or rename with guaranteed power-loss durability without considering the filesystem and operating-system semantics.

### Recovery

Persistent state must be validated when loaded.

Incomplete or invalid state must not be silently treated as a valid committed selection.

Recovery must not duplicate committed history entries.

A failure after selection commitment must preserve the committed quotation.

Missing prepared images must be regenerated from the snapshot without changing selection history.

Recovery behavior must be covered by automated tests using controlled failures at meaningful transaction boundaries.

### Persistent state versioning

Persistent state must carry sufficient format information to distinguish compatible and incompatible representations.

Changes to persisted state structures require explicit compatibility consideration.

Do not silently interpret incompatible state using an unrelated schema.

Migration facilities should be added when a real format change requires them, rather than implementing speculative migration infrastructure in advance.

### Version 0.1 state file

The implementation stores the complete committed selection state in one UTF-8 JSON file. Its envelope contains `format_version`, a complete state payload, and a SHA-256 checksum of the canonical payload. Format version 2 includes `revision`, the current self-contained `snapshot`, an ordered `global_history` array, sorted `repetition_history` identities, and `highest_reveal_stage`. The snapshot embeds the selected font bytes as base64 together with its stable identifier and content digest; resolved presentation metadata, reveal schedule, layout, and scheduling context are stored with it. Reveal progress is stored outside the immutable snapshot and belongs to the selection identified by the payload's revision.

Format version 1 stored reveal progress inside the snapshot. This pre-release format is explicitly unsupported by the version 2 reader: it raises `UnsupportedStateVersionError` without rewriting the file. There is no automatic migration or reset. Preserve an older file for inspection rather than treating it as an uninitialized installation.

The configured state-file path must be absolute. A missing state file represents an uninitialized installation; malformed, incomplete, checksum-invalid, inconsistent, or unsupported state raises a recovery error and is never replaced automatically.

Each `SelectionProposal` carries the base state revision supplied to `select_quotation`. The caller must obtain the revision and repetition history from the same recovered state, then pass that revision when producing the proposal. Commit accepts only the currently stored revision, except for an exact retry of that commit when the current revision is exactly one generation newer. Revisions are chronological commit generations; display dates may repeat or move backward after clock adjustments and are not history keys.

The store assumes one writer at a time. Revision checks reject stale proposals and reveal-progress updates but are not a cross-process compare-and-swap; callers must serialize all writes from multiple threads or processes that share a state path. No general locking or transaction framework is provided.

Selection commitment and reveal advancement use the same complete-state publication mechanism. It writes a unique temporary file in the state file's directory, flushes and synchronizes its contents, then publishes it with `os.replace`. On POSIX, the implementation synchronizes parent-directory metadata when it creates the state directory and synchronizes the containing directory after replacement. The temporary and final files therefore share a filesystem, and the rename is the single publication point: a failure before replacement leaves the prior file authoritative; after replacement, the complete new state is authoritative. Temporary files are not recovery candidates.

The file synchronization and atomic replacement use Python's standard filesystem facilities. POSIX directory synchronization strengthens persistence of the replacement across sudden power loss. The standard-library implementation does not synchronize directory metadata on Windows, so power-loss durability of the directory entry is weaker there; filesystem and storage-device guarantees still apply on every platform. If directory synchronization fails after replacement, the commit reports that publication occurred; callers must reload state before deciding whether to retry.

`PersistentStateStore.commit(proposal, snapshot, initial_reveal_stage=0)` initializes each new selection's progress independently of its predecessor. An idempotent selection retry returns the current state, preserving any subsequent progress rather than reapplying the initial stage.

`PersistentStateStore.advance_reveal_progress(expected_revision, stage)` reloads the authoritative state and requires a positive integer revision matching the current committed selection. Missing state and stale revisions raise `StateCommitError` without publishing anything. The stage and initial stage must be nonnegative integers; booleans and other types raise `ValueError`. Stages are ordinal progress values supplied by the caller; storage does not interpret schedules or derive stages from the clock.

Advancement replaces only `PersistentState.highest_reveal_stage`. It preserves the complete snapshot, both histories, and the chronological selection revision. Requests for the current or an earlier stage return the unchanged state without rewriting the file. These no-op requests still synchronize directory metadata on POSIX, so an idempotent retry can confirm durability after an earlier published update. Publication and durability failures use the same `StateCommitError.published` reporting as selection commitment; reload with `load()` to recover the authoritative state before retrying.

### Prepared image files

Persist all images required for the current committed selection.

Prepared files must be associated with the correct snapshot.

Incomplete or invalid image files must not be treated as valid artifacts.

Use a supported image representation that preserves the required output fidelity.

Avoid recompressing, resizing, or converting images unnecessarily during scheduled display updates.

Generated image files should be managed separately from user-authored content.

Do not accumulate unlimited obsolete prepared images during ordinary operation.

#### Revision-scoped artifact representation

`PreparedImageArtifactStore` owns a caller-specified absolute root, separate from the authoritative state file. Its artifact-set identifier is the existing positive committed state revision; the store neither reads global history nor changes persistent state. Callers supply the snapshot and complete ordered image sequence on storage, and the snapshot and expected positive stage count on loading. Stage ordinals are supplied by the caller, not derived from schedules.

The internal layout is:

```text
<artifact-root>/
  revision-1/
    manifest.json
    images-<transaction-suffix>/
      stage-0.png
      stage-1.png
  .tmp-revision-2-<transaction-suffix>/
    ...
```

The suffix is a random filesystem transaction name, not a second snapshot or artifact-set identity. A revision directory has one authoritative manifest pointing to one immutable image directory. This indirection permits atomic replacement of an existing complete set using standard file replacement on both POSIX and Windows, without attempting to replace a nonempty directory. Every stage is an independently readable, complete lossless PNG. Supported modes are `1`, `L`, `LA`, `RGB`, and `RGBA`; dimensions must match the committed snapshot's `layout.image_size`, and every stage must have the same mode. No image conversion or resizing occurs.

The version 1 UTF-8 JSON manifest contains an `artifacts` object and its canonical JSON SHA-256 checksum. Metadata records `format_version`, `revision`, `snapshot_sha256`, the relative `image_directory`, `image_size`, `mode`, and an ordered `stages` array containing exact filenames and PNG-file SHA-256 digests. The snapshot fingerprint covers quotation text and identity, font identifier and exact font-content digest, all presentation metadata, reveal schedule, layout, and complete scheduling context. It excludes reveal progress and selection histories. A revision reused after state replacement therefore does not suffice to establish snapshot association. Checksums detect accidental damage; they do not authenticate files against a malicious writer.

Loading rejects missing metadata, unsupported or inconsistent manifest fields, checksum failures, snapshot mismatches, unexpected stage sequences/counts or extra payload entries, incorrect dimensions/modes, non-PNG or multi-frame images, unreadable files, and PNG verification/decoding failures. Manifest-derived paths must match fixed owned names, not arbitrary paths. Files and directories must be real regular files/directories rather than symbolic links or junctions, including ancestors of the artifact root. Validation checks and closes each decoded stage before proceeding to the next; the returned handle retains only metadata and paths. Individual stage loading revalidates the file rather than trusting earlier validation.

#### Artifact publication and cleanup

Storage writes every PNG and its manifest into a unique root-level `.tmp-revision-<revision>-<suffix>` directory, flushing and synchronizing each file. After synchronizing that directory, it renames the complete directory into the revision directory as `images-<suffix>` and synchronizes the affected directories. The single publication point is `os.replace` of the prepared manifest into `revision-<revision>/manifest.json`. Before that point, the previous manifest and all its images remain untouched. Afterward, the complete new set is visible. The image directory and revision directory are synchronized again after publication.

Directory entries, including the root's ancestor chain, are synchronized in their parents on every storage attempt, so retries also confirm entries left by interrupted directory creation. POSIX directory synchronization strengthens power-loss durability; the standard-library implementation does not synchronize directory metadata on Windows, so its directory-entry durability guarantee is weaker. Filesystem and storage-device guarantees still apply. `ArtifactWriteError.published` reports whether manifest replacement occurred; failure afterward means a complete set was published but durability could not be confirmed, not that the old set remains current. Reload before retrying.

No automatic cleanup is coupled to storage or loading. Interrupted writes can leave root-level temporary directories or unreferenced image directories. Replaced image directories also remain intact, allowing existing handles to retain their original paths until explicitly coordinated cleanup. `cleanup(current_revision)` removes recognized obsolete revision trees, including their abandoned payloads, and recognized root-level temporary transactions. It preserves the entire current revision directory, even if incomplete or invalid; unreferenced payloads within it remain until that revision becomes obsolete.

Cleanup inspects tree contents before removal. It skips unrelated root entries, noncanonical revision/transaction names, trees with unrecognized children, and any symbolic links or junctions, without following them. Removal and directory-synchronization errors raise `ArtifactCleanupError`; they do not invalidate a successfully published current set. Cleanup can partially remove obsolete artifacts before reporting a failure and may be retried. The root is an owned storage directory, not a general-purpose directory for user files.

Callers must serialize artifact operations and coordinate cleanup with every reader still using a returned stage handle or path. The no-follow checks assume no concurrent hostile filesystem mutation; this is not a cross-process locking or adversarial filesystem sandbox. Cleanup never inspects or modifies authoritative state outside the owned root. `recover_prepared_daily_images` orchestrates reuse and full regeneration from the supplied committed state; only absence or `ArtifactValidationError` triggers regeneration. Artifact-root access and publication errors remain visible, and the operation closes generated images without changing persistent state.

## Rendering and image preparation

### Use Pillow for image composition

Pillow is the preferred image-composition library.

The renderer produces standard images independently of physical display hardware.

Display-specific conversion belongs at the boundary between prepared images and the hardware backend when necessary.

Do not allow the renderer to depend directly on Waveshare-specific objects or APIs.

### Font loading and resolution

Use Pillow-compatible font files for text rendering.

Font identifiers, paths, and validation rules are defined in `docs/CONTENT_FORMAT.md`.

Font-selection and fallback behavior are defined in `docs/ARCHITECTURE.md`.

Validate registered font files when loading application configuration.

Validation must establish that each file exists, is readable, and can be loaded by the renderer.

Report unavailable content-entry font preferences during content-library loading rather than repeatedly during daily selection or scheduling.

Use a controlled random source for deterministic testing of automatic font selection.

Resolve the selected font before committing the daily snapshot.

Pass the resolved font to the renderer through the committed presentation configuration.

Do not independently select or substitute fonts during rendering, image regeneration, or scheduled display updates.

Preserve sufficient information to identify and validate the committed font during recovery.

A font registry identifier or filesystem path alone does not guarantee that the underlying font file remains unchanged after configuration updates.

If the committed font is unavailable during recovery, retain valid prepared images and report the problem rather than silently changing the presentation.

Do not distribute third-party font files without verifying their licenses and redistribution terms.

Do not introduce general font discovery, download, or substitution infrastructure without a demonstrated requirement.

### Keep presentation configuration focused

The initial release provides one configurable presentation layout.

Use the normalized presentation region and font-size bounds defined in `docs/CONTENT_FORMAT.md`.

Convert normalized coordinates into pixel geometry using the actual output-image dimensions.

The shared quotation renderer is responsible for arranging and drawing the quotation and its optional source and attribution within that region.

Layout calculation must account for all present fields before generating any reveal-stage image.

Use Pillow's font metrics and text-measurement facilities to determine suitable font sizes, line wrapping, and placement.

Text measurement must account for:

- actual glyph dimensions;
- line spacing;
- preserved line breaks;
- paragraph spacing;
- the complete presentation region;
- space occupied by source and attribution;
- the effective presentation style.

Avoid assumptions based solely on character counts or average character widths.

The fitting implementation must satisfy the presentation behavior defined in `docs/ARCHITECTURE.md`.

Prefer a straightforward deterministic fitting procedure over a general-purpose text-layout framework.

Do not hardcode the initial display resolution into unrelated content, selection, or scheduling logic.

The initial layout need only be validated at the resolution and color capabilities required for Version 0.1.

Do not introduce a general-purpose layout framework or font-selection optimization engine without a demonstrated requirement.

### Stable presentation geometry

Resolve the complete literary composition once, including all present source and attribution fields.

The resulting layout must contain sufficient information to reproduce the same typography and field positions across every reveal stage.

Presentation styles determine layout geometry. Image drawing uses the resolved geometry rather than independently interpreting style identifiers.

Keep style-specific layout behavior isolated so additional built-in styles can be introduced without changing content-selection policy, persistence mechanisms, scheduling, or display integration.

The initial implementation needs only the `centered` and `left-aligned` styles.

A small internal dispatch mechanism for selecting built-in layout behavior is sufficient. Do not introduce a public styling plugin interface or generalized layout framework without a demonstrated requirement.

All reveal stages for one committed selection must use consistent layout geometry.

Reserved space for future reveals must not cause previously visible content to move when additional information becomes visible.

The renderer must not silently clip, truncate, overlap, or omit required text merely to produce an image.

If the complete composition cannot fit within the supported presentation region, report a meaningful error.

### Preparation and validation

Prepare the complete set of required reveal-stage images from the committed daily snapshot.

Resolve the complete composition layout once and reuse it for every required cumulative visibility stage.

Each prepared image must be independently displayable.

Normal reveal transitions select an existing prepared image rather than invoking text fitting, layout calculation, or image rendering.

Do not require intermediate stages to have been physically displayed before preparing or presenting a later stage.

The same rendering facilities must support preparation of a single fully visible image for views that do not require progressive reveals.

Test image dimensions, supported output formats, presentation styles, field visibility, layout stability, and significant fitting constraints without physical display hardware.

Tests must verify that all present quotation, source, and attribution text remains within the configured presentation region without overlap or clipping.

Visual inspection remains appropriate for typography and layout quality.

## Display backend

### Driver integration

Use the Waveshare Python implementation appropriate for the supported display model as the initial hardware integration.

Keep the imported driver surface as small as practical.

Do not include support for unrelated Waveshare display models merely because those implementations are distributed together.

Record the provenance, version or revision, and license of any vendor code incorporated into the repository.

Do not modify vendor driver behavior without understanding the relevant hardware requirements.

When modifications are necessary, keep them reviewable and explain why they are required.

### Hardware isolation

Only the display backend should depend on the Waveshare driver, SPI, or GPIO facilities.

The application must remain testable without physical hardware.

The backend should accept prepared presentation images through a narrow interface.

Do not expose GPIO pins, controller commands, or driver-specific state to the content or scheduling components.

### Hardware lifecycle

The backend owns initialization, full-frame updates, controller sleep or release, and cleanup.

Use supported driver lifecycle operations rather than assuming a controller can resume from sleep without reinitialization.

Validate initialization, repeated updates, sleep behavior, and recovery using the actual display.

A working example program establishes basic compatibility but does not prove reliable long-term unattended operation.

### Refresh policy

Avoid unnecessary physical refreshes.

A successful prepared-image update should not be repeated merely because the scheduler reevaluates its state.

When the desired stage advances during an active update, the application should ultimately present the latest required stage rather than replaying obsolete intermediate stages.

Avoid overlapping display operations.

### Display failures

Classify hardware failures sufficiently to support meaningful diagnostics and bounded recovery.

Use bounded retry behavior rather than unrestricted rapid retry loops.

Retries must not indefinitely block recognition of newer scheduled presentation requirements.

Preserve the retained e-paper image when possible.

Do not report successful hardware presentation when the result is unknown.

Hardware validation must distinguish between driver-call success and visibly correct panel output.

## Scheduling and timekeeping

### Scheduling

Use timezone-aware date and time operations.

Use the configured IANA timezone for display-day and reveal calculations.

Avoid assumptions that a local day always contains 24 elapsed hours.

Do not use fixed-duration sleeps as a substitute for correct calendar-boundary calculations.

The scheduler should ordinarily wait until the next meaningful event rather than polling continuously.

### Wall-clock changes

Implement the documented forward- and backward-clock behavior without allowing previous reveal stages to become hidden.

Tests must cover clock changes without requiring the host operating-system clock to be modified.

Separate the current time source from scheduling policy sufficiently to permit controlled test inputs.

Use monotonic elapsed time for retry intervals and other durations that should not be affected by wall-clock adjustments.

### Recovery after interruption

Persist the scheduling context required by the architecture.

Do not treat a difference between the stored selection date and the current date as sufficient proof that the committed selection must be replaced.

Test boundary recognition across restarts, missed day starts, clock corrections, and large forward jumps.

When available information cannot reliably distinguish a clock discontinuity, use the architecture's conservative recovery policy rather than inventing unobservable clock history.

## Logging and diagnostics

### Logging

Use Python's standard `logging` facilities.

Emit application logs to standard output and standard error as appropriate for supervised execution.

Do not require a separate log server, database, or third-party logging framework.

Allow systemd and journald to manage ordinary deployed logs.

Avoid implementing application-specific log rotation or persistent log files without a demonstrated need.

### Log content

Log meaningful lifecycle and state changes, including:

- application startup and shutdown;
- configuration and content validation failures;
- daily selection commitments;
- recovery of committed selections;
- image-preparation failures;
- physical display failures and recovery;
- significant scheduling or clock-related events.

Do not log every scheduler iteration or repeatedly emit identical errors during unchanged retry conditions.

Log messages must be concise, human-readable, and useful for diagnosing unattended operation.

Do not unnecessarily log entire quotation libraries or large serialized snapshots.

### Diagnostic behavior

Errors should provide enough information to identify the failing responsibility and next useful troubleshooting step.

Diagnostic facilities must not mutate persistent state or operate the physical display unless explicitly intended to do so.

## Testing and validation

### Automated tests

Use pytest for hardware-independent automated tests.

Tests should verify observable behavior and documented contracts rather than relying unnecessarily on private implementation details.

Every substantive behavior change should include focused regression coverage where practical.

The ability to import and test core components without Raspberry Pi hardware is a project requirement.

### Core test coverage

Automated testing should cover:

- content and configuration validation;
- stable entry and quotation identities;
- normalized quotation matching;
- date-specificity precedence;
- priority selection;
- equal-probability random selection behavior where practical;
- global and repetition-history behavior;
- pool exhaustion and selective reset;
- atomic selection commitment;
- recovery from interrupted writes;
- committed snapshot recovery;
- preparation and recovery of reveal-stage images;
- cumulative reveal progression;
- forward and backward clock adjustments;
- display-day boundaries and restart behavior.

Randomized selection tests should use controlled random sources where deterministic outcomes are needed.

Do not rely on statistical luck to make unit tests pass.

### Filesystem and failure testing

Use temporary directories and isolated test state.

Test persistence failure at meaningful boundaries, including failures before and after commitment.

Verify that incomplete data cannot be mistaken for successfully committed state.

Where practical, test recovery using a newly initialized application instance rather than only inspecting the state of the instance that performed the write.

### Rendering tests

Verify rendered-image dimensions, stage completeness, and stable layout geometry.

Use representative quotations of different lengths and combinations of optional metadata.

Test automatic text fitting with:

- short quotations;
- long quotations requiring multiple wrapped lines;
- explicit line breaks and paragraphs;
- quotations that fit at the maximum permitted font size;
- quotations requiring a smaller permitted font size;
- quotations that cannot fit at the minimum permitted size.

Verify that all rendered literary content stays within the configured presentation region.

Verify that the selected font, font size, wrapping, and quotation placement remain consistent across all reveal stages.

Test font configuration and selection behavior, including:

- valid registered fonts;
- invalid or unreadable registered fonts;
- empty default font pools;
- default identifiers missing from the registry;
- explicit content-entry font preferences;
- unregistered content-entry fonts and their warnings;
- randomized selection from the default pool;
- persistence of the resolved font in committed state and global history;
- recovery without independently reselecting a font.

Use deterministic random sources where required.

Automated image comparisons may be used where they provide stable, meaningful regression coverage.

Do not rely exclusively on exact pixel comparisons for behavior that is better validated through semantic or geometric assertions.

Visual inspection remains appropriate for typography and layout quality.

### Hardware validation

Validate hardware-dependent behavior on the supported display.

Hardware validation should include:

- driver initialization;
- complete image transfer and refresh;
- repeated scheduled updates;
- controller sleep and subsequent use;
- application restart;
- failure and recovery behavior where practical;
- correct presentation of representative prepared images.

Report the exact tested hardware, operating-system environment, and relevant limitations.

A hardware-independent test or mocked driver does not constitute physical display validation.

Do not claim a Raspberry Pi model is supported solely because it uses a compatible GPIO interface.

### Resource validation

Measure memory use, processing time, and storage requirements on representative hardware when those characteristics materially affect supported deployment targets.

In particular, validate the Raspberry Pi Zero 2 W before declaring it supported.

Do not introduce caching, concurrency, or performance optimization without evidence that it improves an observed limitation.

### Normal validation

The repository should provide consistent commands for:

- formatting verification;
- linting;
- automated tests;
- package or source installation verification where applicable.

The exact commands must be documented alongside the configured development tools.

A change is not considered validated merely because its Python files import successfully.

Record validation limitations honestly.

## Deployment and service operation

### Installation approach

Version 0.1 may be installed directly from source.

A package repository, installer framework, or container runtime is not required.

Deployment instructions must identify the supported operating system, system dependencies, Python environment, configuration locations, and persistent-state requirements.

Installation must not depend on the developer's local directory structure.

### Service management

Use systemd for unattended deployment on Raspberry Pi OS.

The service should start automatically when enabled and recover from unexpected application termination according to a bounded restart policy.

Avoid duplicating systemd supervision in application code.

Graceful termination must allow the display backend to release resources safely.

### Permissions

Run Refrain with the minimum practical operating-system privileges.

Do not run the entire application as root merely because one hardware interface requires privileged access.

Document required SPI and GPIO permissions for the supported deployment.

Persistent state and generated images must be writable by the service identity.

User-authored content and configuration should not require write access from the running application unless a defined feature requires it.

### Filesystem locations

Keep user-authored content separate from application code and generated state.

Persistent snapshots, histories, and prepared images must survive application restarts and ordinary software updates.

Avoid writing runtime state into the installed Python package directory.

Define and document deployment paths rather than assuming a particular home directory or username.

### Runtime updates

Application updates must not silently discard committed selections or histories.

Changes to persistent-state or content schemas require compatibility review.

The initial release does not require automatic updates or remote deployment management.

## Versioning and compatibility

Use semantic versioning for project releases.

Version 0.1 establishes the initial usable release.

During pre-1.0 development, compatibility-breaking changes may be necessary, but they must be deliberate and documented.

Treat published content and configuration formats as user-facing interfaces.

Avoid unnecessary changes that invalidate existing YAML libraries.

Persisted-state changes must be evaluated for their effect on recovery across software updates.

Do not promise compatibility with unimplemented future hardware, web interfaces, or integrations.

## Contributions and reviews

### Scope

Keep implementation changes focused on the assigned issue.

Do not include unrelated refactoring, speculative features, or broad formatting changes.

A pull request should ordinarily address one independently reviewable concern.

### Pull-request expectations

A pull request should describe:

- what changed;
- why the change was needed;
- the related GitHub issue;
- validation performed;
- validation that could not be performed;
- known limitations or assumptions.

Use an explicit closing reference when the pull request is intended to resolve an issue.

### Review standards

Review changes for:

- correctness against the issue and architecture;
- separation of responsibilities;
- persistent-state consistency;
- recovery behavior;
- resource use and lifecycle ownership;
- dependency necessity;
- maintainability and readability;
- regression coverage;
- documentation consistency;
- hardware validation where relevant.

Review feedback should be recorded in GitHub so both human and automated contributors can work from the same history.

### AI-assisted implementation

AI implementation agents are contributors, not architectural authorities.

Agents must read `AGENTS.md` and the relevant authoritative project documents.

An agent must not silently change architecture, expand scope, or implement later roadmap items.

When an issue cannot be completed correctly within the documented architecture, the agent must report the conflict rather than redesigning the project independently.

Use draft pull requests for AI-assisted implementations.

Resolve substantive review feedback and required validation before merging.

The detailed agent launch, review, and revision workflow belongs in `docs/AI_WORKFLOW.md`.

## Engineering non-goals

Engineering practices should not introduce:

- a mandatory container runtime;
- a database server;
- additional application daemons;
- a general plugin framework;
- an elaborate dependency-injection system;
- a custom hardware abstraction framework;
- runtime web services for Version 0.1;
- unnecessary asynchronous processing frameworks;
- automated release infrastructure before the project has a demonstrated release need.

Add these mechanisms only when concrete requirements justify their cost.

The goal is a small, maintainable application that behaves correctly and predictably on supported hardware.