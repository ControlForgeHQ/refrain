# Destinations and Runtime Control

## Backend contracts and destination validation

Refrain presents complete rendered images through narrow, hardware-independent display backend interfaces.

A display backend provides two operations:

- A destination-aware publication operation that presents a complete Pillow image through one selected configured destination. The contract must identify the destination generically; an image-only operation is insufficient when one backend instance owns multiple destinations. The contract does not prescribe a Python method signature.
- `close()` releases resources owned by the backend.

Refrain validates a required nonempty top-level destination sequence before initializing hardware or services. Each destination has an explicit, globally unique URL-safe ID and one backend type. A backend implementation declares a side-effect-free maximum destination capacity; the window and Waveshare backends support one destination each, while image-server supports multiple destinations. Configuring more destinations than a backend's capacity is an error.

Backend selection occurs at application startup and does not require modifications to application code or replacement of installed modules.

Version 0.1 provides three built-in display backends:

- `window`: Presents complete images in a graphical desktop window.
- `waveshare-13in3-e`: Presents complete images on the supported Waveshare 13.3-inch e-Paper HAT+ (E).
- `image-server`: Serves one or more named prepared output images to network clients through a read-only HTTP service.

Each configured destination uses its explicit ID unchanged at runtime and receives the complete prepared output image matching its resolved output specification for each reveal stage. Destinations may share an image when their specifications are identical; destinations with different specifications receive different variants. Sharing an output specification or image does not merge destination identity, publication, or acknowledgement. One backend instance may manage multiple destinations. The coordinator and runtime-control clients use generic destination routing and contain no backend-specific routing rules or ID-spelling conventions. Backend selection does not introduce independent content selection, reveal scheduling, composition, or presentation policy.

The Waveshare backend owns model-specific hardware operations, including:

- device initialization;
- transport packing and transfer;
- full-screen refresh;
- controller sleep or release where supported;
- hardware error reporting;
- cleanup.

The image-server backend owns one optional HTTP service that exposes the most recently accepted image for each configured destination. Its publication and lifecycle responsibilities are described under [Integrated HTTP delivery](#integrated-http-delivery).

The common interface does not expose hardware-specific initialization, SPI, GPIO, controller commands, refresh mechanisms, or network transport operations. The Waveshare backend owns transfer packing, refresh, sleep, and cleanup, but not visual palette quantization, image resizing, or literary composition. The window backend displays at native pixel size, and the image-server backend exposes each prepared output without resizing or cropping. No backend may mutate the image supplied by the coordinator. A backend unable to perform its required operation reports a backend-specific publication failure; that failure does not alter any output specification, persistent state, selection, or publication to other destinations.

The image-server backend serves each destination's matching prepared variant with its dimensions and pixel content unchanged. Backend adaptation policies and their visual consequences belong to the relevant backend contract, not to the core renderer.

A completed destination publication operation indicates that the backend accepted the complete image according to its contract. For image-server, this means a complete PNG representation and ETag are retained in memory; it does not mean that an HTTP listener is operating or that a client retrieved or displayed it. Destination delivery availability is reported separately from successful publication.

Failures and uncertain hardware outcomes must remain distinguishable where the underlying implementation permits.

Display backends must not perform quotation selection, reveal scheduling, image preparation, artistic overrides, or persistent-state updates. Destination overrides are applied to the canonical presentation before rendering; backends deliver the resulting complete output image and may perform only their explicitly documented hardware-format or orientation conversion.

Backend implementations are built-in application components. Version 0.1 does not define a general display plugin system.

Validate destination IDs for required presence, URL-safe ASCII syntax, runtime-control length, and global uniqueness before initializing any backend. Backend implementations declare their maximum destination capacity through side-effect-free metadata so invalid counts are rejected before hardware or service initialization. Preserve backend grouping where one instance owns shared resources for multiple destinations.

Provide a small synchronous display backend interface whose publication operation accepts a complete Pillow image and identifies one selected configured destination. The destination may be passed explicitly or represented by an equivalent destination-bound abstraction; an image-only `update(image)` operation is not sufficient for a backend that owns multiple destinations. The contract is generic and does not prescribe a particular Python method signature.

The interface operates on complete Pillow images rather than artifact paths.

Callers own the supplied images and their lifetimes. A backend must not require an image to remain available after its synchronous publication operation returns unless it has independently retained the data it requires.

Keep the interface independent of Waveshare, SPI, GPIO, desktop GUI libraries, selection, persistence, and reveal scheduling.

Implement display backends in a dedicated `refrain.display` package.

Use a small explicit selection mechanism for built-in implementations. Select backends by stable configuration identifiers rather than Python module paths.

Do not introduce dynamic plugin discovery, entry-point registration, generalized dependency injection, or a display plugin framework.

Construct the configured display backends at application startup.

Use explicit mappings or conditional construction for supported built-in implementations. Import backend-specific dependencies only when the corresponding implementation is selected.

The configuration must contain at least one destination. Destination IDs must be globally unique. Multiple destinations may use the same backend type when that type supports them; enforce each type's declared destination capacity before constructing or initializing its backend. A destination declaration is not itself a backend instance: destinations supported by one shared backend use that instance and its lifecycle.

`window` and `waveshare-13in3-e` each support one configured destination. The current integrated `image-server` and filesystem `publish` backends support multiple destinations through one shared backend instance. These explicit capacities do not imply a generic backend-instantiation or plugin framework.

A recognized but unimplemented backend must produce an actionable diagnostic.

Do not silently substitute another backend when construction or initialization fails.

Keep configuration validation separate from actual hardware availability checks.

Backend construction and initialization failures must be isolated so that an unavailable destination does not prevent other configured destinations from operating.

## Resident ownership and authenticated control

A normal Refrain runtime is the sole owner of its configured backend instances and physical display resources for the lifetime of the process. Only one backend-owning Refrain process may own the per-user installation at a time. A second normal invocation or a concurrent `--demo` invocation fails immediately with an actionable diagnostic rather than starting another runtime. Demo is a standalone backend-owning mode under the same exclusive ownership rule; it does not serve runtime-control requests, and concurrent demo operation is not supported.

Installation-management commands that create, reset, purge, or otherwise mutate the standard installation use the same exclusive-ownership rule and must fail rather than mutate files while a resident runtime owns them. Independent consumer services do not acquire this lock; stop them through their operating-system service facilities before maintenance removes or replaces their installation or publication data. One-shot control clients, including `refrain --refresh`, do not acquire resident ownership; they communicate with the already-running normal runtime.

External tools publishing through the runtime must never construct, initialize, or directly access configured backends. The resident normal runtime exposes the narrowly scoped local runtime-control operations defined under [Transient admission and refresh](#transient-admission-and-refresh). The interface is not a network administration API and does not expose the separate `image-server` service as a control channel.

Use a small cross-platform ownership abstraction built on standard-library access to operating-system exclusive locks. Normal runtime and `--demo` acquire the per-user Refrain ownership lock non-blockingly before loading operational state or constructing display backends, and retain it for the complete backend-owning process lifetime. Release it during orderly shutdown; rely on the operating system to release it when a process exits abnormally. A persistent lock-file path may identify the lock, but file existence or a stored PID must never determine ownership or be used as stale-lock recovery.

`--initialize`, `--reset`, `--purge`, and any other command that creates or mutates the standard installation acquire the same lock non-blockingly for the duration of their operation. Keep the lock metadata outside trees reset or purge can remove. A busy lock produces an actionable diagnostic and no operation proceeds. A second normal or demo process likewise fails before it opens configured backends. One-shot control clients, including `refrain --refresh`, do not acquire this ownership lock.

Keep platform-specific locking details behind the small abstraction, using standard-library and operating-system facilities rather than a lock server or process-management dependency. Locking must work across processes, not merely threads. Ownership metadata and lock behavior must be scoped to the current user's standard Refrain installation even when runtime configuration selects custom state paths.

Use Python standard-library local IPC behind one application-facing client/listener abstraction: Unix-domain local IPC on Linux and Windows named-pipe IPC on Windows. `multiprocessing.connection.Listener` and `Client` may supply these transports. Do not use TCP to unify the implementation or expose a control listener on a LAN address. The `image-server` HTTP backend remains separate and is not the control transport.

Authenticate each connection with a per-runtime unpredictable credential available only through appropriately protected per-user runtime metadata. Do not treat a local socket or pipe alone as authorization. `--demo` is a standalone backend-owning mode and does not provide the runtime-control listener.

Restrict runtime metadata and credential files to the owning user using platform-appropriate permissions. Remove endpoint and credential artifacts during orderly shutdown. After abnormal exit, tolerate stale filesystem artifacts: their existence does not establish that a runtime is alive. Acquire the process ownership lock before reconciling or replacing stale endpoint metadata, and use a successful authenticated IPC connection—not the presence of a path or credential file—to establish that a control endpoint is responsive.

Use a bounded, explicitly versioned protocol over byte-oriented operations such as `send_bytes()` and `recv_bytes()`. JSON may carry operation metadata and output specifications. Transfer completed images as separately bounded binary payloads rather than embedding them in JSON. Do not use pickle-based `send()` or `recv()` for control payloads. Apply explicit limits to message size, image dimensions, image count, and selected destinations. Reject unknown versions or operations, malformed metadata, unsupported encodings, oversized or inconsistent payloads, and incomplete requests before they can trigger backend access.

The internal control protocol is version 1. Its runtime-scoped credential and endpoint are stored alongside the ownership-lock location, in metadata supplied to the listener by the application. Unix metadata is created with mode `0600` in a user-owned directory that is not writable by other users; Windows metadata is created with a protected owner-only DACL. Unix uses a randomly named socket in the metadata directory, falling back to Linux's abstract Unix socket namespace if the filesystem path is too long. Windows uses a randomly named local pipe. Clients accept only these endpoint formats and locations. A successful authenticated exchange, not metadata existence, establishes availability.

The transport accepts at most two concurrent connections and 64 KiB of JSON metadata per message. Canonical runtime destination identifiers are limited to 256 characters. Discovery streams individual destination records independently of transient request limits; large refresh results are also streamed. Backend error messages in publication results are truncated with an explicit marker to at most 1024 characters. A transient request selects at most 64 destinations and transfers at most 64 single-frame RGB PNG variants. Each encoded image is limited to 32 MiB, with 192 MiB total per request. Transient images are at most 3840 pixels wide, 2400 pixels high, and 9,216,000 pixels each. The request-scoped staging directory is adjacent to runtime endpoint metadata. Larger configured outputs remain discoverable but are reported as not supporting transient publication; scheduled publication and resident-owned refresh are unaffected by image-transfer limits. The client requests and waits for a metadata preflight response before sending image payloads, so an early rejection is reported without racing a payload transfer. Authentication has a three-second deadline, complete requests have a 60-second deadline, and publication response delivery has a 10-second deadline, enforced by interrupting stalled transport I/O. During streamed discovery and publication responses these deadlines reset as individual messages are sent. Admitted publications have no client completion timeout. A completed transfer requires a separate commit message before coordinator admission. Listener shutdown reports any still-active handler threads so installation ownership can remain held until they finish. These are implementation limits, not a public compatibility guarantee.

Refresh preparation runs outside the transport admission lock. After preparation, the resident refresh callback passes its scheduled identity and images to the supplied admission guard. Both transient and refresh admission guards check the application shutdown event, listener stop state, and connection state before entering the coordinator, and take ownership of images even on rejection. An optional application-supplied transient callback runs outside the transport lock and takes ownership of its supplied images; it may either release them itself or pass them to its supplied admission guard. During shutdown, put the coordinator into a drain phase that rejects new work and stops recoverable retries while allowing unattempted destinations of admitted operations to run. Wait for admitted one-shot operations to reach terminal outcomes before closing the coordinator; handlers still preparing unadmitted requests must not prevent backend cleanup. Keep foreground shutdown bounded and retain ownership until all control handlers and deferred cleanup finish.

Add hardware-independent tests using fake backends and controlled synchronization. Cover:

- exclusive normal and demo ownership, rejection of a second process and concurrent demo, release on shutdown, installation-management exclusion, and control-client behavior with no resident runtime;
- authenticated local connections, malformed, unsupported, oversized, and inconsistent protocol requests, and rejection before backend access;
- discovery of exact configured destination IDs and output specifications, including single-destination and shared multi-destination backends, and rejection when a destination or specification changes after discovery;
- exact output-dimension validation, missing image variants, and shared image use for destinations with identical specifications;
- atomic busy rejection for one destination and for `@all`, no partial publication after failed admission, independent operation on different backend instances, and serialization on the same instance;
- per-destination scheduled acknowledgement and coalescing, including distinct acknowledgements for named destinations with identical output specifications;
- scheduled desired state remaining authoritative after an admitted transient push, transient completion remaining separate from scheduled acknowledgement, no replacement of admitted transient work by later scheduling, and no repaint on routine reevaluation of an unchanged scheduled identity;
- no push mutation of selection, revision, global or repetition history, reveal progression, scheduling state, or prepared artifacts;
- refresh republication of the currently scheduled presentation to every participating configured destination, including destinations without transient-publication capability and the current reveal stage rather than pre-push pixels, plus synchronous push/refresh completion and visible CLI progress;
- client disconnection before and after admission, continued ownership of admitted work, safe loss of terminal-response delivery, unconfirmed outcomes, and no automatic publication replay;

These tests establish software behavior only. Actual Waveshare validation must confirm that a preview is published by the already-running Refrain process, does not overlap another physical refresh, remains displayed after push completion, is replaced by `refrain --refresh`, and leaves the controller and normal runtime usable afterward.

## Scheduled delivery and acknowledgement

The application should avoid unnecessary physical refreshes when the required prepared image has not changed.

The display scheduler and backend remain independent of the renderer.

Normal scheduled updates select among prepared images rather than invoking image composition.

For normal scheduled publication, Refrain coordinates publication of the current prepared presentation to every participating configured destination. A backend may manage multiple destinations through one backend instance; each destination has independent identity, geometry, publication state, and acknowledgement. The independent scheduling, coalescing, and acknowledgement behavior in this section applies to normal scheduled publication; transient push and refresh use the admission and completion rules in [Transient admission and refresh](#transient-admission-and-refresh).

The single committed daily selection remains shared by all destinations, while prepared images are shared only within compatible preparation groups whose effective presentation requirements match. Only the selection is authoritative.

For normal scheduled publication, participating destinations are tracked independently. A destination may remain configured but be intentionally withdrawn from publication for the remainder of the resident runtime. Withdrawal is distinct from failure or unavailability: ordinary scheduled publication skips a withdrawn destination, and later publication requests do not restore it. A failure or unavailable backend does not constitute withdrawal. A slow or failed operation on one backend instance must not delay publication through another backend instance or prevent subsequent scheduling evaluation. Destinations sharing one backend instance share its lifecycle and serialization.

An active publication to one backend instance must not overlap another publication to that instance, including operations for different named destinations. Operations to different backend instances may proceed concurrently.

The persisted highest reveal stage represents the application's globally reached reveal progression. It does not certify successful presentation by any particular backend.

Reveal progression advances monotonically when a later stage becomes required and is durably recorded independently of backend publication outcomes.

The application coordinator maintains independent acknowledgement of the scheduled presentation identity for each participating destination during the application lifetime. It tracks transient operation completion separately from this scheduled acknowledgement. Successful transient publication must not clear or replace the scheduled acknowledgement used to suppress redundant scheduled updates.

For normal scheduled publication, the application must distinguish the currently required variant for each participating destination from the scheduled identity last acknowledged there. A successful scheduled update to one destination does not establish successful publication to another. Literal last-published pixels may instead be a transient preview and do not determine whether the scheduled identity remains acknowledged.

Destination discovery exposes configured identity, output specification, transient-publication capability, participation, withdrawal, external delivery availability, and whether the current scheduled image was accepted. A destination may report unavailable delivery while its publication was accepted successfully. Withdrawal is runtime-local and is not a general dynamic enable/disable or configuration-mutation facility.

Publication tracking is owned by the application coordinator, not by individual display backends. Backends receive complete images and do not interpret selection revisions, reveal stages, or persistent operational state.

Publication status is transient and does not require separate durable storage. After application restart, the coordinator supplies the currently required prepared image to each available destination.

If a new scheduled presentation or variant becomes required while a backend instance is busy, each affected destination must eventually receive its latest required image rather than replaying obsolete intermediate scheduled updates.

An active hardware update need not be interrupted when a newer presentation becomes available.

Normal scheduled publication does not require simultaneous completion or acknowledgement from every destination. Transient push and refresh use synchronous per-request completion reporting for every requested destination, as defined under [Transient admission and refresh](#transient-admission-and-refresh).

The order of backend declarations does not establish publication priority.

Multi-backend publication must preserve bounded memory use and must not require one complete image copy or an unbounded update queue for every pending presentation.

Display updates occur at meaningful presentation changes, including:

- the beginning of a new display day;
- scheduled progressive reveals;
- Recovery when a destination has not accepted the required image.

Refrain does not require continuous physical refresh or animation.

Presentation requests are distributed independently to configured backends.

Backend updates must be coordinated so that overlapping operations cannot corrupt communication with an individual destination.

A backend that has already successfully presented the required image should not repeat an expensive update merely because the scheduler reevaluates its state.

For image-server, publication encodes and retains each destination's image representation in memory. An optional shared HTTP service exposes those representations independently of publication acceptance.

Use independent execution for each configured backend instance so that slow or blocked operations do not delay publication through other backend instances. Destinations sharing one backend instance share its lifecycle and serialization.

A dedicated worker per backend instance is the preferred initial implementation. Use ordinary Python threading facilities rather than introducing a separate asynchronous framework or process-management service.

Keep backend publication synchronous and based on complete Pillow images.

Serialize publication and lifecycle operations for each individual backend instance. Never invoke overlapping operations on the same instance, including operations for different named destinations.

For normal scheduled publication only, maintain at most one pending desired presentation identity per configured destination. When a newer scheduled presentation becomes required, replace that destination's obsolete pending scheduled request rather than accumulating stages, and retain the latest required identity for that destination. Track the most recent successful scheduled publication independently per destination, including those sharing an output specification or backend instance.

Do not interrupt an active hardware transfer unless its backend explicitly supports safe interruption.

Bound shutdown waiting to 60 seconds total across workers. If a synchronous publication is still blocked at the deadline, report it and return without calling `close()` concurrently with that operation. Keep the worker daemonized and retain its active image until the operation returns or the process exits; the worker then attempts backend cleanup if it returns.

The coordinator must remain responsive to scheduling events while backend workers are active.

Track each destination's latest required scheduled presentation independently from its most recent successful scheduled publication.

Persist advancement of the globally required reveal stage through the existing operational-state mechanism without waiting for all backend updates to complete. Backend workers must not independently advance authoritative reveal progress. A failed or uncertain destination publication affects only that destination's publication status and recovery requirements.

A scheduled destination acknowledgement is successful only when that destination's publication operation completes successfully. Success for another destination must not satisfy its scheduled acknowledgement, even when both use one backend instance or the same image variant.

Identify each requested presentation using an opaque identity associated with the prepared image. The coordinator may derive this identity from the committed selection revision and resolved reveal stage, but backend implementations must not depend on those values or inspect persistent operational state.

Associate each outstanding scheduled destination publication with the identity it was asked to publish. Record scheduled acknowledgement only for that identity, so completion of an older operation cannot incorrectly satisfy a newer pending request.

Transient publication uses separate admission and completion state, not the replaceable scheduled-presentation slot. Once admitted, a transient request must complete or fail for every requested destination and must not be replaced because newer scheduled work appears. It neither changes the scheduled desired identity nor clears or satisfies scheduled acknowledgement. Shared backend serialization, image ownership, resource lifetime, and safe shutdown rules apply to scheduled, transient, and forced refresh operations.

Keep intentional withdrawal distinct from backend failure or delivery unavailability. Ordinary scheduled work, transient `@all`, and forced refresh skip an intentionally withdrawn destination; an explicit transient request naming it is rejected. A failed or unavailable destination remains part of transient `@all` and forced refresh results rather than being silently reclassified as withdrawn. Do not add general runtime destination enable/disable or configuration mutation.

Avoid unnecessary image duplication. Backend workers must receive images whose lifetime remains valid throughout their publication operation.

Coordinate artifact cleanup with outstanding image readers and backend operations. Do not remove prepared images while an active or pending publication still requires them.

Do not persist backend-specific presentation acknowledgements. On every startup, recovery must reconcile the currently configured destinations and output specifications, then publish the currently required reveal stage to every available configured destination.

Keep worker state and synchronization limited to what is necessary for independent publication, shutdown, and recovery.

Avoid unnecessary physical refreshes.

A successful prepared-image update should not be repeated merely because the scheduler reevaluates its state.

When the desired stage advances during an active update, the backend should ultimately present the latest required stage rather than replaying obsolete intermediate stages.

Avoid overlapping display operations.

Backend processing order must not delay publication to another destination.

Include hardware-independent tests covering:

- Configured destinations receiving the prepared variant matching their output specification, with variants shared only for identical specifications.
- Globally duplicate destination-ID rejection.
- Capacity violations for `window` and `waveshare-13in3-e`, and valid repeated destination types for `image-server` through one shared backend instance.
- Valid repeated backend types being distinguished from the number of constructed backend instances; `publish` destinations support multiple destinations.
- Independent initialization and failure reporting.
- One backend continuing while another is blocked or slow.
- No overlapping updates to an individual backend.
- For normal scheduled publication, replacement of obsolete per-destination pending stages with the latest required presentation.
- Independent successful scheduled-publication tracking per destination, including destinations sharing one output specification.
- Failed and uncertain destination publications not being treated as successful.
- Recovery from individual backend failures without reselection.
- Startup recovery and republication to available backends.
- Artifact lifetimes while updates remain active.
- Graceful shutdown while one or more backends are busy.

Use injected or simulated backends to test slow and failed updates deterministically.

Validate the existing window and image-server backends together on a supported graphical development environment.

Verify physical Waveshare operation with another enabled backend on the target Raspberry Pi before declaring multi-backend presentation validated.

## Transient admission and refresh

The normal runtime's desired scheduled presentation is distinct from a one-shot transient publication submitted by an external local tool. A transient publication does not replace or invalidate the scheduled desired presentation. It does not modify the committed selection, selection revision, repetition or global history, reveal progression, scheduling state, prepared-image artifacts, or the identity of the normal desired presentation.

The runtime-control interface belongs to the resident Refrain process and is local-machine only, authenticated, and limited to explicitly defined operations. Its initial operations are destination discovery, transient complete-image publication, and refresh of the current scheduled presentation. It is separate from the `image-server` HTTP service and any public or future web presentation. It does not provide arbitrary filesystem access, backend-method invocation, configuration or content mutation, shell execution, or general remote procedure execution.

The runtime is authoritative for configured publication destinations and their output specifications. Discovery returns each exact configured destination ID, its declared aspect ratio, requested resolution, and whether it supports transient publication. IDs are opaque routing values: clients must not infer backend type, hardware, transport, or capabilities from their spelling. Backend-specific publication details remain runtime-owned. Destination discovery does not reserve a destination. Transient-publication capability indicates whether a destination accepts externally supplied completed images; it does not gate normal scheduled publication or refresh.

Before any backend is accessed, the runtime validates the complete request: each destination still exists, each current output specification matches the discovered specification, every selected destination has an image variant, and every image has the exact required dimensions. Malformed, unsupported, or inconsistent requests are rejected without backend access; the runtime does not infer a replacement destination, adapt a changed specification, or resize an image. Backends continue to receive complete images.

External publication is opportunistic, not queued. Admission is atomic across all requested destinations: if any selected destination is publishing or has work that prevents immediate safe admission, the entire request is rejected as busy before any transient publication begins. `@all` means every configured destination still participating in publication is included or none are. An intentionally withdrawn destination is excluded from transient `@all`; explicitly naming one is rejected. A failed or unavailable destination is not silently treated as withdrawn and remains included in `@all`, where its publication failure contributes to the request result. The bare ID `all` has no special meaning. Normal scheduled work has priority until an external operation is admitted. After admission, transient work is allowed to finish safely; newly required scheduled work may follow it but must not interrupt or replace the admitted operation. Operations against the same backend instance never overlap.

Only one transient publication request may be in transfer, validation, or admitted publication at a time. A second transient request is rejected as busy until the current transient operation reaches a terminal result. This global transient-operation serialization does not prevent destinations within one admitted operation from progressing concurrently through independent backend instances; ordinary per-backend serialization still applies.

Before admission, rejection means no requested publication has begun. After admission, the resident runtime owns the operation; client disconnection does not cancel, roll back, or preempt it. The operation continues under ordinary backend safety, serialization, and shutdown rules. If publication completes or partially completes but the terminal acknowledgement is not delivered, the client must treat the outcome as unconfirmed: it cannot infer that nothing was published, that every destination succeeded, or that every destination failed. The client must not automatically replay the request because the acknowledgement was lost. Publication across destinations is not transactional and cannot be rolled back.

While a transient preview is visible, routine scheduler reevaluation of an unchanged scheduled identity does not repaint it solely because the destination contains different pixels. The preview may remain visible until ordinary scheduling requires a genuine presentation change or an explicit refresh is requested. There is no automatic timeout or restoration of the image that was visible before the preview.

`refrain --refresh` is a one-shot control-client operation that asks the resident normal runtime to republish its own presentation currently required by scheduling to every configured destination still participating in publication using a forced scheduled-publication operation. It skips intentionally withdrawn destinations and does not resurrect them. It is not historical restoration: for example, it publishes the current reveal stage if progression advanced after a preview. Refresh does not require transient-publication capability, so a destination may participate in scheduled publication and refresh without accepting externally supplied transient images. Admission is atomic across the complete participating destination set; ordinary backend availability and busy-admission rules apply. Refresh is rejected as busy rather than queued when the complete operation cannot be safely admitted immediately. Once admitted, it remains owned by the resident runtime even if the client disconnects.

A successful synchronous transient push or refresh reports success only after every requested destination has completed its backend publication operation successfully. A failure at one destination is reported; success at another does not make the complete request successful. If its terminal acknowledgement is lost, the client observes an unconfirmed outcome rather than success or failure. The public commands provide visible progress before waiting on slow publication.

Any future configured destination that supports the ordinary complete-image publication contract participates through runtime-supplied discovery and routing, without viewer-specific backend logic. Transient-publication capability is a backend-generic destination property and is reported as such during discovery; clients do not infer it from identifier spelling or backend type. If the requested destination is unsupported—or `@all` includes any participating destination that is unsupported—the request is rejected before rendering or publication. `@all` does not silently omit unsupported or failed destinations, but does exclude destinations intentionally withdrawn for the resident runtime.

## Transient transfer and staging

Extend the existing application-owned publication coordinator. Transient and scheduled publication must use the same configured backend instances, per-instance serialization, lifecycle ownership, and safe shutdown behavior; do not create a second path that independently constructs or opens hardware.

Keep the normal desired scheduled presentation distinct from transient request state. Reserve all selected destinations atomically only after validating the complete request and confirming immediate safe admission. Reject a busy request in full rather than partially publishing or queuing it. Preserve scheduler responsiveness while receiving image data and waiting for publication; ordinary threads may perform control handling where needed, but no asynchronous framework or external daemon is required.

Separate request admission from client connection lifetime. Rejection before admission means no requested publication began. After admission, the resident runtime owns the operation: socket or pipe closure is not cancellation, and admitted work continues under ordinary backend safety and serialization rules. If the client is gone, safely discard or fail delivery of the terminal response without starting another publication attempt. A lost terminal acknowledgement leaves the client's outcome unconfirmed; do not imply rollback, exactly-once delivery, or automatically replay the request. No durable transaction journal or replay protocol is required.

Bound retained transient image memory by staging transferred lossless PNG variants in request-scoped temporary storage rather than retaining the complete decoded request in memory. Decode each transferred variant only long enough to validate its encoding, mode, dimensions, and configured transport bounds, then release that decoded image while retaining the validated PNG for the admitted operation.

Transient staging is not scheduled prepared-image storage, authoritative operational state, or reusable daily presentation cache. The staged files belong only to the current transient operation. Backend workers may decode the required staged variant on demand and must release each decoded image after publication. Destinations with identical output specifications reuse the same staged PNG.

Remove transient staging when the operation reaches a terminal result or when a pre-admission request is abandoned, rejected, disconnected, or times out. After acquiring exclusive resident ownership and before accepting runtime-control requests, reconcile and remove stale transient staging left by an abnormal previous runtime. Never remove staging still owned by an active transient operation.

## Failure handling and retries

Display backend failures are isolated by destination.

Failure to initialize, update, or recover one backend must be reported without preventing otherwise functional backends from presenting the current image.

Recoverable failures are retried with a finite attempt budget and bounded backoff. Once exhausted, retries stop until a subsequent scheduled publication, refresh, or applicable transient publication creates another opportunity.

Retries must not indefinitely block scheduling, other destinations, or recognition of newer presentation requirements.

A backend instance that can no longer accept updates must be released or disabled safely. Unrecoverable failures are not retried automatically, and intentionally withdrawn destinations are not recovered automatically.

An unavailable backend must not be silently replaced with a different backend type.

When no configured destination is externally available for delivery, Refrain reports the condition and continues its scheduling, persistence, preparation, and runtime-control responsibilities. Total delivery unavailability, backend failure, or withdrawal is not by itself fatal.

The application must distinguish a known successful update from a failed or uncertain update where the backend permits.

An uncertain hardware result must not be treated as proof that the desired image was successfully displayed.

For image-server, unsuccessful image encoding must not expose incomplete content or invalidate the previously accepted representation for the affected destination.

Individual network-client failures do not constitute display-backend update failures. The backend does not require clients to retrieve or acknowledge published images.

Retry recoverable initialization and publication errors on the affected backend without blocking other workers or the application scheduler. Each recovery opportunity permits at most five total attempts. Retry delays start at one second, double exponentially, and are capped at 60 seconds. After exhaustion, another publication opportunity is required.

Backend recovery must not modify committed selection history or cause quotation reselection.

Hardware failures do not invalidate committed selections.

Classify failures sufficiently to support meaningful diagnostics and bounded recovery.

`DisplayBackendError.recoverable` defaults to true. Backends mark errors nonrecoverable when the active instance cannot safely accept another update, such as a closed window or disabled hardware transport.

Only `DisplayBackendError` instances explicitly marked recoverable are retried. Unexpected exceptions during construction or update are logged as programming/backend failures and terminally disable that destination.

An unrecoverable backend error must release or disable the affected instance safely. Other functional backends must continue operating.

Initialization failures should be reported independently. Do not assume that an instance which failed construction can be retried using the normal update interface.

Where recovery requires constructing a replacement backend instance, coordinate cleanup and reinitialization without overlapping operations on the same destination.

Use bounded retry delays rather than unrestricted rapid retries. After retry exhaustion, stop attempting that failure until a subsequent scheduled publication, refresh, or applicable transient publication creates a new recovery opportunity. Do not retry unrecoverable errors or intentionally withdrawn destinations.

Retries must not indefinitely block recognition of newer scheduled presentation requirements.

If every configured destination becomes unavailable, report the condition and keep the resident runtime operating its scheduler, persistence, preparation, and runtime-control responsibilities. Total destination unavailability, unrecoverable failure, or intentional withdrawal is not a fatal application condition.

Distinguish failures occurring before presentation, failures during presentation, and uncertain outcomes when the underlying implementation permits.

Do not report successful hardware presentation when the result is unknown.

Hardware validation must distinguish between driver-call success and visibly correct panel output.

## Desktop window lifecycle and withdrawal

The desktop window backend presents complete images in a graphical window suitable for development and validation on Windows and Linux. Its image-display area matches the supplied image dimensions and presents the image at native pixel size. A later update with different dimensions resizes the display area; it does not resample, crop, or letterbox the image.

The window backend owns its GUI event loop and remains responsive between synchronous image updates, including while the application is otherwise idle. It replaces the image in one window and releases that window when `close()` returns.

Closing the desktop window through the window manager intentionally withdraws its destination for the remainder of the resident runtime. The window is recreated only when a new runtime starts.

The backend reports initialization, presentation, and cleanup failures through common display-backend errors. It reports an unavailable graphical environment with guidance to install Tk support and use a graphical session.

Provide a desktop window backend for graphical Windows and Linux environments.

Use an established GUI facility rather than creating a custom windowing system.

The backend must support successive complete-image updates in a persistent window.

Keep GUI dependencies and event-loop requirements isolated from the application scheduler and non-window backends.

Do not require desktop GUI dependencies for ordinary hardware-independent imports or for headless Waveshare deployments.

The desktop backend is a development and testing presentation destination, not an alternative image renderer.

Use the platform's Tk support and Pillow's `ImageTk` presentation adapter. Import them only when constructing the window backend; configuration, rendering, and other hardware-independent imports must not require a graphical environment. Keep the Tk event loop in a backend-owned thread so updates remain synchronous without requiring the caller to run a GUI loop.

Create, operate, and finalize Tk interpreter objects on that GUI thread. Before it exits, destroy the window and release all interpreter-owning references, including widgets and active Tk images. Queued commands and reported errors must not carry Tk owners or GUI traceback frames into caller-thread cleanup. A successful `close()` must join only after GUI-owned cleanup completes.

The window backend must preserve caller-owned image data, replace the image in its existing window, and report initialization, presentation, and cleanup failures. On Linux, a Tk-capable Python installation and an active graphical session are required; standard Windows Python installations typically include Tk.

Distinguish user-requested window closure from application-driven `close()` and unexpected GUI failure. Notify the publication coordinator promptly of user-requested closure; ordinary application shutdown must not emit a withdrawal notification. Unexpected GUI or backend failure remains failure or unavailability rather than intentional withdrawal.

## Waveshare conversion and controller lifecycle

The Waveshare 13.3-inch panel resolves to the fixed 4:3 @ 1600 × 1200 output specification.

Its backend receives the matching RGB output image and must not resize it.

An update with dimensions other than 1600 × 1200 is invalid and reports a backend update failure as a contract violation; it is not resized to fit.

Hardware-independent post-processing converts the complete RGB output image once to a palette-indexed raster using the vendored driver's active seven palette entries, in index order: black, white, yellow, red, black, blue, and green.

The duplicate black entry is retained.

The vendored source also contains a commented alternative ordering (black, white, green, blue, red, yellow, orange), which is not the active panel palette and must not be substituted.

The backend passes these resolved indices to the driver, which rotates the index raster to controller orientation without changing its values and packs adjacent indices into the transport-specific 4-bit buffer without requantization.

The complete buffer is prepared before initializing the controller and must contain exactly 960,000 packed elements.

Each valid update initializes the controller, transfers the complete image, and returns the controller to sleep.

It does not clear the display before an update or during shutdown.

`close()` is repeatable and sleeps the controller only when an update has left it active.

Use the Waveshare Python implementation appropriate for the supported 13.3-inch e-Paper HAT+ (E).

Keep the imported driver surface as small as practical.

Do not include support for unrelated Waveshare display models merely because those implementations are distributed together.

Record the provenance, version or revision, and license of vendor code incorporated into the repository.

Do not modify vendor driver behavior without understanding the relevant hardware requirements.

When modifications are necessary, keep them reviewable and explain why they are required.

The physical backend uses Linux hardware SPI and GPIO character-device access through its optional `hardware` dependencies. Configure the required SPI overlay, `/dev/spidev0.0`, GPIO lines, and service-identity device permissions according to the project's deployment and permissions guidance. Keep the application process under the minimum practical privileges rather than running it as root. The transport must remain lazy-loaded so non-hardware development and other display backends do not require these dependencies.

Only the Waveshare backend should depend on its vendor driver, SPI, or GPIO facilities.

The application must remain testable without physical hardware.

Do not expose GPIO pins, controller commands, or driver-specific state to content, scheduling, rendering, or persistence components.

Backend implementations must validate incoming image dimensions and representation against their supported destination. Do not silently resize or recolor prepared images.

A physical backend owns initialization, full-frame updates, controller sleep or release, and cleanup.

Use supported driver lifecycle operations rather than assuming a controller can resume from sleep without reinitialization.

The shared interface must not force the application to manage hardware-specific initialization or sleep operations.

`close()` must support orderly release of resources and should be safe during ordinary shutdown and failure cleanup.

Validate initialization, repeated updates, sleep behavior, and recovery using the actual display.

A working example program establishes basic compatibility but does not prove reliable long-term unattended operation.

Verify the Waveshare publication path quantizes exactly once, passes palette indices unchanged through driver rotation and 4-bit packing, and leaves the original RGB image unchanged.

Verify the conversion can be imported and exercised without GPIO/SPI dependencies and that the driver and viewer use the same conversion.

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

For Waveshare visual post-processing, physical validation should compare a viewer-exported processed preview with the corresponding image published to the supported panel. Monitor colorimetry may differ from e-paper pigments; compare palette and dither structure, and report when this hardware check was not available.

Do not claim a Raspberry Pi model is supported solely because it uses a compatible GPIO interface.

## Integrated HTTP delivery

The `image-server` backend provides network-accessible representations without requiring directly connected display hardware. One backend instance maintains an independent current image representation and entity tag for each configured destination. A present top-level `image-server` mapping enables the one shared HTTP listener; an absent mapping leaves the destinations registered and publication-capable without starting a listener.

Each destination is available at its own read-only HTTP endpoint:

`GET /display/<destination_id>/current`

A successful request returns the complete PNG for that destination's resolved specification, with the appropriate HTTP content type. For example, destination `kitchen` is available at `/display/kitchen/current`. The configured ID is used unchanged as the resource path.

The endpoint must be usable by standard HTTP clients, including ordinary web browsers, without requiring client-specific software or protocols.

Each destination resource supports HTTP entity tags (ETags) derived from its served image content. Clients may submit conditional requests using `If-None-Match`; when that destination's current representation matches, the service returns `304 Not Modified` without transferring the image body.

When no image has been accepted for the requested output, the service returns `503 Service Unavailable`.

The backend retains each current encoded PNG and its associated entity tag in memory. It does not create or manage a separate persistent image store.

Publishing first encodes and retains the complete representation for the selected destination, independently of listener startup or operation. A bind or listener failure does not invalidate publication or discard prior representations. Each subsequent publication provides a bounded opportunity to recover the listener; on recovery it serves the latest accepted representations without regenerating content. Concurrent requests must observe a consistent, complete image and entity tag for one destination, never partially updated content.

The existing prepared-image persistence and recovery mechanisms remain authoritative. After application startup or recovery, the scheduler supplies the appropriate prepared image through the normal backend interface.

The HTTP service operates independently of individual clients. It does not track display devices, maintain client sessions, queue updates, or require acknowledgement that an image has been physically displayed.

Clients determine when to retrieve images. A client may miss intermediate reveal stages and retrieve only the most recently published image.

The backend does not control client polling intervals, power management, physical display refreshes, or client-side image retention.

The service must remain responsive between image replacement operations without requiring the application scheduler to process HTTP requests.

The backend owns its listening resources and concurrent request handling. A listener bind or startup failure is reported as unavailable delivery, not as failure to retain an encoded image; it does not prevent backend publication or terminate the runtime. Later publication provides a bounded opportunity to recover the listener, which must then expose the latest retained representations. Shutdown must release listening resources and terminate backend-owned execution without leaving the HTTP service running independently of Refrain.

The configured listening address controls network accessibility. The service is intended for explicitly trusted local-network deployments and must not expose application configuration, content-library files, persistent state, or privileged operations.

The image-server backend is distinct from future local or public web publishing functionality. It provides rendered image data for clients rather than a general-purpose web presentation or content-management interface.

This section describes the current integrated Version 0.1 backend. It remains in place during the transition and is retired only after the independent `refrain-image-server` consumer has been implemented and validated against [the filesystem-publication contract](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md).

The requirements below describe the current integrated Version 0.1 backend during the transition. Do not extend it as the target non-direct destination mechanism. The target `refrain-image-server` is a separately supervised consumer of filesystem publications and replaces this backend only after that consumer is implemented and validated.

Implement the `image-server` backend using standard HTTP facilities suitable for the supported Python runtime.

Prefer the Python standard library unless an additional dependency provides a demonstrated benefit.

Keep HTTP request handling and network-resource ownership within the backend. The application scheduler must not run a server event loop or process individual HTTP requests.

The service must remain responsive between image replacement operations.

Backend construction establishes the configured image-server destinations and their in-memory capability to accept and retain complete image representations. Successful HTTP listener binding is not a prerequisite for this publication capability. If the optional `image-server` listener configuration is omitted, do not attempt to bind a listener; the destinations remain publication-capable while external HTTP delivery is unavailable.

When listener configuration is present, listener startup and binding are independent of destination image publication. A listener startup or binding failure must be reported with an actionable diagnostic and follow the established bounded recovery behavior for external delivery. It must not prevent the backend from accepting and retaining complete image representations.

Encode incoming Pillow images as complete PNG representations before making them available to HTTP clients. Retain the encoded bytes and associated entity tag in backend-owned memory.

A successful destination publication acknowledges that its complete PNG representation and entity tag were retained in memory. It does not assert that a listener is available, that an HTTP client retrieved the image, or that a client displayed it. Report external delivery availability separately from publication acknowledgement.

Replacement of the currently served representation must be synchronized with concurrent HTTP requests. A request must observe one consistent image and its corresponding entity tag, without holding backend state locked during network transmission.

Preserve the previously accepted representation when a replacement cannot be completed successfully.

Use standard HTTP conditional-request semantics rather than introducing a custom image-version or polling protocol.

Keep the HTTP interface narrowly scoped and read-only. Do not expose arbitrary filesystem paths, application configuration, content-library data, persistent state, or administrative operations.

Handle unsupported methods and paths explicitly. Malformed requests and individual client disconnections must not terminate the backend or corrupt its current representation.

The backend must stop accepting requests and release its listening resources during `close()`. Coordinate concurrent request handling and shutdown so that inactive or slow clients cannot indefinitely prevent orderly application termination.

Test the backend without physical display hardware or external network services. Automated tests should exercise the HTTP interface through a real local listening socket, including:

- successful retrieval of every configured image-server destination PNG;
- correct response content type and image contents;
- independent entity tags and conditional requests for each image-server destination;
- replacement of each output image and invalidation of that output's previous entity tag;
- correct delivery when multiple outputs share a prepared variant or use distinct variants;
- requests made before the first successful image update;
- failed image replacement preserving the previous representation;
- concurrent requests and image updates;
- invalid HTTP methods and paths;
- initialization failures caused by unavailable listening addresses or ports;
- orderly shutdown, repeated cleanup, and rejection of updates after closure.

Use locally allocated test ports rather than assuming a fixed port is available. Tests must not depend on access to an external network, a particular LAN configuration, or Raspberry Pi-specific facilities.

## Retained content and delivery failures

E-paper retains its visible image without continuous power.

Refrain should preserve useful displayed content across temporary application and hardware failures when possible. Preserve the retained e-paper image when possible. Do not clear a physical display merely because a recoverable software problem occurred or another backend failed.

The image-server backend retains each destination's last successfully accepted image in memory, even while the HTTP listener is unavailable. It does not independently persist those representations across application restarts.

Network clients are responsible for retaining their displayed content during temporary network or application unavailability.
