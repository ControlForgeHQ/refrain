# Destinations and Runtime Control

## Backend contracts and destination validation

Refrain publishes complete rendered images through narrow, hardware-independent destination backend interfaces.

A backend provides:

- A destination-aware synchronous publication operation that accepts a complete Pillow image and identifies the configured destination receiving it.
- `close()` to release backend-owned resources.

The publication contract must support one backend instance serving multiple named destinations. An image-only interface without destination identity is insufficient for such backends.

The contract does not prescribe a particular Python method signature.

For destinations requiring publication metadata, the application supplies the corresponding completed, validated publication document independently of image rendering. Metadata finalization belongs to the application; backend storage and delivery responsibilities do not include literary interpretation or artistic resolution.

The resident backend types are:

- `window`: Presents complete images in a graphical desktop window.
- `waveshare-13in3-e`: Presents complete images on the supported Waveshare 13.3-inch e-Paper HAT+ (E).
- `publish`: Stores complete images and finalized publication metadata in independently consumable filesystem datasets.

`publish` is the sole non-direct resident backend. The resident does not host HTTP services, manage network clients, or require network availability for publication.

Network image delivery is provided by the independent [Image Server](75-IMAGE_SERVER.md).

A valid application configuration contains a nonempty `destinations` sequence.

Each destination requires a globally unique, URL-safe identifier, supported backend type, output specification, and explicitly configured audience, as defined in [Application Configuration](../schemas/CONFIGURATION.md#destinations).

Validate destination configuration before constructing backend instances or opening hardware resources.

Backend implementations declare side-effect-free capacity limits:

- `window`: One configured destination.
- `waveshare-13in3-e`: One configured destination.
- `publish`: Multiple configured destinations through one shared backend instance.

A destination declaration does not necessarily create a separate backend instance. Destinations sharing one backend instance share that instance's lifecycle and operation serialization while retaining independent identity, output geometry, publication status, and acknowledgement.

Validate configured destination counts against each backend's declared capacity before initialization.

Recognized but unavailable or unimplemented backend types must produce actionable diagnostics. Do not silently substitute another backend type.

Backend construction failures must be isolated so that one unavailable backend instance does not prevent independent configured instances from operating.

Every configured destination receives the complete prepared image corresponding to its output specification and effective presentation requirements.

Destinations may share prepared pixels only when their output specifications and effective requirements are compatible. Sharing pixels does not merge destination identity, audience, publication events, or acknowledgements.

Destination identifiers are opaque routing values. The application coordinator and runtime-control clients must not infer backend types, hardware, transport, or capabilities from identifier spelling.

The backend interface operates on complete Pillow images rather than paths to scheduled prepared-image artifacts.

Callers own supplied image objects and their lifetimes. A backend must not require a supplied image to remain available after its synchronous publication operation returns unless it has independently retained the data needed for its continuing responsibilities.

Backends must not mutate caller-owned images.

The common interface does not expose hardware initialization, SPI, GPIO, controller commands, refresh mechanisms, GUI event loops, HTTP request handling, or network transports.

Backends do not perform content selection, reveal scheduling, artistic resource selection, image composition, destination overrides, or persistent operational-state updates.

Destination artisticoverrides are resolved before backend delivery according to [Presentation and Rendering](50-PRESENTATION_AND_RENDERING.md). Backend-specific visual conversion occurs at the boundary defined by the relevant backend contract.

Backend-specific pixel-format or orientation conversion is permitted only where explicitly defined by the relevant backend contract.

The `window` and `publish` backends receive completed RGB images without artistic or geometric modification. The Waveshare backend receives the fixed RGB output image and uses the shared hardware-independent palette converter before controller-specific transport operations.

For a `publish` destination, successful publication means that the complete destination dataset has passed its filesystem commit point and required verification. It does not mean an independent consumer is operating, has read the dataset, or has physically displayed its image.

For a directly attached display, successful publication means the backend's synchronous operation completed successfully according to its hardware or window contract. Software success does not itself prove visually correct physical output.

External delivery availability is distinct from successful resident publication.

Backend implementations belong to the built-in `refrain.display` package. Select them using stable configured type identifiers and a small explicit construction mechanism.

Import backend-specific dependencies only when the corresponding implementation is selected.

Do not introduce dynamic plugin discovery, entry-point registration, arbitrary Python-module configuration, or a general display plugin framework.

Hardware-independent application modules must remain importable without graphical desktop, GPIO, SPI, Waveshare driver, or independent HTTP-service dependencies.

Automated tests must cover:

- required destinations, valid IDs, global uniqueness, and invalid identifiers;
- supported backend types and capacity limits;
- one-instance/multiple-destination `publish` behavior;
- independent destination identity and acknowledgements despite shared images;
- compatible and incompatible prepared-image groups;
- exact output specification and image representation validation;
- independent construction, initialization, and failure reporting;
- rejection of unavailable or unimplemented backend types without substitution;
- absence of backend-specific routing assumptions;
- independent publication metadata finalization for filesystem destinations;
- no hardware or HTTP dependencies in hardware-independent imports.

## Resident ownership and authenticated control

The normal Refrain runtime exclusively owns its configured backend instances and protected display resources for the lifetime of the process.

Only one normal backend-owning Refrain process may own the per-user installation at a time.

A second normal invocation must fail immediately with an actionable diagnostic rather than constructing another runtime.

Installation-management operations that create, reset, purge, or otherwise mutate the standard installation use the same exclusive ownership rule. They must not proceed while the normal resident owns the installation.

One-shot control clients, including `refrain --refresh`, `refrain-viewer --list-destinations`, and viewer transient publication, do not acquire resident ownership. They communicate with the running normal resident.

Independent consumer services do not acquire the resident ownership lock. They are separately supervised readers of publication data and must be stopped by the operator before maintenance removes or replaces data they consume.

### Ownership lock

Use a small cross-platform abstraction built on operating-system exclusive locks available through standard-library facilities.

The normal runtime acquires the per-user installation lock non-blockingly before loading operational state or constructing configured backends.

Retain ownership throughout backend operation, publication coordination, and any deferred cleanup requiring protected resources.

Release ownership only after safe cleanup completes, or allow the operating system to release it when the process exits.

A persistent lock-file path may identify the lock, but file existence or a stored process ID must not determine current ownership or serve as stale-lock recovery.

`--initialize`, `--reset`, `--purge`, and other standard-installation mutation commands acquire the same lock non-blockingly for their operation.

Keep ownership metadata outside directory trees that reset or purge may remove.

A busy lock prevents the requested operation and produces an actionable diagnostic.

Lock behavior must work across processes rather than merely across threads.

The lock is scoped to the current user's standard Refrain installation, even when the normal runtime selects custom operational-state or publication paths.

The precise platform paths and installation ownership belong to [Installation and Service Operation](80-INSTALLATION_AND_SERVICE_OPERATION.md).

### Local control transport

The resident exposes a narrowly scoped, authenticated local-machine runtime-control interface.

Supported control transport targets are:

- Linux: Unix-domain local IPC.
- Windows: Local named-pipe IPC.

Use Python standard-library facilities behind one application-facing listener/client abstraction. `multiprocessing.connection.Listener` and `Client` may provide the transport.

Do not use TCP to unify the control implementation or expose the listener on a LAN interface.

No macOS runtime-control support or maintenance commitment is required.

The control interface is separate from filesystem publication and independently supervised HTTP consumers.

Its supported operations are:

- Destination discovery.
- Transient complete-image publication.
- Forced refresh of the currently required scheduled presentation.

It must not provide arbitrary filesystem access, backend-method invocation, configuration or content mutation, shell execution, a general remote-procedure interface, or privileged network administration.

Authenticate each connection using an unpredictable per-runtime credential available only through appropriately protected user-owned runtime metadata.

Local socket or pipe access alone is not sufficient authorization.

On Linux, protect credential and endpoint metadata with owner-only permissions, using mode `0600` for files inside a user-owned directory not writable by other users.

On Windows, use an owner-only protected DACL.

Store endpoint and credential metadata alongside the ownership-lock location.

Use a randomly named local Unix socket on Linux, falling back to the Linux abstract Unix socket namespace when the filesystem path is too long.

Use a randomly named local named pipe on Windows.

Clients must accept only the supported endpoint formats and locations.

A successful authenticated exchange establishes endpoint responsiveness. Metadata or socket-file existence does not prove that a resident process is alive.

After abnormal termination, the next lock-owning runtime may reconcile stale endpoint artifacts.

Remove endpoint and credential artifacts during orderly shutdown when safe.

### Protocol and limits

Use a bounded, explicitly versioned local protocol. The supported protocol version is `1`.

Use byte-oriented transport operations such as `send_bytes()` and `recv_bytes()`.

JSON may carry operation metadata, destination identities, output specifications, and publication results. Transfer complete images as separately bounded binary PNG payloads.

Transient destination associations include the audience reported by discovery. The resident validates that association against its current destination configuration before admission.

Do not use pickle-based `send()` or `recv()` for control payloads.

Reject unsupported versions or operations, invalid authentication, malformed or inconsistent metadata, invalid encodings, oversized payloads, and incomplete transfers before backend access.

The transport limits are:

| Property | Limit |
|---|---|
| Concurrent connections | 2 |
| JSON metadata per message | 64 KiB |
| Configured destination ID | 256 characters |
| Destinations per transient request | 64 |
| Image variants per transient request | 64 |
| Encoded image size | 32 MiB each |
| Aggregate encoded image size | 192 MiB per request |
| Image width | 1–3840 pixels |
| Image height | 1–2400 pixels |
| Decoded pixels per image | At most 9,216,000 |
| Backend error message | 1024 characters, with explicit truncation marker |

Transient image variants must be complete single-frame RGB PNGs.

Discovery streams individual destination records independently of transient destination-count limits.

Large refresh results may likewise be streamed without requiring a single oversized response message.

The same finished-image dimension limits apply to scheduled rendering. Configured dimensions exceeding those limits are invalid; there is no exemption for scheduled publication or refresh.

The client must receive and accept a metadata preflight response before transmitting image payloads.

A completed image transfer requires a separate commit message before coordinator admission.

Use the following transport deadlines:

- Authentication: 3 seconds.
- Complete request transfer: 60 seconds.
- Publication response delivery: 10 seconds.

Enforce deadlines by interrupting stalled transport I/O. During streamed discovery and responses, the relevant deadline resets as individual messages are sent.

An admitted backend publication has no client-side completion deadline. Its lifetime is governed by the resident coordinator, backend safety, and shutdown rules.

These transport limits are internal implementation constraints, not a promise of public protocol compatibility.

### Coordination and shutdown

Control handling must not block the application scheduler while images are transferred, validated, or published.

Use ordinary threading or equivalent standard-library facilities without introducing a separate asynchronous framework.

Refresh image preparation occurs outside the transport admission lock.

At admission, both transient and refresh guards must recheck shutdown state, listener state, client connection state, destination membership, output specifications, and relevant publication conditions.

The guard takes ownership of supplied images even when rejecting a request, so all image references are safely released.

An application-supplied transient callback may release its image references itself or transfer ownership to the admission guard. Ownership must not be ambiguous.

During shutdown, stop admitting new operations and enter a coordinator drain phase.

Admitted one-shot work remains resident-owned and may finish safely, including unattempted selected destinations. Stop recoverable retries and reject new work.

Handlers still preparing unadmitted requests must not indefinitely block backend cleanup.

Use the single foreground shutdown deadline defined in [Shutdown coordination](40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#shutdown-coordination). Retain exclusive installation ownership while handlers, backend workers, or deferred cleanup still require protected resources.

### Control validation

Hardware-independent tests using fake backends and controlled synchronization must cover:

- exclusive normal resident ownership and second-process rejection;
- installation-management exclusion;
- control-client operation without acquiring resident ownership;
- authentication and protected endpoint metadata;
- stale endpoint artifacts after abnormal termination;
- Linux and Windows local transports;
- unsupported protocol versions and malformed requests;
- metadata, image, count, and aggregate-size limits;
- staged transfer and metadata preflight;
- client disconnection before and after admission;
- destination reconfiguration between discovery and admission;
- streaming discovery and result responses;
- listener shutdown with active handlers;
- continued ownership of admitted work;
- bounded foreground shutdown and deferred cleanup.

These tests are hardware-independent. They do not establish physical e-paper correctness.

## Scheduled delivery and acknowledgement

The application coordinates normal scheduled publication to every configured destination still participating in publication.

The committed daily selection is shared across destinations. Compatible prepared output images may be shared, but destination publication state and acknowledgement remain independent.

Each destination has:

- Its configured identity and output specification.
- Its current participation and withdrawal status.
- Its latest required scheduled presentation identity.
- Its most recently acknowledged successful scheduled presentation identity.
- Its current delivery availability and applicable failure status.

A destination may remain configured but be intentionally withdrawn for the remainder of the resident runtime.

Withdrawal is distinct from backend failure or temporary unavailability.

Ordinary scheduled publication skips withdrawn destinations. Subsequent ordinary publication or refresh must not recreate or reactivate them.

Failed or unavailable destinations remain participating unless they have been intentionally withdrawn.

A backend instance may serve multiple destinations. Its publication and lifecycle operations must be serialized, including operations addressing different destinations.

Different backend instances may operate concurrently.

### Reveal progression and publication status

Operational state owns the committed global reveal stage. It does not certify physical presentation by any destination.

When a later reveal stage becomes required, the application coordinator durably advances operational reveal progress and synchronizes publication checkpoint visibility according to the persistence contract.

Reveal advancement must not wait for every destination to acknowledge successful presentation.

Backend workers must not independently modify authoritative reveal progression.

A failed or uncertain destination publication affects that destination's publication status and recovery, not committed literary selection, repetition history, global reveal progress, or successful publication to other destinations.

Normal scheduled updates use existing compatible prepared images rather than invoking rendering at each reveal event.

Meaningful scheduled publication requirements include:

- A new committed daily selection.
- A later required reveal stage.
- A changed required presentation variant.
- Startup recovery or a subsequent opportunity for a destination that has not accepted its currently required image.

Do not continuously refresh physical displays merely because the scheduler reevaluates unchanged state.

### Acknowledgement

The application coordinator owns scheduled publication acknowledgement, independently for each destination.

Backends receive complete images. They do not interpret selection revisions, reveal-stage indexes, or persistent operational state.

Identify each requested scheduled presentation with an opaque identity associated with its prepared image and required presentation.

That identity may be derived from committed selection revision and reveal stage, but backend implementations must not depend on its internal composition.

Associate each outstanding scheduled publication with the exact identity it was asked to publish.

A successful completion acknowledges only that destination and that requested identity.

Success for another destination does not satisfy its acknowledgement, even when the destinations share a backend instance or prepared image.

Completion of an older publication must not incorrectly acknowledge a newer required identity.

The coordinator distinguishes current desired scheduled presentation identity from the most recently acknowledged scheduled identity.

A destination already acknowledged for the currently required presentation should not repeat an expensive update solely because scheduling was reevaluated.

Publication acknowledgements are transient application state. Do not persist them in operational state, publication checkpoints, or separate durable files.

On restart, reconcile the configured destinations and currently required prepared images, then request publication to each available participating destination without relying on previous process-local acknowledgements.

Publication status must distinguish backend publication acceptance from external delivery availability. A `publish` destination can have a successfully committed filesystem dataset while no consumer service is running.

### Coalescing and backend execution

Use independent execution for each configured backend instance so slow or blocked operations do not delay scheduling or independent backend instances.

A dedicated worker per backend instance is the preferred implementation.

Use standard Python threading facilities rather than introducing an asynchronous application framework.

Keep backend publication synchronous at the backend interface.

For normal scheduled publication, maintain at most one pending latest desired presentation per configured destination.

When a newer stage or variant becomes required, replace that destination's obsolete unstarted scheduled request rather than accumulating intermediate updates.

Do not interrupt an active backend transfer unless that backend explicitly supports safe interruption.

When the active operation finishes, the destination must eventually receive the latest required scheduled image, not a replay of obsolete intermediate stages.

An active operation against one backend instance must not overlap a subsequent scheduled, transient, refresh, or lifecycle operation against that same instance.

Publication declaration order does not establish priority between independent backend instances.

Avoid unbounded image queues and unnecessary full-image duplication.

Maintain active image ownership until each backend's synchronous publication returns. Coordinate cache cleanup with active and pending image readers.

### Transient and information-view independence

Transient publication and forced refresh have separate admission and completion state. They are not replaceable scheduled-presentation requests.

An admitted transient publication does not alter the scheduled desired identity or clear, satisfy, or replace scheduled acknowledgement.

Literal last-displayed pixels may belong to a transient preview and do not determine whether the scheduled identity remains acknowledged.

A routine scheduler reevaluation of unchanged scheduled identity must not automatically replace a transient preview.

Startup information-view publication also preserves scheduled-presentation acknowledgement. Expired information-view jobs that have not started are discarded according to the application lifecycle contract.

Normal scheduled publication need not finish simultaneously at every destination.

One-shot transient push and forced refresh instead report completion for every admitted destination.

### Scheduled publication tests

Hardware-independent tests must cover:

- each destination receiving its matching output image;
- compatible image sharing without merged acknowledgements;
- distinct destinations sharing one backend instance;
- independent execution across backend instances;
- no overlapping backend-instance operations;
- scheduled publication identity and acknowledgement;
- replacement of obsolete pending scheduled stages;
- correct handling of older completions after a newer stage is required;
- independence of transient and scheduled acknowledgements;
- withdrawal distinct from failure and unavailable delivery;
- startup republishing without persisted acknowledgements;
- failure isolation and recovery without literary reselection;
- publication to `publish` destinations without requiring consumer availability;
- safe image ownership during cache cleanup and shutdown.

Validate the window and `publish` backends together on Windows and Linux without requiring physical e-paper hardware.

Validate concurrent Waveshare and another configured backend on the supported Raspberry Pi before claiming physical multi-backend operation.

## Transient admission and refresh

The resident's scheduled presentation is independent of one-shot transient publication.

Transient publication does not modify:

- Committed literary content or selection revision.
- Repetition or global history.
- Reveal progression or scheduling state.
- Shared publication checkpoints.
- Scheduled prepared-image artifacts.
- Current desired scheduled presentation identity.
- Scheduled publication acknowledgements.

The runtime-control interface supports destination discovery, transient complete-image publication, and forced refresh.

Discovery reports each configured destination's exact ID, audience, declared aspect ratio, requested resolution, participation, withdrawal, transient-publication capability, external delivery availability, and scheduled acceptance status.

For `publish` destinations, external delivery availability is unobserved and must be reported as `unknown`. A verified filesystem publication or successful resident acknowledgement does not establish whether an independent consumer is running, has retrieved the image, or has displayed it. Discovery must not infer consumer availability from publication success or require consumer liveness probing.

Destination discovery does not reserve targets or guarantee future availability.

### Transient target selection

A transient request selects either one exact destination ID or `@all`.

The literal ID `all` is an ordinary destination ID.

`@all` selects every currently participating configured destination except those intentionally withdrawn.

Failed and unavailable destinations remain included unless withdrawn.

An explicit request naming a withdrawn destination is rejected.

A request selecting no participating destinations must produce a no-target failure rather than success.

Transient-publication capability is a generic destination property. Clients must not infer it from destination names or backend types.

A directly selected destination without transient support is rejected before rendering or publication.

If `@all` includes any participating destination without transient support, reject the complete request. Do not silently omit the unsupported destination.

### Complete-request validation

Before backend access, the resident validates:

- The request's complete selected destination set.
- Current destination identity and participation.
- Applicable transient capability.
- Current output specifications.
- Current destination audiences matching the submitted discovery associations.
- Exact image-variant association.
- Image dimensions and encoded transport limits.
- Required output representation.
- Safe admission conditions for every selected destination and backend instance.

A destination removed or reconfigured after client discovery is rejected rather than adapted.

The runtime must not substitute another destination or resize, crop, pad, recolor, or otherwise adapt submitted finished images.

Finished transient images are already destination-ready and bypass scheduled artistic overrides.

Admission is atomic across the complete selected destination set.

If any selected destination or shared backend instance cannot safely accept the operation immediately, reject the entire request as busy before any requested backend publication begins.

Do not queue an external request while waiting for scheduled backend activity to finish.

Normal scheduled work has priority until a transient request is admitted.

After admission, the resident owns the entire fixed destination set.

A newer scheduled presentation may follow the admitted transient operation, subject to any active all-day hold. It must not interrupt, replace, or overlap the admitted transient operation on the same backend instance.

Only one transient request may be in transfer, validation, or admitted publication at a time.

A second transient request is rejected as busy until the active transient operation reaches a terminal result.

Different backend instances may progress concurrently within one admitted transient operation while preserving per-instance serialization.

### All-day transient holds

An all-day transient request temporarily suppresses ordinary scheduled publication to destinations where the request successfully publishes an image. It uses the existing transient-publication path and completed transient metadata form. It does not create a scheduled publication or alter committed content, repetition or global history, reveal progression, publication checkpoints, prepared images, desired scheduled identities, or scheduled acknowledgements.

The resident owns at most one process-local all-day hold per destination. Each hold records the logical display date determined from host-local time and the configured day start when its request was admitted. Holds do not retain image bytes and are not persisted.

A hold remains effective only while its recorded logical display date is current. When the current logical display date differs, clear the hold without reactivating it if the clock later returns to the earlier date. Resident restart or shutdown discards all holds.

An all-day request follows the existing complete-request validation, atomic admission, backend serialization, completion, and failure-isolation requirements. Its hold intent must be carried explicitly in the validated transient request. An omitted hold intent means an ordinary transient push; invalid values are rejected. The internal protocol remains version 1.

At admission, temporarily protect the request's destinations against scheduled publication until their transient publication results are resolved. Prevent unstarted scheduled work and subsequently required scheduled updates from overwriting an admitted all-day request. Do not interrupt already active backend operations or relax existing busy-admission and backend-serialization requirements.

For each destination with a known successful all-day publication, establish or replace its hold for the admission display date, provided that date remains current. A failed or uncertain publication does not establish a new hold or clear an existing successful hold. Remove provisional protection after the result, retaining the established hold when applicable. If no hold remains, ordinary scheduled-delivery eligibility resumes.

A subsequent ordinary transient push clears an existing hold only for a destination where that push successfully publishes its image. Rejected, failed, and uncertain destination publications preserve prior holds. Clearing a hold does not force scheduled restoration or guarantee continued display of the ordinary transient image. Existing scheduled-publication, acknowledgement, and retry behavior resumes.

While a hold is effective, suppress scheduled publication and recoverable scheduled-publication retries to that destination, including unstarted pending scheduled requests. Continue computing the required scheduled presentation, advancing global reveal progress, preparing images, and maintaining scheduled identities independently of the hold. Do not mark suppressed scheduled work as successfully acknowledged.

Expiration resumes normal scheduled-delivery eligibility and allows publication of the latest required presentation when available. Do not replay intermediate reveal stages that were suppressed during the hold.

An admitted `refrain --refresh` clears all process-local all-day holds before executing its forced scheduled publication. A rejected or stale refresh leaves all holds unchanged. Once refresh is admitted, later backend failure does not restore the cleared holds.

A hold does not alter destination participation, withdrawal, backend availability, or another destination's publication behavior. Destinations sharing a backend instance retain the existing operation-serialization requirements.

A lost client connection or terminal acknowledgement does not cancel an admitted request or alter resident-owned publication results. Holds follow known resident publication outcomes, not the client's ability to receive confirmation.

Holds require no new persistent document, publication metadata shape, public destination-discovery field, or retained image store.

### Forced scheduled refresh

`refrain --refresh` is a one-shot request for the resident's currently required scheduled presentation.

It applies to every configured destination still participating in scheduled publication, excluding intentionally withdrawn destinations.

Refresh is not historical restoration. It uses the currently required reveal stage and presentation, including changes occurring after a transient preview.

A destination's lack of transient-publication capability does not exclude it from refresh.

Refresh uses a forced scheduled-publication operation with a fixed admitted destination set.

It is rejected as busy rather than queued when immediate safe admission is unavailable for any participating destination or its shared backend instance.

A request with no participating destinations must report a no-target failure.

Refresh preparation occurs outside the transport admission lock.

Immediately before admission, the resident must recheck the complete currently required scheduled presentation identity against the identity and variants prepared for the refresh.

This check is atomic with admission.

If selection, reveal stage, required effective presentation, or destination requirements changed during preparation, reject the stale refresh rather than admitting an obsolete presentation.

Do not silently substitute newly required images after admission or treat an obsolete prepared identity as current.

A rejected stale refresh must not publish any of its prepared images.

The caller may issue a new refresh request after the runtime has established its current scheduled presentation. The resident must not automatically replay an unconfirmed or stale request.

Once admitted, refresh remains resident-owned even if its client disconnects.

An admitted refresh is not replaced by later scheduling changes. Newly required scheduled work may follow it safely.

Refresh must not reset or recreate intentionally withdrawn destinations.

### Completion and uncertainty

A one-shot request succeeds only when every admitted destination completes its publication operation successfully.

A failure at one destination makes the overall request unsuccessful but does not roll back successful publications at other destinations.

A rejection before admission means no requested backend publication began.

After admission, client disconnection does not cancel, preempt, or roll back publication.

If the terminal acknowledgement is lost, the client must report an unconfirmed outcome. It cannot conclude that no publication occurred or that every destination succeeded or failed.

Do not automatically replay a request because its terminal acknowledgement was lost.

The resident must preserve per-destination outcomes where available. Do not collapse partial success into a false all-success or all-failure report.

The public client reports useful progress before waiting for potentially slow publication.

Publication across destinations is not transactional and cannot be rolled back.

### Transient and refresh tests

Tests using controlled concurrent requests and fake backends must cover:

- exact destination selection and `@all`;
- literal destination ID `all`;
- intentionally withdrawn, unavailable, failed, and unsupported destinations;
- no-target failures;
- complete-request validation before backend access;
- destination, audience, or geometry changes after discovery, with complete-request rejection before backend publication;
- atomic busy rejection with no partial publication;
- shared-backend-instance admission conflicts;
- one active transient request at a time;
- normal scheduled work receiving priority before admission;
- fixed membership and completion after admission;
- client disconnection and lost terminal acknowledgements;
- truthful per-destination results;
- absence of automatic replay and rollback;
- refresh including destinations without transient capability;
- refresh use of the latest required reveal stage;
- stale scheduled identity rejected atomically at refresh admission;
- scheduled work following admitted one-shot operations;
- absence of mutation to committed state, checkpoints, history, or scheduled acknowledgements.
- all-day hold establishment, renewal, expiration, and resident-restart clearing;
- scheduled reveal progression and image preparation while per-destination delivery is held;
- suppression of pending and newly required scheduled publications during admission and active holds;
- successful ordinary pushes clearing only their destinations' holds without forced restoration;
- rejected, failed, uncertain, and partially successful pushes preserving or changing holds according to known per-destination outcomes;
- admitted refresh clearing all holds, including when subsequent delivery fails, and rejected refresh preserving them;
- logical-date changes during an admitted push and safe resumption of current scheduled publication;
- independent holds for destinations sharing one backend instance;
- no mutation of authoritative state, histories, checkpoints, scheduled acknowledgements, or publication metadata forms.

## Transient transfer and staging

Use the existing application-owned publication coordinator for scheduled, transient, information-view, and forced-refresh publication.

Do not construct a second set of backend instances or a separate transient publication pipeline that bypasses ordinary lifecycle ownership.

Keep the application scheduler responsive while receiving and validating transient images.

Request-scoped temporary storage is used for complete encoded PNG variants so the runtime does not retain every decoded image in memory simultaneously.

The staging directory belongs to the active transient request and is located adjacent to runtime endpoint metadata.

Validate the complete request's bounded metadata and image count before accepting image payloads.

For each transferred variant:

1. Validate encoded size limits before full decoding.
2. Inspect image dimensions and representation safely.
3. Reject unsupported dimensions, unsafe or malformed encoding, or incorrect image mode.
4. Decode only as needed to validate the complete single-frame RGB PNG.
5. Release the decoded validation image while retaining the validated encoded PNG in staging.

The maximum decoded image is 3840 × 2400 pixels, with width and height limits applied independently.

The aggregate encoded request limit and per-image size limit remain authoritative even when several destinations reuse one variant.

Do not decode a complete collection of transferred images simultaneously merely to perform validation.

A destination may reuse the same validated staged PNG when its output specification matches another selected destination.

Backend workers may decode required staged variants on demand. Release decoded images after their synchronous publication operations finish.

Staging is not authoritative operational state, a publication checkpoint, a scheduled prepared-image cache, or a reusable historical publication store.

Remove staging after terminal completion or when a pre-admission request is abandoned, rejected, disconnected, or times out.

After acquiring exclusive resident ownership and before accepting control requests, reconcile stale transient staging left by an abnormal prior runtime.

Never remove staging still owned by an active transient operation or backend worker.

An admitted operation must retain its referenced staging and image resources until its selected backend publications have completed or resources can otherwise be released safely.

Do not confuse client connection lifetime with admitted operation lifetime.

Tests must cover encoded and decoded limits, malformed files, incomplete transfers, preflight rejection, sequential decoding, staged variant reuse, cleanup after failures, startup stale-staging reconciliation, and resource retention during blocked backend publications.

## Failure handling and retries

Backend failures must be isolated to the actual affected destination or shared backend instance.

Failure to initialize, update, or recover one independent backend instance must not prevent other functional instances from presenting their required images.

When multiple named destinations share one backend instance, an instance-wide failure may affect all dependent destinations. Do not report such a failure as limited to only the destination whose operation first exposed it.

Conversely, a destination-specific publication failure must not falsely mark another independent destination or backend instance as failed.

Classify failures sufficiently to distinguish:

- Initialization failure.
- Recoverable publication failure.
- Nonrecoverable publication failure.
- Unexpected backend or programming failure.
- Delivery unavailability independent of publication.
- Uncertain publication outcome.
- Intentional destination withdrawal.

A known successful publication must not be inferred from an uncertain result.

`DisplayBackendError.recoverable` defaults to `true`.

Only errors explicitly classified as recoverable may enter automatic retry.

Unexpected exceptions during backend construction or update are logged as programming or backend failures and terminally disable the affected destination or shared instance as appropriate.

A nonrecoverable failure must safely release or disable the affected backend instance without overlapping any active operation.

Initialization failures must be reported independently. Do not assume an instance that failed construction can be retried through its normal update interface.

### Bounded retries

Each recoverable publication or initialization recovery opportunity permits at most five total attempts.

Retry delays begin at one second, double exponentially, and are capped at 60 seconds.

After attempts are exhausted, stop retrying that failure until a subsequent applicable scheduled publication, refresh, or transient request provides another opportunity.

Do not retry unrecoverable errors or intentionally withdrawn destinations automatically.

Retry work must not indefinitely block the scheduler, independent backend instances, or recognition of newer presentation requirements.

Where recovery requires replacing a backend instance, coordinate cleanup and initialization without overlapping active operations on that instance.

Backend recovery must not modify committed literary selection, revision, repetition history, reveal progression, or publication checkpoints.

A failed filesystem publication must preserve the previously committed dataset when possible according to [Filesystem Publication and Consumers](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#dataset-commit-and-consumer-recovery).

A failed independent HTTP consumer does not constitute a resident `publish` backend failure when the destination dataset was successfully committed.

When all destinations become unavailable, failed, or intentionally withdrawn, report the condition and continue resident scheduling, persistence, preparation, and runtime-control responsibilities.

Total delivery unavailability alone is not fatal.

Hardware validation must distinguish successful driver calls from visibly correct panel output.

Automated tests must cover bounded retries, backoff, exhaustion, recovery opportunities, unexpected exceptions, correct shared-instance failure scope, no overlapping cleanup, and continued operation after total delivery loss.

## Desktop window lifecycle and withdrawal

The `window` backend displays complete images in a graphical desktop window on Windows and supported graphical Linux environments.

Its image-display area matches the supplied image's native pixel dimensions.

A later update with different dimensions resizes the display area without resampling, cropping, or letterboxing the image.

The backend owns one persistent window and its GUI event loop.

It must remain responsive between synchronous image updates, including while the main application is waiting for scheduling events.

Use the platform's Tk support with Pillow's `ImageTk` adapter.

Import GUI dependencies only when constructing the window backend.

The application scheduler and other backends must not depend on a graphical environment.

Run the Tk event loop on a backend-owned GUI thread.

Create, use, and destroy all Tk interpreter objects on that same thread.

Before the GUI thread exits, destroy the window and release all interpreter-owning references, including widgets and active Tk images.

Queued commands and reported errors must not retain Tk owners or GUI traceback frames in caller-thread cleanup.

A successful `close()` must join only after GUI-owned cleanup completes.

The backend must preserve caller-owned image data while replacing the displayed image.

### User closure and withdrawal

Closing the window through the window manager intentionally withdraws its configured destination for the remainder of the resident runtime.

The withdrawn window must not be recreated by scheduled updates, transient `@all`, or `refrain --refresh`.

An explicitly targeted transient request to that withdrawn destination is rejected.

A new normal runtime may create the window again.

Distinguish user-requested closure from application-driven `close()` and unexpected GUI failure.

Notify the publication coordinator promptly of intentional user closure.

Ordinary application shutdown must not emit an intentional-withdrawal notification.

Unexpected GUI or backend failures remain failures or unavailability, not intentional withdrawal.

Report unavailable graphical environments with actionable guidance to install Tk support and start an appropriate graphical session.

The window backend is a development and presentation destination, not an independent image renderer.

Tests must cover persistent updates, native dimensions, GUI-thread ownership, cleanup, intentional withdrawal, rejected subsequent publication, and independent operation of other backends.

Mocked GUI behavior does not establish validation in an actual graphical session.

## Waveshare conversion and controller lifecycle

The supported Waveshare 13.3-inch e-Paper HAT+ (E) destination has a fixed output specification of 4:3 at 1600 × 1200 pixels.

The backend receives the complete matching RGB output image.

It must reject any image whose dimensions differ from 1600 × 1200. It must not resize, crop, pad, or stretch an image to fit.

### Palette conversion

Use the shared hardware-independent RGB-to-seven-index converter defined in [Destination visual conversion](50-PRESENTATION_AND_RENDERING.md#destination-visual-conversion).

The vendored driver's active palette indexes are:

1. Black.
2. White.
3. Yellow.
4. Red.
5. Black.
6. Blue.
7. Green.

Preserve the duplicate black entry.

Do not substitute the commented alternative palette ordering present in the vendored source.

The shared converter determines deterministic palette indexes using the same implementation as viewer inspection and export.

Quantize the RGB image exactly once.

The dithering algorithm is implementation-defined but must be shared between viewer and runtime conversion.

Do not independently quantize the image inside the physical driver or backend after shared conversion.

Preserve the caller-owned RGB image.

The backend passes the resulting palette indexes to the driver.

The driver rotates the indexed raster to controller orientation without changing palette indexes and packs adjacent indexes into its transport-specific 4-bit buffer without requantization.

Prepare the complete buffer before initializing the controller. The packed buffer must contain exactly 960,000 elements.

Tests must verify index ordering, duplicate-black preservation, identical viewer/runtime conversion, unchanged RGB input, one quantization pass, rotation and packing without recoloring, and the required buffer size.

### Controller lifecycle

Each valid full-frame update:

1. Initializes the controller.
2. Transfers the complete packed image.
3. Performs the required refresh.
4. Returns the controller to sleep.

Do not clear the panel before each update or during shutdown.

`close()` must be repeatable and must put the controller to sleep only when an operation has left it active.

Use the Waveshare Python implementation appropriate to the supported panel.

Keep the imported vendor-driver surface as narrow as practical.

Do not include drivers for unrelated Waveshare models merely because they are distributed with the selected vendor package.

Record the provenance, revision or version, and license of incorporated vendor code.

Modifications to vendor code must be reviewable and justified by understood hardware requirements.

The physical backend uses Linux SPI and GPIO character-device facilities through optional hardware dependencies.

Configure the required SPI overlay, `/dev/spidev0.0`, GPIO lines, and service-identity permissions according to the deployment requirements.

Run under the minimum practical privileges rather than requiring root.

Hardware transport dependencies must be loaded lazily.

Only the physical Waveshare backend depends on its vendor driver, SPI, and GPIO facilities.

The converter, viewer, scheduler, renderer, persistence, and other backends must remain usable without those dependencies.

The backend owns hardware initialization, complete-frame transfer, controller sleep, and cleanup.

Use supported driver lifecycle operations rather than assuming a sleeping controller can resume without initialization.

Never invoke overlapping update and cleanup operations against the controller.

If an update remains active during shutdown, defer cleanup until that operation finishes safely or the process exits.

The shared backend interface must not require the application coordinator to issue hardware-specific initialization or sleep commands.

### Hardware validation

Validate the actual supported Waveshare panel for:

- controller initialization and repeated full-frame transfers;
- exact 1600 × 1200 input acceptance and rejection of other dimensions;
- complete packed image transfer;
- correct physical orientation;
- representative palette and dithering output;
- consistent viewer preview and physical-panel conversion;
- controller sleep and subsequent initialization;
- retention of the displayed image after sleep;
- application restart;
- clean shutdown during ordinary operation;
- recovery after interrupted or failed presentation where practical;
- independent operation alongside another configured backend.

Monitor rendering and software tests do not establish physical colorimetric correctness.

Compare palette and dithering structure, accounting for differences between monitor colors and e-paper pigments.

Report the tested hardware, operating-system environment, and relevant limitations.

A working vendor demonstration alone does not prove reliable unattended operation.

Do not claim another Raspberry Pi model is supported solely because it exposes compatible GPIO connections.

## Retained content and delivery failures

E-paper retains its displayed image without continuous power.

Refrain should preserve useful displayed content across temporary application, backend, and hardware failures when safe.

Do not clear a physical display merely because a recoverable software error occurred, a publication checkpoint requires recovery, or another destination failed.

An incomplete or failed replacement must not intentionally destroy a healthy existing e-paper image.

Filesystem publication preserves its last verified complete dataset according to the manifest commit and recovery contract. The resident does not keep a separate authoritative network-image history.

Network consumers and physical receiving devices are responsible for retention of already displayed content when publication or connectivity is unavailable.

Backend delivery failures must not change committed literary selection, repetition history, reveal progression, or valid publication checkpoints.

Recovery restores the current required presentation without relying on the assumption that every destination successfully displayed every earlier reveal stage.