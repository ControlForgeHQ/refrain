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
- display output;
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
- authoritative operational state, including the current daily selection, selection revision, active repetition history, and reveal progress;
- independently retained global selection history;
- prepared presentation artifacts;
- backend-owned presentation state.

Components must not modify state owned by unrelated responsibilities merely because a reference to that state is available.

Prefer immutable values for validated content, committed selections, and resolved presentation configuration where practical.

### Design for unattended recovery

Recoverable failures should not require manual intervention.

Failure handling must respect the boundaries established by the architecture.

In particular:

- selection failure must not create an incomplete committed selection;
- rendering failure must not trigger reselection;
- display failure must not alter quotation history;
- restart must not discard valid current-format selection state;
- recovery must not hide previously reached reveal stages.

Do not add an elaborate recovery framework when a simple, bounded retry or restart-safe operation is sufficient.

### Respect resource-constrained hardware

The Raspberry Pi 3B+ is the minimum supported Raspberry Pi platform for Version 0.1.

Favor implementations that can operate within modest memory, CPU, and storage budgets.

Avoid unnecessary resident data, polling, heavyweight dependencies, and background processing.

Do not retain all decoded reveal-stage images in memory merely because they were generated together.

Use measurements from representative hardware to justify performance-related changes.

Correctness and maintainability take precedence over speculative micro-optimization.

### Prefer existing platform facilities

Use platform-standard per-user application-data facilities as the defaults for configuration, operational state, global history, and derived artifacts. Resolve standard locations at the command-line boundary without adding a dependency solely for path selection. Optional runtime storage overrides belong to application configuration; keep lower-level application and persistence interfaces explicit about the effective paths they receive.

On Linux, honor absolute XDG configuration, state, and cache bases and use the per-user fallbacks when those variables are missing, empty, or relative. On Windows, use the configured roaming and local application-data directories. Other supported desktop platforms should use their established per-user locations.

Use ordinary operating-system facilities where they satisfy the requirement. In particular:

- use systemd for supervised service operation;
- use standard process streams for application logging;
- use the local filesystem for ordinary application storage;
- use the operating system's local-time facilities for local scheduling.

Avoid creating a custom service manager, log daemon, database service, or scheduler without a demonstrated need.

## Documentation model

Each project document has one authoritative responsibility.

### README.md

The root `README.md` is a concise, user-facing introduction to Refrain.

It describes the project's purpose, general direction, development status, and where interested users can follow progress.

It is not an installation guide, configuration reference, technical manual, feature inventory, or implementation history.

Routine development work must not trigger updates to the root README. It is changed only when the project maintainer explicitly requests a README change.

Technical information belongs in its authoritative project document. Implementation details and validation outcomes belong in the relevant issues and pull requests.

### docs/ROADMAP.md

The roadmap owns release goals, planned capabilities, sequencing, and future product scope.

It must not prescribe implementation details.

### docs/ARCHITECTURE.md

The architecture owns runtime responsibilities, behavior, lifecycle, state semantics, scheduling rules, and architectural invariants.

It answers:

> Where does this behavior belong, and how must the system behave?

### docs/CLI.md

The CLI reference owns public command syntax, argument behavior, command-mode conflicts, exit and result semantics, and user-facing command diagnostics.

The architecture owns the runtime semantics behind those commands. Engineering owns CLI implementation and testing guidance.

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

Routine development work must not trigger updates to the root README; update the authoritative technical document instead.

## Python development

### Language and runtime

Refrain is implemented in Python 3.

Use a Python version supported by the targeted Raspberry Pi OS release.

Do not require a separately installed interpreter when the operating system's supported Python version meets the project's needs.

Avoid language features or third-party packages that unnecessarily exclude supported deployment platforms.

The project's minimum supported Python version must be established in the project metadata once implementation begins.

### Cross-platform development and testing

Refrain's hardware-independent components must remain compatible with Linux and Windows development environments. Prefer platform-neutral Python interfaces and avoid unnecessary operating-system-specific assumptions.

The repository's GitHub Actions CI workflow provides the standard automated validation for pull requests and changes to the default branch. It must run:

- Ruff lint checks and Black formatting checks;
- the complete hardware-independent pytest suite on Linux;
- the same pytest suite on Windows.

For pull requests whose diff is limited to Markdown under `docs/`, the root `README.md`, or the root `AGENTS.md`, CI still runs lint and both required test jobs. The test jobs report the documentation-only result and skip Python setup, dependency installation, and pytest. Any other changed path or an inconclusive comparison requires the full test suite on both platforms. Pushes to the default branch and manual runs always run the full suite.

Use the project's supported Python version and declared development dependencies. CI must not require Raspberry Pi hardware, GPIO or SPI libraries, or other hardware-specific dependencies to run the hardware-independent tests.

Tests must not assume a particular filesystem path separator, directory layout, user privilege level, or operating-system-specific error message. Compare paths using native `pathlib.Path` values where practical. Assertions involving diagnostic output must remain portable without weakening the behavior they verify.

Tests requiring capabilities that are not universally available, such as symbolic-link creation on Windows, must detect unavailable capabilities and skip only the affected tests with an explanatory reason. Genuine behavioral, security, or validation failures must not be suppressed.

Platform-specific tests may be conditional when their subject is inherently platform-specific. Hardware-independent functionality must not be excluded from a platform's test suite merely to obtain passing results.

All required CI checks must pass before a pull request is considered fully validated. A failure on either platform requires investigation and correction. A passing result on one platform does not establish compatibility with the other.

When required CI checks cannot run or complete, record the limitation explicitly. Pending, skipped, cancelled, or unavailable checks must not be represented as passing validation.

Local automated testing remains useful for development and investigation, but contributors are not required to duplicate successful CI checks manually unless additional validation is necessary.

Passing hardware-independent CI checks does not establish correct operation on Raspberry Pi hardware or a physical e-paper display. Hardware-dependent changes require separate validation appropriate to the affected functionality.

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

Do not deserialize arbitrary Python objects from application configuration or content files.

Application configuration and content files have separate validation and recovery policies defined in `docs/CONTENT_FORMAT.md`.

A syntax error in application configuration prevents that document from being interpreted; the application must report an actionable error rather than guess at its contents.

A syntax error in an individual content file excludes that file without invalidating unrelated content files.

Where the supported content format permits independent entry validation, reject individual invalid entries without discarding unrelated valid entries.

Content source discovery must distinguish a complete examination containing rejected entries from missing directories, inaccessible sources, or failed enumeration.

Duplicate entry identifiers must be handled independently of filesystem enumeration order.

Do not depend on YAML mapping order or filesystem enumeration order for selection policy.

Do not implement speculative YAML syntax repair or unsupported multi-entry formats.

### Configuration

Configuration must be explicit, documented, and validated.

Both application configuration and content entries use YAML, with separate schemas defined in `docs/CONTENT_FORMAT.md`.

Construct an effective application configuration from accepted values, documented defaults, and usable registered resources.

Distinguish fatal validation errors from recoverable warnings and informational default notices.

Apply only defaults established by the public configuration specification. Do not invent fallback values to bypass missing required settings.

Unknown application-configuration fields and invalid optional values must be reported and handled according to the configuration contract without unnecessarily preventing operation.

When optional values are omitted, informational default notices should be consolidated where practical rather than generating excessive startup output.

Discover bundled and user-owned assets when loading effective configuration, using package-resource APIs for bundled resources and category directories relative to the effective configuration for user assets. Do not monitor, modify, or generate files in user asset directories. Safely validate each manifest and resource independently; confine manifest references to their package and do not follow symlinks during discovery.

Construct registries from valid discovered identifiers, but construct default pools only from explicitly configured identifiers. Never add discovered assets to a default pool automatically. Custom resources cannot shadow bundled identifiers, and all custom resources in a same-category collision are excluded deterministically.

An unavailable font preference in an otherwise valid content entry does not invalidate that entry. Report it and proceed to the next font preference, using the effective default pool only when automatic selection is required. An empty effective pool must not invalidate an otherwise usable explicit content-entry or decoration preference.

Validate discovered backgrounds individually against the PNG requirements in `docs/CONTENT_FORMAT.md`. Preserve valid resources when another asset fails. Build the effective default background pool without adding unrequested resources. Report unavailable content-entry background preferences without rejecting otherwise valid entries.

Validate content independently by source file and, where supported, by entry. Preserve accepted entries when other entries fail validation.

A nonempty effective content library may be used for new selections even when individual sources were rejected.

Do not treat missing or inaccessible sources, unsuccessful discovery, or an empty effective content library as successful content removal for repetition-history cleanup.

Preserve the selected content's presentation preferences in the daily selection record when needed to interpret or present the quotation. Those captured preferences are authoritative for the committed selection: do not reread the original content entry after commitment, and do not let later edits to it change the captured values.

The semantic committed selection and its captured preferences do not change when source content or configuration files are edited. If a valid prepared cache cannot be reused, resolve the captured preferences against current application configuration and available assets during regeneration. Derived visual resources and rendering decisions are not frozen at commitment, so regenerated appearance may differ.

Do not rewrite user-authored configuration or content files as part of validation.

### File paths

Use `pathlib` for filesystem path handling.

Do not assume that application files, content files, persistent state, and generated images are located in the same directory.

Keep configuration and user content separate from operational state, global history, and derived artifacts. Custom fonts, backgrounds, and decorations are user-owned resources under `assets/{fonts,backgrounds,decorations}/` beside the effective configuration file; they are separate from bundled package resources and generated artifacts. Manifest references are relative to their package and must not escape it. Content-directory paths retain their configuration-relative or explicit-absolute semantics. Configuration resolves explicit relative storage paths against its own file; the command-line entry point combines these optional values independently with platform-standard defaults. Application functions continue to receive effective paths rather than performing implicit home-directory lookup.

Avoid assumptions tied to a particular username, home directory, mount point, or installation path.

Resolve relative paths consistently and document their interpretation.


## Persistent storage

### Storage approach

Use ordinary local filesystem storage for Refrain's initial persistent data.

A database service is not required.

The storage representation should remain simple, inspectable, and suitable for recovery after unexpected termination.

Authoritative operational state, global selection history, and prepared images have separate storage responsibilities.

Operational state must not depend on reading global-history records or prepared-image files to determine the current selection revision.

The architectural commitment and recovery requirements determine the storage design.

### Atomic selection commitment

A daily selection becomes authoritative when the selected content record, updated repetition history, next selection revision, initial reveal progress, and required scheduling context have been committed consistently.

These operational-state values have one logical commit point.

Global-history recording is independent of that commit and must not be included in its transaction.

Construct a complete next operational state and publish it using atomic filesystem replacement.

Temporary and final state files must reside on a filesystem supporting the required replacement semantics.

Flush file contents before replacement and synchronize relevant directory metadata where supported.

A failure before publication leaves the previous operational state authoritative. A failure after publication may require reloading state to establish whether the new selection was committed.

Do not require a global-history append to succeed before recognizing a committed selection.

### Recovery and prerelease state

Persistent operational state must be validated when loaded. Incomplete, invalid, or integrity-check-failing state must not be silently accepted. An interrupted state publication must not produce a partially committed selection or inconsistent repetition history. A failure after selection commitment must preserve the committed quotation. Global-history failures must not prevent operational recovery, and global history must not be used to reconstruct repetition state or determine the next revision.

Only the current prerelease operational-state schema is supported. Do not add schema migrations, legacy readers, normalization paths, rendering branches, or tests for earlier internal state formats. A numeric discriminator is unnecessary unless required by the implementation; if one is retained, the sole current prerelease value is `1`. Incompatible or invalid state must produce an actionable diagnostic reflecting the effective state-file location, without silently replacing selected content or modifying the file. For the platform-standard per-user state path, the diagnostic may direct the operator to stop Refrain and run `refrain --reset`. For a state path configured outside that standard location, it must identify the path and direct the operator to stop Refrain, back up the file, and manually quarantine or remove only that file; `--reset` does not manage custom paths.

The current state need only preserve the selected entry and quotation identities, original quotation text, optional source and attribution, content properties needed to interpret or present the selected quotation, effective reveal schedule, display-day and scheduling context, selection revision, repetition history, and highest reached reveal stage. Do not persist derived rendering geometry, selected fonts or face identifiers, resolved colors, selected image resources, tinting decisions, QR placement, or layer transformation plans solely to reproduce pixels.

Recovery behavior must be covered by automated tests using controlled failures at meaningful publication boundaries. Valid current-format state must remain recoverable across restarts.

Global selection history is not included in the operational-state document. The configured state-file path must be absolute. A missing state file represents an uninitialized installation.

### Selection revisions and commitment

Each `SelectionProposal` carries the base state revision supplied to `select_quotation`.

The caller obtains the base revision and repetition history from the same recovered operational state.

A successful new selection uses `current_revision + 1`. The initial selection uses revision 1.

Revisions are assigned from operational state, never from the number or contents of global-history records.

Display dates may repeat or move backward after clock adjustments and are not revision keys.

Commit accepts a proposal only when its base revision matches the current operational revision, except for an exact idempotent retry of an already published selection.

An idempotent retry preserves any subsequent reveal progression and does not commit another selection.

The store assumes one writer at a time. Revision checks reject stale proposals and reveal-progress updates but are not a cross-process compare-and-swap. Callers must serialize concurrent writes sharing the same state path.

No general state-store locking or transaction framework is required; resident process exclusivity is specified separately under [runtime ownership](#resident-process-ownership-and-runtime-control).

### Repetition-history cleanup

Before selecting a quotation, successfully discover and examine the content sources and construct a nonempty effective content library from accepted entries.

Derive the set of normalized quotation identities belonging to every accepted entry in the effective library.

Intersect the persisted repetition history with those identities.

Use the resulting collection for repetition-aware selection.

The cleanup must consider every accepted quotation, regardless of current eligibility, specificity, priority, or font availability.

Rejected files and entries do not contribute identities to the effective library. Their previously recorded repetition identities may therefore be removed.

Do not prune repetition history when the content directory is missing or inaccessible, source discovery or enumeration fails, or the effective library contains no valid quotations.

Individual invalid content files or entries do not prevent cleanup when the remaining effective library is usable.

Persist the cleaned repetition history only as part of the next successful selection commitment.

A separate startup write, maintenance service, or periodic pruning task is not required.

### Operational-state publication

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

### Global-history storage

Global selection history is maintained separately from authoritative operational state.

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

The application must not read global history to determine current selection state, repetition eligibility, scheduling, or the next revision.

Global-history recording occurs only for committed selection events, not reveal updates or display refreshes.

### Global-history retention and rotation

Global-history retention is bounded and does not have operator-configurable limits in Version 0.1. Use size-based rotation with the following fixed limits:

The maximum segment size is 1 MiB (1,048,576 bytes).

The total retention allowance is 20 MiB, represented by one active segment and up to 19 rotated segments.

The active segment contains the newest records. Rotated segments retain older records in chronological order, with the oldest retained segment removed when necessary to maintain the fixed retention allowance.

Rotation occurs between complete records, never within a JSONL record.

Before appending a record that would exceed the 1 MiB active-segment limit, rotate the active segment.

A single record exceeding the segment limit cannot be recorded and must produce a diagnostic without affecting the committed selection.

Rotation must not modify authoritative operational state or reset selection revisions.

### Global-history failure handling

Global-history recording is best-effort.

Failure to open, append, flush, rotate, or retain a history segment must produce a diagnostic but must not invalidate a committed selection or prevent ordinary display operation.

An interrupted append may leave an incomplete trailing record. History-reading tools must distinguish such records from complete valid events without affecting application recovery.

The history format does not promise transactional consistency with operational state.

A missing historical record after an interruption is acceptable.

Normal operation should avoid recording the same committed selection repeatedly during ordinary retries or restarts, but no cross-file exactly-once transaction is required.

Global-history storage assumes one writer at a time. Concurrent writers sharing the same history directory require external coordination.

History rotation and retention apply only to global-history files. They do not delete the current prepared images or any future calendar presentation archive.

### Prepared image files

Persist all images required for the current committed selection.

Prepared files must be associated with the current selection revision and expected reveal stages.

Incomplete or invalid image files must not be treated as valid artifacts.

Use a supported image representation that preserves the required output fidelity.

Avoid recompressing, resizing, or converting images unnecessarily during scheduled display updates.

Generated image files should be managed separately from user-authored content.

Do not accumulate unlimited obsolete prepared images during ordinary operation.

#### Complete-set cache

The prepared-image cache is derived output, not authoritative state. Associate the complete required variant collection with the committed selection revision, expected output specifications, and ordered reveal stages; do not fingerprint every visual choice or serialize a rendering plan. Every required stage for every output specification must be present. Each stage is a complete, independently displayable lossless PNG. Files for one output specification must have its exact expected dimensions and a compatible image mode; dimensions may differ between specifications. Validate collection completeness and file integrity, detecting missing, damaged, truncated, or inconsistent files.

During ordinary operation, reuse a complete valid set without checking whether configuration, fonts, palette, or image assets have changed. If the set is absent, incomplete, damaged, or otherwise unusable, resolve current configuration and resources and prepare the complete required variant collection together. Publish the replacement safely only after the complete new collection is ready. A replacement may look different from the prior set.

### Prerelease implementation simplification

Follow-up implementation work must inspect the existing code and remove responsibilities that only support exact-rendering recovery or obsolete unreleased schemas. This includes rendering-plan fields and snapshot validation, snapshot construction devoted to resolved presentation metadata, artifact identities and fingerprints over visual decisions, cache invalidation when settings or assets change, regeneration rules that preserve old font/palette/QR/resource choices, special-case compatibility handling for obsolete prerelease configuration fields, legacy state and single-image manifest readers, and tests for historical-schema recovery or pixel-identical regeneration.

Retain only the machinery needed to atomically commit selected content and scheduling state, protect repetition identity and monotonic reveal progress, associate complete image sets with the right selection and stages, detect damaged cache files, safely replace a complete set, reuse it during ordinary operation, and regenerate all stages after cache failure. Do not introduce replacement abstractions unless implementation evidence demonstrates they are necessary.

#### Artifact publication and cleanup

Storage writes every PNG and its small association/integrity manifest into a unique temporary directory, flushing and synchronizing each file. Publish the complete prepared set atomically so an interrupted write leaves the previous complete set or no usable cache, never a partial set presented as valid.

Use atomic file replacement and appropriate synchronization where supported. Cache durability need only protect safe reuse and replacement; loss of a cache is recoverable from current operational state.

Remove obsolete cache files without disturbing active readers or the complete set being published. Keep cleanup simple and bounded; artifact retention must not become a second source of application state.

The cache store must not modify authoritative selection state. Cache errors are reported and handled by regeneration from the valid daily selection; they must never authorize reselection or reveal regression.

## Resident process ownership and runtime control

### Exclusive ownership

Use a small cross-platform ownership abstraction built on standard-library access to operating-system exclusive locks. Normal runtime and `--demo` acquire the per-user Refrain ownership lock non-blockingly before loading operational state or constructing display backends, and retain it for the complete backend-owning process lifetime. Release it during orderly shutdown; rely on the operating system to release it when a process exits abnormally. A persistent lock-file path may identify the lock, but file existence or a stored PID must never determine ownership or be used as stale-lock recovery.

`--initialize`, `--reset`, `--purge`, and any other command that creates or mutates the standard installation acquire the same lock non-blockingly for the duration of their operation. Keep the lock metadata outside trees reset or purge can remove. A busy lock produces an actionable diagnostic and no operation proceeds. A second normal or demo process likewise fails before it opens configured backends. One-shot control clients, including `refrain --refresh`, do not acquire this ownership lock.

Keep platform-specific locking details behind the small abstraction, using standard-library and operating-system facilities rather than a lock server or process-management dependency. Locking must work across processes, not merely threads. Ownership metadata and lock behavior must be scoped to the current user's standard Refrain installation even when runtime configuration selects custom state paths.

### Local runtime-control IPC

Use Python standard-library local IPC behind one application-facing client/listener abstraction: Unix-domain local IPC on Linux and Windows named-pipe IPC on Windows. `multiprocessing.connection.Listener` and `Client` may supply these transports. Do not use TCP to unify the implementation or expose a control listener on a LAN address. The `image-server` HTTP backend remains separate and is not the control transport.

Authenticate each connection with a per-runtime unpredictable credential available only through appropriately protected per-user runtime metadata. Do not treat a local socket or pipe alone as authorization. `--demo` is a standalone backend-owning mode and does not provide the runtime-control listener.

Restrict runtime metadata and credential files to the owning user using platform-appropriate permissions. Remove endpoint and credential artifacts during orderly shutdown. After abnormal exit, tolerate stale filesystem artifacts: their existence does not establish that a runtime is alive. Acquire the process ownership lock before reconciling or replacing stale endpoint metadata, and use a successful authenticated IPC connection—not the presence of a path or credential file—to establish that a control endpoint is responsive.

Use a bounded, explicitly versioned protocol over byte-oriented operations such as `send_bytes()` and `recv_bytes()`. JSON may carry operation metadata and output specifications. Transfer completed images as separately bounded binary payloads rather than embedding them in JSON. Do not use pickle-based `send()` or `recv()` for control payloads. Apply explicit limits to message size, image dimensions, image count, and selected destinations. Reject unknown versions or operations, malformed metadata, unsupported encodings, oversized or inconsistent payloads, and incomplete requests before they can trigger backend access.

### Publication coordination

Extend the existing application-owned publication coordinator. Transient and scheduled publication must use the same configured backend instances, per-instance serialization, lifecycle ownership, and safe shutdown behavior; do not create a second path that independently constructs or opens hardware.

Keep the normal desired scheduled presentation distinct from transient request state. Reserve all selected destinations atomically only after validating the complete request and confirming immediate safe admission. Reject a busy request in full rather than partially publishing or queuing it. Preserve scheduler responsiveness while receiving image data and waiting for publication; ordinary threads may perform control handling where needed, but no asynchronous framework or external daemon is required.

Separate request admission from client connection lifetime. Rejection before admission means no requested publication began. After admission, the resident runtime owns the operation: socket or pipe closure is not cancellation, and admitted work continues under ordinary backend safety and serialization rules. If the client is gone, safely discard or fail delivery of the terminal response without starting another publication attempt. A lost terminal acknowledgement leaves the client's outcome unconfirmed; do not imply rollback, exactly-once delivery, or automatically replay the request. No durable transaction journal or replay protocol is required.

Bound retained image memory and reuse one complete image variant for destinations with identical output specifications wherever ownership and lifetime allow. Avoid unnecessary copies while ensuring each image remains valid until every backend operation using it has completed. An admitted transient operation must not cause an active backend call to be interrupted or concurrently closed.

### Runtime-control validation

Add hardware-independent tests using fake backends and controlled synchronization. Cover:

- exclusive normal and demo ownership, rejection of a second process and concurrent demo, release on shutdown, installation-management exclusion, and control-client behavior with no resident runtime;
- authenticated local connections, malformed, unsupported, oversized, and inconsistent protocol requests, and rejection before backend access;
- discovery of canonical destination IDs and output specifications, including single-output and named multi-output backends, and rejection when a destination or specification changes after discovery;
- exact output-dimension validation, missing image variants, and shared image use for destinations with identical specifications;
- atomic busy rejection for one destination and for `all`, no partial publication after failed admission, independent operation on different backend instances, and serialization on the same instance;
- per-destination scheduled acknowledgement and coalescing, including distinct acknowledgements for named destinations with identical output specifications;
- scheduled desired state remaining authoritative after an admitted transient push, transient completion remaining separate from scheduled acknowledgement, no replacement of admitted transient work by later scheduling, and no repaint on routine reevaluation of an unchanged scheduled identity;
- no push mutation of selection, revision, global or repetition history, reveal progression, scheduling state, or prepared artifacts;
- refresh republication of the currently scheduled presentation to every configured destination, including destinations without transient-publication capability and the current reveal stage rather than pre-push pixels, plus synchronous push/refresh completion and visible CLI progress;
- client disconnection before and after admission, continued ownership of admitted work, safe loss of terminal-response delivery, unconfirmed outcomes, and no automatic publication replay;
- generic viewer routing without backend-type conditionals.

These tests establish software behavior only. Actual Waveshare validation must confirm that a preview is published by the already-running Refrain process, does not overlap another physical refresh, remains displayed after push completion, is replaced by `refrain --refresh`, and leaves the controller and normal runtime usable afterward.

## Rendering and image preparation

### Use Pillow for image composition

Pillow is the preferred image-composition library.

The renderer produces standard images independently of physical display hardware.

Display-specific conversion belongs at the boundary between prepared images and the hardware backend when necessary.

Do not allow the renderer to depend directly on Waveshare-specific objects or APIs.

### Output geometry and diagnostics

Use Pillow for raster composition and resampling. Follow the three image-space responsibilities and pipeline in `docs/ARCHITECTURE.md`; do not introduce a competing rendering sequence. Validate each resolved output specification and dimensions before allocating images. Keep the design canvas, presentation canvas, and requested output-image dimensions distinct. Resolve design-space geometry and scale it to presentation-canvas coordinates with the architecture's deterministic rounding rules. Render literary content, QR, and diagnostics on the presentation canvas; only the completed image may then be resized once as a whole to the requested output dimensions.

Nine-slice values are source-image pixel distances: partition the original source directly with those values and preserve the same numerical edge and corner thicknesses on the design canvas. Do not map source coordinates through the reference envelope. For example, a 1920 × 1200 source with `20 / 20 / 20 / 20` slices used on a 3840 × 2400 design canvas retains 20-pixel thicknesses, not 40-pixel thicknesses.

Avoid unnecessary upscaling of source raster resources and unnecessary full-canvas copies. Manage Pillow image and font resources explicitly, closing decoded or temporary images when their owners are finished with them. Diagnostic tools must follow their documented output-specification behavior and must not mutate committed presentation state or generated daily artifacts.

### Shared presentation and viewer

Runtime and `refrain-viewer` must call the same presentation-construction, preference-resolution, geometry, QR, and image-preparation operations. Keep precedence and fallback rules authoritative in shared presentation machinery; represent optional viewer choices with a typed override model and apply them there, not in a second viewer-side resolver. Viewer font-size bounds must use the shared configured-bound resolution, design-to-presentation scaling, and fitting path. Normal runtime preparation supplies no viewer overrides.

For local inspection and export, the viewer selects a validated content entry and one 1-based quotation directly, without eligibility, priority, repetition, scheduling, or selection commitment. Its built-in `@preview` fixture belongs only to the viewer. It resolves one viewer-owned output specification, uses the same design/presentation/output pipeline, and writes or displays the final output image without using configured display backends. In push mode, it instead renders against runtime-discovered destination specifications and may produce multiple unique output variants.

Keep the viewer independent of operational state, global history, and prepared-artifact storage, including configuration-relative paths. Window presentation is viewer-owned, display-only UI: it may scale a copy for desktop fit but must not alter the rendered output image. In every mode, the viewer must never construct, initialize, or directly access configured backend instances; in push mode it only asks the resident runtime to publish the completed images.

### Font loading and resolution

Use Pillow-compatible font files for text rendering.

Font identifiers, paths, and validation rules are defined in `docs/CONTENT_FORMAT.md`.

Font-selection and fallback behavior are defined in `docs/ARCHITECTURE.md`.

Validate all manifest-declared font faces when loading application configuration; each discovered bundle must provide a usable regular face. Validate the optional role-preference mapping independently from the registered `faces` resources. Invalid optional preference metadata is warned about and ignored without invalidating an otherwise usable bundle or decoration.

Validation must establish that each registered file exists, is readable, and can be loaded by the renderer.

Validate the syntax of content-entry face preferences during content-library loading. Report a valid but unavailable winning face when the selected bundle and preferences are resolved for a complete image preparation.

Use a controlled random source for deterministic testing of automatic font selection.

Select one font bundle during image preparation using content-entry, decoration, and default-pool precedence, then resolve each literary role within that bundle using entry, decoration, bundle, global, and implicit-regular preference precedence. A usable explicit content-entry or decoration font does not require a usable default pool. Automatic selection requires a nonempty effective pool; if no usable explicit preference applies and that pool is empty, preparation fails with an actionable diagnostic. An unavailable winning face warns and resolves directly to the selected bundle's regular face; do not inspect lower-priority role preferences or select another bundle.

Do not store selected bundle identifiers, effective face identifiers, font bytes, filesystem paths, or content digests in operational state. Resolve current preferences once per complete stage preparation and use those faces consistently for all generated stages.

Do not independently select fonts for individual reveal stages.

Reuse a valid complete prepared-image set without resolving fonts, even when a selected face or font file has changed or become unavailable. If regeneration is needed, resolve current explicit preferences and the effective default pool deterministically; do not use a separate emergency bundled-font pool. Report an actionable preparation error if the selected font or required regular face cannot be loaded.

Font errors during regeneration must not change the committed quotation, content identity, reveal schedule, or reveal progression.

Do not distribute third-party font files without verifying their licenses and redistribution terms.

Do not add font downloading. Keep role-specific face resolution limited to quotation, source, and attribution within the single bundle selected for each preparation.

### Background loading and composition

Background identifiers, registration requirements, and default-pool validation are defined in [Background registry](CONTENT_FORMAT.md#background-registry). Selection precedence and recovery behavior are defined in [Presentation and rendering](ARCHITECTURE.md#presentation-and-rendering).

Discover bundled and user backgrounds from their category directories, using `importlib.resources` for package-owned assets so installed-package operation does not depend on a source checkout. Preserve stable bundled identifiers. Validate images as readable, single-frame PNGs in RGB or RGBA mode, with positive dimensions, without requiring source dimensions to match the configured output. Use deterministic aspect-preserving centered cover scaling and cropping on the design canvas. Preserve transparency over the paper-white base.

Use a controlled random source for testing equal-probability selection among distinct usable default-pool members. Resolve the background for a complete image-preparation operation, not during selection commitment or independently for reveal stages.

Keep background composition outside the shared quotation renderer. Compose the resolved background over a paper-white base on the design canvas, preserving RGBA transparency. Scale the completed graphical composition to the presentation canvas as specified in `docs/ARCHITECTURE.md`, then reuse preparation-wide results for every stage where appropriate. Use an appropriate high-quality Pillow resampling filter when dimensions differ, retain deterministic geometry, and close decoded resources promptly.

Daily-image preparation accepts the selected content, effective reveal stages, and current resource registries. It resolves a background from current preferences or pool configuration for the whole generated set. A supplied empty registry represents unavailable resources and applies the paper-white fallback policy.

When preparation cannot resolve or decode an optional background, report a warning and continue with paper-white according to the established fallback policy. Do not change the selected quotation or reveal progression. Keep resource reads bounded and close decoded images when no longer needed.

### Decoration loading and composition

Decoration identifiers, the initial ordered-layer manifest schema, and preference metadata are defined in [Decoration registry](CONTENT_FORMAT.md#decoration-registry). Discover bundled and user decorations through their package manifests and `importlib.resources` where appropriate. Validate every referenced image as a readable, single-frame RGB or RGBA PNG with positive dimensions; retain source alpha and do not alter source files.

Resolve presentation-wide choices such as decoration, font, background, palette, and layer preferences consistently for a complete preparation, while resolving output-specification-dependent insets, transforms, and raster results for each specification as defined in `docs/ARCHITECTURE.md`. Resolve effective QR availability separately for each output specification before selecting its conditional decoration layers. Keep selection outside rendering; compose each resulting graphical design on the design canvas before scaling it to the presentation canvas. Use deterministic scaling, rounding, and alpha composition. Do not infer presentation insets from slice values or image dimensions.

Test centered cover scaling and cropping directly on the design canvas, including reference-sized artwork, smaller and differently proportioned RGB/RGBA sources, alpha preservation, odd crop differences, and matching-size sources that need no transform. Test nine-slice source boundaries, 1:1 preservation of configured source-pixel thicknesses on the design canvas, edge `stretch` and centered `crop`, center stretching, alpha preservation, and exact shared boundaries. For example, a 1920 × 1200 source with 20-pixel slices on a 3840 × 2400 design canvas must retain 20-pixel edge/corner thicknesses. Cover invalid boundaries, opposing corners that do not fit the destination, crop destinations longer than their source edge segments, odd dimensions, and rounding cases that would otherwise introduce gaps or overlaps. Do not implement edge tiling.

Decoration-wide and per-layer tintability both default to true; test the logical AND, including an untinted accent layer. When any layer is effectively tintable, select one color using content-entry, decoration, global-pool, then built-in black precedence; a successful selection activates tinting. Preserve each layer's source alpha when applying that single preparation-wide decoration color. Artwork retaining authored RGB must explicitly be non-tintable. Reuse a complete valid set before resolving resources so later manifest or image changes do not invalidate it.

Image preparation accepts the effective decoration registry independently of the background registry. Reuse a complete valid set before resolving image resources, so registry or file changes do not invalidate it.

### QR composition

Follow the two-phase QR dependency in `docs/ARCHITECTURE.md`: resolve design-space placement, map the allocation to presentation-canvas pixels, and evaluate effective availability before choosing `always`, `qr`, or `no-qr` decoration layers. Availability includes presentation-level policy, selected-decoration `qr_ready`, valid in-bounds placement, and at least one presentation pixel per QR module. Rasterization and composition happen later on the presentation canvas, after literary rendering. Do not decide availability from policy and `qr_ready` alone or make a second decision in the decoration renderer.

Test default and all directional placements, per-axis defaults, single-axis centering, conflicts, malformed values (including booleans), design-canvas bounds failures, edge-rounding and odd centering cases, and the supported canvases. Verify effective availability under each policy/readiness/placement/raster-viability condition before conditional-layer selection, then verify QR rasterization and composition on the presentation canvas after literary rendering. Cover exact Version 0.1 encoding, a complete four-module quiet zone, opaque black-and-white pixels, and consistent placement across reveal stages. Test intentional policy and `qr_ready` suppression without warnings, invalid-placement and insufficient-raster-size suppression with warnings, and preservation of the selected decoration and literary preparation. Do not perform automatic collision avoidance or alter literary insets or artwork to reserve QR space. The information view remains independent of literary QR behavior.

Wheel and source-distribution tests must verify that bundled manifests, referenced images and fonts, applicable font licenses, and `assets/README.md` are included. Installed-package discovery must use package-resource APIs and must not depend on a source checkout.

### Keep presentation configuration focused

The initial release provides one configurable presentation layout.

Use the configurable output dimensions, design-canvas pixel presentation insets, and font-size bounds defined in `docs/CONTENT_FORMAT.md`.

Resolve configured geometry in design-canvas units and map it to the presentation canvas with deterministic rounding. Follow `docs/ARCHITECTURE.md` for destination-specific output specifications and the optional final whole-image resize.

The shared quotation renderer is responsible for arranging and drawing the quotation and its optional source and attribution within that region.

Layout calculation must account for all present fields before generating any reveal-stage image.

Use Pillow's font metrics and text-measurement facilities to determine suitable font sizes, line wrapping, and placement.

Text measurement must account for:

- actual glyph dimensions;
- line spacing;
- preserved line breaks;
- paragraph spacing;
- the complete effective literary rectangle;
- space occupied by source and attribution;
- the effective presentation style.

Avoid assumptions based solely on character counts or average character widths.

The fitting implementation must satisfy the presentation behavior defined in `docs/ARCHITECTURE.md`.

Prefer a straightforward deterministic fitting procedure over a general-purpose text-layout framework.

Do not hardcode the initial display resolution into unrelated content, selection, or scheduling logic.

Validate each destination's supported aspect-ratio and resolution specification, including aspect-mismatched requests. Exercise 1080p and 4K presentation/output cases without treating hardware-independent results as physical display validation. Verify that preparation produces the Waveshare's fixed 4:3 @ 1600 × 1200 output and that the backend rejects any image with different dimensions rather than resizing, cropping, or padding it.

Do not introduce a general-purpose layout framework or font-selection optimization engine without a demonstrated requirement.

### Stable presentation geometry

For each output specification's preparation, resolve the complete literary composition once, including all present source and attribution fields, using the full composition that will be visible across the reveal sequence.

That specification's resulting layout must contain sufficient information to reproduce stable typography and field positions across every reveal stage. Different output specifications may have different raster dimensions, wrapping, fitted font pixel sizes, and mapped geometry.

Presentation styles determine layout geometry. Image drawing uses the resolved geometry rather than independently interpreting style identifiers.

Keep style-specific layout behavior isolated so additional built-in styles can be introduced without changing content-selection policy, persistence mechanisms, scheduling, or display integration.

The initial implementation needs only the `centered` and `left-aligned` styles.

A small internal dispatch mechanism for selecting built-in layout behavior is sufficient. Do not introduce a public styling plugin interface or generalized layout framework without a demonstrated requirement.

All reveal stages within one output specification must use consistent layout geometry.

Reserved space for future reveals must not cause previously visible content to move when additional information becomes visible.

The renderer must not silently clip, truncate, overlap, or omit required text merely to produce an image.

If the complete composition cannot fit within the supported presentation region, report a meaningful error.

### Preparation and validation

For each required output specification, prepare its complete set of reveal-stage images from the durable daily selection and current presentation inputs. Use that specification's complete fully revealed literary composition to determine geometry for every stage in its set; do not require different specifications to share raster geometry.

Resolve the complete composition layout once per output specification and reuse it for every required cumulative visibility stage of that specification.

Each prepared image must be independently displayable.

Normal reveal transitions select an existing prepared image rather than invoking text fitting, layout calculation, or image rendering.

Do not require intermediate stages to have been physically displayed before preparing or presenting a later stage.

The same rendering facilities must support preparation of a single fully visible image for views that do not require progressive reveals.

Test image dimensions, supported output formats, presentation styles, field visibility, layout stability, and significant fitting constraints without physical display hardware.

Tests must verify that all present quotation, source, and attribution text remains within the configured presentation-canvas literary region without overlap or clipping.

Visual inspection remains appropriate for typography and layout quality.

### Information view preparation and publication

Prepare the information view using the existing Pillow image-composition facilities.

Keep view-specific background composition separate from the shared quotation renderer. The background generator is responsible for project identity, build information, runtime details, and copyright information. The quotation renderer remains responsible for the literary composition.

Supply the information view's curated quotation from application-owned release resources rather than the user content library.

Render the information view as one complete, fully visible image. Do not introduce reveal stages or daily-selection artifacts for this view.

Keep optional runtime-data collection lightweight and tolerant of unavailable platform facilities. Do not require network connectivity, Git, hardware-specific dependencies, or additional background services merely to prepare the view.

Use the installed application version as the primary version identifier. Include build or commit metadata when reliably available without requiring a Git working tree.

Collect basic environment details through appropriate Python or platform facilities. Avoid unnecessary subprocesses, external service calls, broad network enumeration, or repeated system probing.

Do not include credentials, tokens, private configuration contents, or privileged filesystem information in the rendered view.

Use the existing display publication coordinator to distribute the prepared information-view image to configured backends.

Distinguish information-view publication identity from committed daily presentation identity without exposing view semantics to display backend implementations.

The startup information-view interval is transient application state. It does not require durable storage or modification of the committed daily selection.

Use a monotonic clock for the configured display duration. Begin timing when the first backend successfully acknowledges publication of the information view.

Bound the initial attempt to obtain a successful information-view publication so recoverable backend failures cannot postpone daily presentation indefinitely.

Do not require successful publication by every backend before the information-view interval begins or ends.

When the interval ends, reevaluate the normal scheduling requirements and request the currently appropriate prepared daily image. Preserve independent backend execution, pending-update coalescing, and safe handling of active hardware transfers.

Do not reset or reconstruct display backends merely to transition between the information and daily views.

Information-view preparation failures must be reported without preventing ordinary daily presentation when that remains possible.

Include hardware-independent automated tests covering:

- default, disabled, and explicitly configured information-view durations;
- invalid duration values and documented fallback behavior;
- preparation when optional build, network, or environment information is unavailable;
- correct use of application-owned literary content independently of the content library;
- preservation of committed selection, repetition history, and reveal progression;
- publication to multiple independent backends;
- timer start after the first successful publication;
- wall-clock adjustments during the information-view interval;
- bounded initial publication attempts when no backend succeeds;
- transition to the latest required daily presentation after missed reveal events;
- failure isolation and shutdown during information-view presentation.

Inspect representative information-view images at the target resolution to evaluate typography, branding, information density, and visual hierarchy.

The initial implementation needs one application-owned information-view layout. Do not introduce an independent styling system, plugin interface, interactive control service, or general-purpose diagnostic framework.

## Display backend

### Interface and implementation boundaries

Provide a small synchronous display backend interface whose publication operation accepts a complete Pillow image and identifies one selected configured destination. The destination may be passed explicitly or represented by an equivalent destination-bound abstraction; an image-only `update(image)` operation is not sufficient for a backend that owns multiple named outputs. The contract is generic and does not prescribe a particular Python method signature.

The interface operates on complete Pillow images rather than artifact paths.

Callers own the supplied images and their lifetimes. A backend must not require an image to remain available after its synchronous publication operation returns unless it has independently retained the data it requires.

Keep the interface independent of Waveshare, SPI, GPIO, desktop GUI libraries, selection, persistence, and reveal scheduling.

Implement display backends in a dedicated `refrain.display` package.

Use a small explicit selection mechanism for built-in implementations. Select backends by stable configuration identifiers rather than Python module paths.

Do not introduce dynamic plugin discovery, entry-point registration, generalized dependency injection, or a display plugin framework.

### Backend selection

Construct the configured display backends at application startup.

Use explicit mappings or conditional construction for supported built-in implementations. Import backend-specific dependencies only when the corresponding implementation is selected.

The configuration must contain at least one backend and must not contain duplicate backend types.

A recognized but unimplemented backend must produce an actionable diagnostic.

Do not silently substitute another backend when construction or initialization fails.

Keep configuration validation separate from actual hardware availability checks.

Backend construction and initialization failures must be isolated so that an unavailable destination does not prevent other configured destinations from operating.

### Multi-backend coordination

Use independent execution for each configured backend instance so that slow or blocked operations do not delay publication through other backend instances. Destinations sharing one backend instance share its lifecycle and serialization.

A dedicated worker per backend instance is the preferred initial implementation. Use ordinary Python threading facilities rather than introducing a separate asynchronous framework or process-management service.

Keep backend publication synchronous and based on complete Pillow images.

Serialize publication and lifecycle operations for each individual backend instance. Never invoke overlapping operations on the same instance, including operations for different named destinations.

For normal scheduled publication only, maintain at most one pending desired presentation identity per configured destination. When a newer scheduled presentation becomes required, replace that destination's obsolete pending scheduled request rather than accumulating stages, and retain the latest required identity for that destination. Track the most recent successful scheduled publication independently per destination, including named outputs even when they share an output specification or backend instance.

Do not interrupt an active hardware transfer unless its backend explicitly supports safe interruption.

Bound shutdown waiting to 60 seconds total across workers. If a synchronous publication is still blocked at the deadline, report it and return without calling `close()` concurrently with that operation. Keep the worker daemonized and retain its active image until the operation returns or the process exits; the worker then attempts backend cleanup if it returns.

The coordinator must remain responsive to scheduling events while backend workers are active.

Track each destination's latest required scheduled presentation independently from its most recent successful scheduled publication.

Persist advancement of the globally required reveal stage through the existing operational-state mechanism without waiting for all backend updates to complete. Backend workers must not independently advance authoritative reveal progress. A failed or uncertain destination publication affects only that destination's publication status and recovery requirements.

A scheduled destination acknowledgement is successful only when that destination's publication operation completes successfully. Success for another destination must not satisfy its scheduled acknowledgement, even when both use one backend instance or the same image variant.

Identify each requested presentation using an opaque identity associated with the prepared image. The coordinator may derive this identity from the committed selection revision and resolved reveal stage, but backend implementations must not depend on those values or inspect persistent operational state.

Associate each outstanding scheduled destination publication with the identity it was asked to publish. Record scheduled acknowledgement only for that identity, so completion of an older operation cannot incorrectly satisfy a newer pending request.

Transient publication uses separate admission and completion state, not the replaceable scheduled-presentation slot. Once admitted, a transient request must complete or fail for every requested destination and must not be replaced because newer scheduled work appears. It neither changes the scheduled desired identity nor clears or satisfies scheduled acknowledgement. Shared backend serialization, image ownership, resource lifetime, and safe shutdown rules apply to both scheduled and transient operations.

Avoid unnecessary image duplication. Backend workers must receive images whose lifetime remains valid throughout their publication operation.

Coordinate artifact cleanup with outstanding image readers and backend operations. Do not remove prepared images while an active or pending publication still requires them.

Do not persist backend-specific presentation acknowledgements. On every startup, recovery must reconcile the currently configured destinations and output specifications, then publish the currently required reveal stage to every available configured destination.

Keep worker state and synchronization limited to what is necessary for independent publication, shutdown, and recovery.

### Desktop window backend

Provide a desktop window backend for graphical Windows and Linux environments.

Use an established GUI facility rather than creating a custom windowing system.

The backend must support successive complete-image updates in a persistent window.

The window must remain responsive between updates, including while the application is otherwise idle.

Keep GUI dependencies and event-loop requirements isolated from the application scheduler and non-window backends.

Do not require desktop GUI dependencies for ordinary hardware-independent imports or for headless Waveshare deployments.

The desktop backend is a development and testing presentation destination, not an alternative image renderer.

Use the platform's Tk support and Pillow's `ImageTk` presentation adapter. Import them only when constructing the window backend; configuration, rendering, and other hardware-independent imports must not require a graphical environment. Keep the Tk event loop in a backend-owned thread so updates remain synchronous without requiring the caller to run a GUI loop.

The window backend must preserve caller-owned image data, replace the image in its existing window, and report initialization, presentation, and cleanup failures. On Linux, a Tk-capable Python installation and an active graphical session are required; standard Windows Python installations typically include Tk.

### HTTP image-server backend

Implement the `image-server` backend using standard HTTP facilities suitable for the supported Python runtime.

Prefer the Python standard library unless an additional dependency provides a demonstrated benefit.

Keep HTTP request handling and network-resource ownership within the backend. The application scheduler must not run a server event loop or process individual HTTP requests.

The service must remain responsive between image replacement operations.

Backend construction must establish that the configured listening address and port are usable before reporting successful initialization. Binding and startup failures must produce actionable diagnostics through the common display-backend error interface.

Encode incoming Pillow images as complete PNG representations before making them available to HTTP clients. Retain the encoded bytes and associated entity tag in backend-owned memory.

Replacement of the currently served representation must be synchronized with concurrent HTTP requests. A request must observe one consistent image and its corresponding entity tag, without holding backend state locked during network transmission.

Preserve the previously accepted representation when a replacement cannot be completed successfully.

Use standard HTTP conditional-request semantics rather than introducing a custom image-version or polling protocol.

Keep the HTTP interface narrowly scoped and read-only. Do not expose arbitrary filesystem paths, application configuration, content-library data, persistent state, or administrative operations.

Handle unsupported methods and paths explicitly. Malformed requests and individual client disconnections must not terminate the backend or corrupt its current representation.

The backend must stop accepting requests and release its listening resources during `close()`. Coordinate concurrent request handling and shutdown so that inactive or slow clients cannot indefinitely prevent orderly application termination.

Test the backend without physical display hardware or external network services. Automated tests should exercise the HTTP interface through a real local listening socket, including:

- successful retrieval of every named output PNG;
- correct response content type and image contents;
- independent entity tags and conditional requests for each named output;
- replacement of each output image and invalidation of that output's previous entity tag;
- correct delivery when multiple outputs share a prepared variant or use distinct variants;
- requests made before the first successful image update;
- failed image replacement preserving the previous representation;
- concurrent requests and image updates;
- invalid HTTP methods and paths;
- initialization failures caused by unavailable listening addresses or ports;
- orderly shutdown, repeated cleanup, and rejection of updates after closure.

Use locally allocated test ports rather than assuming a fixed port is available. Tests must not depend on access to an external network, a particular LAN configuration, or Raspberry Pi-specific facilities.

### Waveshare model-specific backend

Use the Waveshare Python implementation appropriate for the supported 13.3-inch e-Paper HAT+ (E).

Keep the imported driver surface as small as practical.

Do not include support for unrelated Waveshare display models merely because those implementations are distributed together.

Record the provenance, version or revision, and license of vendor code incorporated into the repository.

Do not modify vendor driver behavior without understanding the relevant hardware requirements.

When modifications are necessary, keep them reviewable and explain why they are required.

The physical backend uses Linux hardware SPI and GPIO character-device access through its optional `hardware` dependencies. Configure the required SPI overlay, `/dev/spidev0.0`, GPIO lines, and service-identity device permissions according to the project's deployment and permissions guidance. Keep the application process under the minimum practical privileges rather than running it as root. The transport must remain lazy-loaded so non-hardware development and other display backends do not require these dependencies.

### Hardware isolation

Only the Waveshare backend should depend on its vendor driver, SPI, or GPIO facilities.

The application must remain testable without physical hardware.

Do not expose GPIO pins, controller commands, or driver-specific state to content, scheduling, rendering, or persistence components.

Backend implementations must validate incoming image dimensions and representation against their supported destination. Do not silently resize or recolor prepared images.

### Hardware lifecycle

A physical backend owns initialization, full-frame updates, controller sleep or release, and cleanup.

Use supported driver lifecycle operations rather than assuming a controller can resume from sleep without reinitialization.

The shared interface must not force the application to manage hardware-specific initialization or sleep operations.

`close()` must support orderly release of resources and should be safe during ordinary shutdown and failure cleanup.

Validate initialization, repeated updates, sleep behavior, and recovery using the actual display.

A working example program establishes basic compatibility but does not prove reliable long-term unattended operation.

### Refresh policy

Avoid unnecessary physical refreshes.

A successful prepared-image update should not be repeated merely because the scheduler reevaluates its state.

When the desired stage advances during an active update, the backend should ultimately present the latest required stage rather than replaying obsolete intermediate stages.

Avoid overlapping display operations.

Backend processing order must not delay publication to another destination.

### Display failures

Classify failures sufficiently to support meaningful diagnostics and bounded recovery.

`DisplayBackendError.recoverable` defaults to true. Backends mark errors nonrecoverable when the active instance cannot safely accept another update, such as a closed window or disabled hardware transport.

Retry recoverable errors on the affected backend without blocking other workers or the application scheduler.

Only `DisplayBackendError` instances explicitly marked recoverable are retried. Unexpected exceptions during construction or update are logged as programming/backend failures and terminally disable that destination.

An unrecoverable backend error must release or disable the affected instance safely. Other functional backends must continue operating.

Initialization failures should be reported independently. Do not assume that an instance which failed construction can be retried using the normal update interface.

Where recovery requires constructing a replacement backend instance, coordinate cleanup and reinitialization without overlapping operations on the same destination.

Use bounded retry delays rather than unrestricted rapid retries.

Retries must not indefinitely block recognition of newer scheduled presentation requirements.

If every configured backend becomes unavailable, report the loss of all presentation destinations. Continue bounded recovery when possible; otherwise allow the application to fail so that external service supervision can respond.

Distinguish failures occurring before presentation, failures during presentation, and uncertain outcomes when the underlying implementation permits.

Preserve the retained e-paper image when possible.

Do not report successful hardware presentation when the result is unknown.

Hardware validation must distinguish between driver-call success and visibly correct panel output.

### Multi-backend validation

Include hardware-independent tests covering:

- Configured destinations receiving the prepared variant matching their output specification, with variants shared only for identical specifications.
- Duplicate backend rejection.
- Independent initialization and failure reporting.
- One backend continuing while another is blocked or slow.
- No overlapping updates to an individual backend.
- For normal scheduled publication, replacement of obsolete per-destination pending stages with the latest required presentation.
- Independent successful scheduled-publication tracking per destination, including named outputs sharing one output specification.
- Failed and uncertain destination publications not being treated as successful.
- Recovery from individual backend failures without reselection.
- Startup recovery and republication to available backends.
- Artifact lifetimes while updates remain active.
- Graceful shutdown while one or more backends are busy.

Use injected or simulated backends to test slow and failed updates deterministically.

Validate the existing window and image-server backends together on a supported graphical development environment.

Verify physical Waveshare operation with another enabled backend on the target Raspberry Pi before declaring multi-backend presentation validated.

## Scheduling and timekeeping

### Scheduling

Use timezone-aware datetimes for absolute instants and monotonic clocks for durations.

Use operating-system local civil time for display-day and reveal calculations. Resolve future wall-time deadlines with operating-system local-time rules; a timezone-aware value returned by `datetime.now().astimezone()` may contain only the current offset and is not sufficient to resolve future dates.

Keep local wall-time conversion isolated so tests can inject deterministic local-time rules without changing the process timezone.

Avoid assumptions that a local day always contains 24 elapsed hours.

Resolve ambiguous wall times to their first occurrence and nonexistent wall times to the first valid instant after the gap, including non-hour offset transitions.

Do not use fixed-duration sleeps as a substitute for correct calendar-boundary calculations.

The scheduler should ordinarily wait until the next meaningful event rather than polling continuously.

`next_scheduling_deadline()` derives reveal deadlines from the committed selection's effective schedule and combines them with the next configured day-start time. `wait_for_scheduling_event()` waits interruptibly and periodically rechecks wall time, returning control after a clock adjustment so the coordinator can recalculate an obsolete deadline. Scheduling is based on comparing the current logical display date with the committed selection's date, not on a boundary-observation event.

### Wall-clock changes

Implement the documented forward- and backward-clock behavior without allowing previous reveal stages to become hidden.

If a clock change alters the logical display date, establish one selection for the current logical date regardless of adjustment direction. If the date is unchanged, retain the selection and its monotonic reveal progression. Tests must cover these cases without requiring the host operating-system clock to be modified.

Separate the current time source from scheduling policy sufficiently to permit controlled test inputs.

Use monotonic elapsed time for retry intervals and other durations that should not be affected by wall-clock adjustments.

### Recovery after interruption

Persist the display date and day-start context required by the architecture. On startup, compare the current logical display date with the committed date: retain the selection when they match and establish one selection for the current logical date when they differ.

Test logical-date comparison across restarts, missed day starts, backward and forward clock adjustments, and large forward jumps. Repeated evaluations for the same committed logical date must not duplicate a selection. Do not add or infer clock-observation history.

### Demo-session ownership and timing

`run_demo()` owns accelerated progression separately from normal scheduling. Load configuration first, then create standard-library temporary session storage for the existing operational-state store, prepared-image artifact store, and global-history store. Storage settings may be parsed as part of configuration but must not be used as demo persistence targets; do not inspect or open production persistence locations. Determine the initial display date through the OS-local/day-start calculation once; do not reevaluate wall time to drive demo stages.

Reuse the application selection, resource resolution, daily-selection commitment, reveal-progress persistence, image-cache recovery, and history-recording operations. Keep a pending selection proposal across commit retries, including uncertain publication followed by a failed reload, so an already published selection cannot be replaced inadvertently. Recover preparation or image-loading failures from the durable daily selection without skipping the requested stage. Best-effort history recording retains its ordinary semantics.

Use `resolve_reveal_stages()` for canonical progression. Publish prepared images with revision/stage identities through `DisplayPublicationCoordinator`. Wait interruptibly for any successful acknowledgement, then measure the viewing interval from `first_successful_publication_time()` using the same monotonic clock supplied to the coordinator. An unacknowledged stage cannot advance. Initialization, preparation, failed publications, and wall-clock adjustments must not consume or alter the interval. Recheck elapsed time after interrupted or early waits; bound individual duration waits to avoid platform timeout overflow for large finite CLI intervals.

Use the normal independent backend retries and increasing application retry delays from 1 to at most 60 seconds. Do not reset backends between stages or require all destinations to succeed. Wake progression and retry waits on shutdown or terminal loss of every backend, and report the latter as an actionable application error rather than continuing selection without a destination.

Stop new work on Ctrl+C or SIGTERM. Close the publication coordinator before removing temporary storage, preserving its bounded worker shutdown and image-reference ownership. Attempt session cleanup even after fatal application errors; report cleanup failures without concealing the primary error or touching production files. Each invocation starts fresh and has no resumable session state. Suppress the startup information view in demo mode.

Cover CLI validation and normal-mode requirements, canonical progression, fixed eligibility dates, repeated revisions and pool exhaustion, stable resource identifiers, isolation from production files, fresh sessions, cleanup, interrupted waits, and preparation/publication/storage recovery with deterministic hardware-independent tests. Use injectable clocks, controlled waits, and fake backends instead of real-time sleeps. Include independent healthy/slow or unavailable destinations and all-backend loss; retain ordinary scheduler, startup, persistence, and recovery regression coverage. These tests do not establish physical e-paper behavior.

## Logging and diagnostics

### Logging

Use Python's standard `logging` facilities.

Emit application logs to standard output and standard error as appropriate for supervised execution.

Do not require a separate log server, database, or third-party logging framework.

Allow systemd and journald to manage ordinary deployed logs.

Avoid implementing application-specific log rotation or persistent diagnostic log files without a demonstrated need.

Global selection history is structured application data and must remain separate from ordinary diagnostic logging.

### Log content

Log meaningful lifecycle and state changes, including:

- application startup and shutdown;
- application configuration defaults and recoverable validation problems;
- output-specification defaults and paired-field validation for window and image-server outputs, fixed Waveshare dimensions, unique named output IDs, and preparation of all unique required specifications;
- excluded content files and entries;
- fatal configuration or content-library failures;
- daily selection commitments;
- recovery of committed selections;
- image-preparation failures;
- physical display failures and recovery;
- significant scheduling or clock-related events.

Use `INFO` for ordinary operational events and documented defaults applied to omitted optional settings.

Use `WARNING` for invalid or unrecognized values that were ignored, replaced by defaults, or excluded without preventing operation.

Use `ERROR` for failures that prevent a required operation from proceeding.

Log warnings with enough context to identify the affected file, field, entry, or resource and explain the action taken.

Consolidate informational default notices where practical.

Do not log every scheduler iteration or repeatedly emit identical errors during unchanged retry conditions.

Log messages must be concise, human-readable, and useful for diagnosing unattended operation.

Do not unnecessarily log entire quotation libraries, large serialized daily selections, or sensitive configuration values.

### Diagnostic behavior

Diagnostics must distinguish a rejected input value from a failure of the entire configuration or content library.

Recoverable validation problems must remain visible to the operator without preventing unrelated valid settings or entries from being accepted.

Fatal errors must identify the missing or unusable requirement and the next useful troubleshooting step.

Configuration and content diagnostics must preserve their source location where available.

Diagnostic facilities must not mutate persistent state or operate the physical display unless explicitly intended to do so.

## Testing and validation

### Automated tests

Use pytest for hardware-independent automated tests.

Tests should verify observable behavior and documented contracts rather than relying unnecessarily on private implementation details.

Every substantive behavior change should include focused regression coverage where practical.

The ability to import and test core components without Raspberry Pi hardware is a project requirement.

### Viewer presentation tests

Test default and explicit `@preview` selection, exact normal-entry selection, omitted and explicit 1-based quotation numbers, malformed/zero/negative/out-of-range selectors, and independence from eligibility, priority, and repetition. Verify that runtime and viewer use the shared preparation/resolution machinery, normal preference precedence remains unchanged, and each explicit override takes precedence only for its property. Cover strict rejection of unavailable requested resources, ordinary pool resolution for unspecified properties, and QR placement/readiness constraints when QR is forced on.

Verify `refrain-viewer --debug-layout` uses the shared presentation diagnostics without enabling overlays in normal runtime or demo preparation.

Cover each aspect's full design-canvas default, exact and mismatched requested resolutions, the one-output-specification design/presentation/output pipeline for local inspection/export, final-image PNG export, and the default-window, PNG-only, window-only, and combined destinations. Mock the local window where necessary and verify desktop fitting does not mutate the output image. For local inspection/export, use sentinel persistence locations and backend factories to verify the viewer never accesses configured backends or runtime persistence. For push, verify it never constructs, initializes, or directly accesses configured backends, but does exercise the resident runtime-control publication path using discovered output specifications. Verify that a destination reported as not supporting transient publication is rejected before rendering, both when selected directly and when included by `--push all`. Do not treat mocked window behavior as graphical-session validation.

### Core test coverage

Automated testing should cover:

- application configuration parsing, defaults, warnings, and fatal validation errors;
- recursive asset discovery, package boundaries, manifest schemas, safe relative references, symlink escapes, malformed-resource isolation, identifier validation, collisions, and independence of discovered availability from default pools;
- missing optional values with documented defaults;
- explicitly invalid optional values with and without defaults;
- unrecognized application-configuration fields;
- unavailable or invalid registered fonts and effective font-pool construction;
- built-in and custom palette values, invalid palette definitions, and effective text-color pool construction;
- bundled and custom background registration, independent rejection of invalid PNGs, reserved identifiers, and default-pool construction;
- explicit background preferences, `"none"` suppression, and unavailable-preference fallback;
- content and decoration text-color preferences, precedence, unavailable members, and duplicate-free selection;
- content-file parsing failures and independent rejection of invalid entries;
- partial content-library acceptance with valid entries preserved;
- duplicate entry identifiers and deterministic conflict handling;
- missing, inaccessible, and empty content libraries;
- repetition-history cleanup using accepted content only;
- preservation of repetition history when content discovery fails or no valid quotations remain;
- recovery of valid current-format daily selections independently of current content-library availability;
- clear rejection of incompatible current state without modifying the state file; diagnostics for platform-standard paths may direct the operator to stop Refrain and run `refrain --reset`, while diagnostics for configured paths outside the standard location identify that path and require manual backup and quarantine/removal of only that file;
- current selection-record round trips containing selected content, effective schedule, day context, and required repetition/reveal state, without derived rendering decisions;
- recovery of the selected quotation and monotonic reveal progress after image preparation or cache failure;
- no legacy development-schema readers, migrations, normalization, or historical-format recovery tests;
- stable entry and quotation identities;
- normalized quotation matching;
- date-specificity precedence;
- priority selection;
- equal-probability random selection behavior where practical;
- global and repetition-history behavior;
- pool exhaustion and selective reset;
- atomic selection commitment;
- recovery from interrupted writes;
- current daily-selection recovery;
- preparation and recovery of reveal-stage images;
- cumulative reveal progression;
- forward and backward clock adjustments;
- display-day boundaries and restart behavior.

Randomized selection tests should use controlled random sources where deterministic outcomes are needed.

Do not rely on statistical luck to make unit tests pass.

### Filesystem and failure testing

Use temporary directories and isolated test state.

Test path selection with injected platform and environment information. Exercise category-specific custom-resource discovery independently of the current working directory, including nested package references and manifest confinement, while verifying that content directories retain configuration-relative and explicit-absolute semantics. Exercise repeatable initialization, existing user data and assets, links, exclusive file creation, race-time destinations, marker-verified interrupted sample installation, partial failures, reset preservation, purge deletion, confirmation, and deletion boundaries using temporary locations; do not use developer application-data directories.

Test persistence failure at meaningful boundaries, including failures before and after commitment.

Verify that incomplete data cannot be mistaken for successfully committed state.

Where practical, test recovery using a newly initialized application instance rather than only inspecting the state of the instance that performed the write.

### Rendering tests

Distinguish assertions on the design canvas, presentation canvas, and output image. Verify stage completeness and stable layout geometry. All reveal stages for one output specification have identical output dimensions; destinations with the same output specification share those images. Do not require variants for different output specifications to have identical dimensions. Verify that each configured destination resolves its own output specification and that the prepared variant set contains exactly the unique required specifications.

Include an aspect-mismatched output specification with declared aspect 4:3 and requested resolution 1600 × 1190. Assert that the design canvas is 3200 × 2400 and background/decorative composition occurs there; literary geometry and font fitting, QR viability and rasterization, and diagnostic overlays resolve on the 1596 × 1197 presentation canvas; and only the completed image is resized to the 1600 × 1190 output image. This case must not be replaced by tests where presentation-canvas and output-image dimensions happen to match. Also exercise exact-aspect supported configurations. Verify deterministic half-up rounding and rejection of degenerate geometry.

Use representative quotations of different lengths and combinations of optional metadata.

Test automatic text fitting with:

- short quotations;
- long quotations requiring multiple wrapped lines;
- explicit line breaks and paragraphs;
- quotations that fit at the maximum permitted font size;
- quotations requiring a smaller permitted font size;
- quotations that cannot fit at the minimum permitted size.

Verify that all rendered literary content stays within the effective rectangle mapped from design-canvas insets to the presentation canvas.

Verify that backgrounds and decorations are composed on the design canvas, that the completed graphical composition is scaled to the presentation canvas, and that literary text, QR, and diagnostics are composed there. Verify the optional final whole-image resize for both reduction and enlargement, and no resize when requested and presentation dimensions match. Do not require text or QR pixels to remain individually unchanged through that final resize.

Verify that independently selected quotation, source, and attribution faces use their own metrics and remain consistent across all reveal stages. Include both presentation styles, optional-field combinations, mixed-face baselines and punctuation, fitting, clipping, and unchanged geometry during reveal.

Verify that literary text colors are consistent for the quotation, source, attribution, and punctuation across reveal stages generated together, and that the information view's typography is unchanged.

Test font configuration and selection behavior, including:

- valid registered fonts;
- invalid or unreadable registered fonts;
- empty default font pools;
- default identifiers missing from the registry;
- explicit content-entry font preferences;
- a valid explicit content-entry or decoration preference with an empty effective default pool;
- automatic-selection failure when the effective default pool is empty and no usable explicit preference applies;
- `font_faces` parsing and invalid-value handling at all four configuration/content/manifest levels;
- role-face precedence, explicit-regular overrides, unavailable winning-face fallback without lower-level preference lookup, and decoration preferences applied to an entry-selected bundle;
- consistent face resolution across stages generated together and reuse of complete caches despite later typography configuration or asset changes;
- unregistered content-entry fonts and their warnings;
- randomized selection from the default pool;
- absence of resolved font identifiers and face choices from operational state and global history;
- image regeneration using current font preferences and available assets after cache invalidation;
- preference fallback and diagnostics when a requested font is unavailable, without an emergency bundled-font pool;
- consistent font use across every reveal stage prepared together;
- reuse of valid prepared images independently of subsequent font-file changes;
- actionable failure when no usable font resource can be resolved.

Use deterministic random sources where required.

Test ordered multi-layer decoration composition, all QR conditions, RGBA transparency, decoration-wide AND per-layer tintability, color-precedence selection and automatic tint activation, the untinted-accent case, consistent composition across reveal stages, and plain output for `"none"`. Verify diagnostics and established resource fallbacks, and that a valid cached set is reused without checking resource changes. Do not test or implement QR/text collision detection or automatic overlap correction.

Test background cover scaling and centered cropping and decoration `contain` scaling for portrait, landscape, matching, smaller, and larger source images, including alpha, odd dimensions, exact output size, and deterministic results. Test nine-slice corners, preservation of resolved corner dimensions across 4:3, 16:9, and 16:10 canvases, edge stretching, centered edge cropping, center stretching, source-pixel bounds, destinations too small for preserved corners, crop destinations longer than available source segments, and deterministic rounding without gaps or overlaps.

Automated image comparisons may be used where they provide stable, meaningful regression coverage.

Do not rely exclusively on exact pixel comparisons for behavior that is better validated through semantic or geometric assertions.

Visual inspection remains appropriate for typography and layout quality.

### Hardware validation

Validate hardware-dependent behavior on the supported display. Backends receive the output image matching their resolved output specification and must not geometrically resize, crop, pad, or otherwise adapt it unless an explicit backend contract permits that operation. Backend-specific pixel-format or orientation conversion remains permitted where defined by that contract.

Hardware validation should include:

- driver initialization;
- complete image transfer and refresh;
- delivery of the prepared `4:3 @ 1600 × 1200` output image to the Waveshare backend, with rejection of any image with different dimensions;
- correct destination orientation and representative color rendering;
- representative resolution-independent output on a non-e-paper destination;
- repeated scheduled updates;
- controller sleep and subsequent use;
- retention of the displayed image after sleep;
- application restart;
- clean shutdown and recovery following a failed presentation where practical;
- correct presentation of representative prepared images.

Report the exact tested hardware, operating-system environment, and relevant limitations.

A hardware-independent test or mocked driver does not constitute physical display validation.

Do not claim a Raspberry Pi model is supported solely because it uses a compatible GPIO interface.

### Resource validation

Measure memory use, image-preparation time, and storage requirements on the Raspberry Pi 3B+ when those characteristics materially affect supported deployment targets. Do not reject rendering-quality decisions solely because they add work to infrequent daily image preparation.

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

The installed package includes a complete default configuration and sample content library as package resources. Explicit initialization copies these resources to standard per-user locations, but ordinary startup never performs installation or repairs missing user configuration.

A package repository, installer framework, or container runtime is not required.

Deployment instructions must identify the supported operating system, system dependencies, Python environment, configuration locations, and persistent-state requirements.

Installation must not depend on the developer's local directory structure.

Initialization is noninteractive and repeatable. Preflight every required path and destination type before writing. Reuse real directories, preserve an existing regular configuration file, and initially install samples only into a missing or empty standard content directory. Leave ordinary pre-existing nonempty content uninspected and untouched. A retry after interrupted sample installation may resume in the now-nonempty directory only when the temporary marker matches the packaged sample set and every existing expected sample matches its packaged bytes. Create only missing sample files exclusively and remove the marker after the sample set is complete. An invalid marker or conflicting sample requires manual inspection rather than treating arbitrary content as an interrupted installation. Create missing standard user asset category directories, accepting existing nonempty directories without inspecting or modifying their files; never copy bundled visual resources into them. Reuse state and cache directories without modifying existing state, history, or artifact files. Refuse links or unexpected objects that redirect or block safe access. On failure, report created destinations and leave them in place so a later initialization can retry safely when ownership is established.

Reset and purge are destructive standard-path operations and require exact interactive confirmation; they must not offer a noninteractive bypass. Resolve deletion scope only from platform-standard Refrain-owned locations, never from configured runtime storage values. Do not remove shared parent directories or follow a POSIX symlink, Windows junction, reparse point, or other filesystem indirection into an external tree. A linked standard root cannot establish safe ownership and must be refused; links encountered inside an owned tree must never be traversed as directories. Report the failed operation and affected path on permission or I/O errors, and do not perform out-of-scope recovery.

Reset removes only the standard state file, active and rotated global-history files, and Refrain-generated cache contents while preserving configuration, content, the complete user-assets tree, and standard directory structure. Purge removes the Refrain-owned standard directory trees and their contents, including standard user assets under the configuration directory after explicit confirmation. Both operations are intended for use while Refrain is stopped; their standard-installation mutation paths must also participate in the runtime ownership lock described above. This protects against cooperating Refrain processes, not arbitrary concurrent hostile filesystem mutation.

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

Valid current-format selection state and histories must survive application restarts. Prepared images are disposable and may be regenerated. During prerelease development, incompatible state schemas do not require migration support. A diagnostic for incompatible platform-standard state may direct the operator to stop Refrain and run `refrain --reset`; for a configured state path outside the standard location, identify that path and require manual backup and quarantine/removal of only that file. `--reset` does not manage custom paths.

Avoid writing runtime state into the installed Python package directory.

Define and document platform-standard per-user paths rather than assuming a particular username or current working directory. Omitted state, global-history, and artifact paths independently retain their platform-standard defaults; demo persistence remains isolated in temporary storage.

### Runtime updates

Application updates must not silently discard valid current-format selections or histories. Incompatible state from earlier prerelease development may require the explicit reset described above.

Persistent-state changes before the first release do not require migration from prior development schemas. Reassess compatibility when Refrain has released a public format; changes to public YAML schemas still require review against the documented interface.

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
- a general-purpose management/web application service or runtime web infrastructure beyond explicitly documented backends and features;
- unnecessary asynchronous processing frameworks;
- automated release infrastructure before the project has a demonstrated release need.

Add these mechanisms only when concrete requirements justify their cost.

The goal is a small, maintainable application that behaves correctly and predictably on supported hardware.