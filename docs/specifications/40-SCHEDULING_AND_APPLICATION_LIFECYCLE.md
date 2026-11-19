# Scheduling and Application Lifecycle

## Civil time and logical-date evaluation

The host operating system is the sole authority for local timezone and daylight-saving rules. Refrain does not configure or persist a timezone identifier.

Display-day and reveal schedules use host-local civil time. Use timezone-aware datetimes for absolute event timestamps and monotonic elapsed time for durations.

Do not assume that a local calendar day contains exactly 24 elapsed hours.

An ambiguous scheduled wall time resolves to its first occurrence; a nonexistent scheduled wall time resolves to the first valid local instant after the gap. Apply these rules to reveal deadlines and display-day boundaries, including non-hour offset transitions.

Logical-date evaluation orders the current instant and resolved display-day boundaries as timezone-aware instants, not solely by their local `HH:MM` values.

Changing the host timezone is an operating-system operation. Refrain does not need to adapt its scheduling while running; restarting afterward is acceptable. At the next scheduling evaluation, the current host-local logical display date determines whether the committed selection remains active. Reveal progression does not move backward while that logical date remains unchanged.

Clock changes must be handled according to the established display-day transition and reveal-progression policies.

The display day begins at a configured local time.

For example, with a configured start time of 06:00, a display day normally begins at 06:00 and remains active until the following configured day-start boundary.

The local calendar date associated with a new selection determines its special-date eligibility.

A committed daily selection remains authoritative while its display date matches the current logical display date.

Whenever the current logical display date differs from the committed selection's display date, Refrain establishes a new selection for the current logical date. This rule applies during continuous operation, after restart, and after either forward or backward clock adjustments. It does not depend on observing a particular boundary crossing.

Repeated scheduling evaluations for the same committed logical date must not generate duplicate selections. Display failures, content-library changes, and missed reveal events do not independently trigger reselection.

When the logical date is unchanged, the existing selection remains authoritative and its reveal progression never moves backward. A transition to another logical date establishes a new selection and reveal progression, even if a quotation was previously selected for that date.

The current logical display date is calculated from resolved day-start boundaries as defined under Logical-date evaluation. When the clock advances within that logical date, Refrain advances to the reveal stage appropriate to the new time.

When the logical display date differs from the committed selection's date, Refrain selects a quotation for the current logical date, including after a forward jump across one or more day-start boundaries.

Skipped display dates do not require retrospective selection or presentation.

For example, if the clock advances from October 17 to November 28, Refrain selects content for November 28 and presents the appropriate reveal stage.

Moving the clock backward does not reverse reveal progression while the logical display date remains unchanged.

If the backward adjustment changes the logical display date, Refrain establishes a new selection for that date.

With `day_start: "06:00"`:

- Monday 07:00 to Monday 03:00 changes the logical date from Monday to Sunday and establishes a new selection.
- Monday 15:00 to Monday 10:00 keeps the same logical date and selection; reveal progress is retained.
- Monday 23:00 to Tuesday 02:00 keeps the same logical date and selection.
- Tuesday 02:00 to Tuesday 07:00 changes the logical date from Monday to Tuesday and establishes a new selection.

Moving to another logical date does not reverse or remove prior selection or history records. The new selection has its own reveal progression.

The logical display date is the local calendar date associated with the most recent resolved day-start boundary not later than the current instant.

Resolve the configured day-start for the current host-local calendar date using the Local time rules: an ambiguous wall time uses its first occurrence, and a nonexistent wall time uses the first valid local instant after the gap. Compare the current instant with that resolved boundary using timezone-aware instant ordering. At or after the boundary, the logical display date is the boundary's local calendar date; otherwise, it belongs to the preceding resolved display-day boundary. Do not determine whether the boundary has passed using only a local wall-clock-value comparison.

On ordinary dates, this remains equivalent to the intuitive rule: before `day_start`, use the preceding local calendar date; at or after `day_start`, use the current local calendar date.

For example, with `day_start: "06:00"`, Monday 05:00 has logical display date Sunday, and Monday 07:00 has logical display date Monday.

During a fall-back transition with `day_start: "01:30"` inside the repeated interval, the first occurrence of 01:30 is authoritative. Both the interval after that occurrence and before the fold, and the second occurrence of 01:15, belong to the new logical display date: the resolved boundary has already passed in absolute time. The repeated hour must not temporarily regress the logical date or create extra selections or history records. During a spring-forward gap containing the configured day-start, the preceding logical date remains active until the first valid local instant after the gap.

On startup and during ordinary scheduling, compare this date with the committed selection's display date. A mismatch requires one new selection for the current logical date; skipped dates do not require retrospective selections. The committed date and day-start context are sufficient for this comparison. Do not require a boundary-observation event, retain an outdated selection because a boundary was not observed, or persist or infer clock-observation history.

On startup, Refrain recovers the committed selection and its highest previously reached reveal stage.

The active stage must be at least the previously reached stage.

A restart retains the committed selection and reveal progression when its display date matches the current logical display date. If the date differs, startup establishes a new selection for the current logical date with its own reveal progression.

Backward clock adjustments must not cause previously revealed fields to become hidden.

Reveal progression remains monotonic within the lifetime of the committed selection.

When a new daily selection is committed, reveal progress begins according to that selection's applicable schedule and current time.

Clock adjustments that establish a new display day follow the rules defined in the display-day model.

A restart retains the committed selection and reveal progression only while the current logical display date matches the committed date.

The active selection remains authoritative while the current logical display date matches its committed date; a mismatch requires a new selection regardless of clock direction or restart.

Use operating-system local civil time for display-day and reveal calculations. Resolve future wall-time deadlines with operating-system local-time rules; a timezone-aware value returned by `datetime.now().astimezone()` may contain only the current offset and is not sufficient to resolve future dates.

Keep local wall-time conversion isolated so tests can inject deterministic local-time rules without changing the process timezone.

Resolve day-start boundaries through the same isolated local-time conversion rules used for scheduled deadlines. Follow Architecture's Logical-date evaluation: compare the current instant with the resolved day-start boundary for the current local calendar date; at or after it, use the boundary's local calendar date, otherwise use the preceding resolved display-day boundary's date. Compare timezone-aware instants in absolute-time order (for example, after conversion to UTC), preserving the distinction between occurrences in a fold. Do not implement this as a bare local `time` comparison when the date can contain an ambiguous or nonexistent boundary.

Do not use fixed-duration sleeps as a substitute for correct calendar-boundary calculations.

The scheduler should ordinarily wait until the next meaningful event rather than polling continuously.

`next_scheduling_deadline()` derives reveal deadlines from the committed selection's effective schedule and combines them with the next configured day-start time. `wait_for_scheduling_event()` waits interruptibly and periodically rechecks wall time, returning control after a clock adjustment so the coordinator can recalculate an obsolete deadline. Scheduling is based on comparing the current logical display date with the committed selection's date, not on a boundary-observation event.

Implement the documented forward- and backward-clock behavior without allowing previous reveal stages to become hidden.

If a clock change alters the logical display date, establish one selection for the current logical date regardless of adjustment direction. If the date is unchanged, retain the selection and its monotonic reveal progression. Tests must cover these cases without requiring the host operating-system clock to be modified.

Separate the current time source from scheduling policy sufficiently to permit controlled test inputs.

Use monotonic elapsed time for retry intervals and other durations that should not be affected by wall-clock adjustments.

Persist the display date and day-start context required by [logical-date model](#civil-time-and-logical-date-evaluation). On startup, compare the current logical display date with the committed date: retain the selection when they match and establish one selection for the current logical date when they differ.

Test logical-date comparison across restarts, missed day starts, backward and forward clock adjustments, and large forward jumps. Repeated evaluations for the same committed logical date must not duplicate a selection. Do not add or infer clock-observation history.

Require deterministic hardware-independent tests with explicit current instants and injected local-time rules, without changing the host operating-system clock or process timezone. Cover:

- ordinary dates before, exactly at, and after day start, preserving the previous/current local calendar date behavior;
- a fall-back transition with day start inside the repeated interval, verifying that the first occurrence is the boundary;
- current time after the first day-start occurrence but before the clock fold, retaining the new logical date;
- current time during the second occurrence of a wall time earlier than day start, such as second-occurrence 01:15 with `day_start: "01:30"`, retaining the new logical date rather than temporarily regressing;
- a spring-forward transition with day start inside the nonexistent interval, retaining the preceding logical date before the first valid instant after the gap and using the new logical date at and after that instant;
- non-hour offset folds and gaps where supported by the injected local-time rules;
- startup, restart, and fresh evaluation within those transition intervals without prior boundary observations;
- repeated evaluation and restart with a committed selection for the evaluated logical date, producing only one selection and no duplicate history records while retaining monotonic reveal progression.

Automated testing should cover:

- cumulative reveal progression;
- forward and backward clock adjustments;
- display-day boundaries and restart behavior.

## Reveal progress and missed events

Missed intermediate reveal stages are not presented sequentially.

Refrain progressively reveals information associated with the committed daily selection.

The primary quotation appears at the first presentation stage.

Additional information, such as source and attribution, appears at later configured stages.

Reveals are cumulative.

Information that has become eligible for presentation must remain visible for the remainder of the committed selection.

Optional fields absent from an entry are omitted rather than displayed as empty placeholders.

A global reveal schedule defines the default timing for supported semantic fields.

Individual content entries may override that schedule.

The effective schedule is resolved before the daily selection record is committed.

Subsequent changes to global configuration or the original entry do not alter the committed schedule.

Reveal schedules must be validated to prevent impossible or contradictory behavior.

Reveal timing is evaluated relative to the logical display day associated with the selection.

If the current time requires a later reveal stage, advance directly to it; a forward clock adjustment may require that advancement immediately.

Reveal progression never moves backward within a committed selection.

Within one logical display date, reveal progression is monotonic. A new selection for another logical display date begins its own reveal progression.

## Scheduling interfaces and waits

The hardware-independent scheduling evaluator determines whether an initial or new selection is required, the display date for that selection, and the required reveal stage for a committed selection. It accepts an explicit timezone-aware current timestamp, application configuration, and recovered persistent state.

The public interface is `refrain.evaluate_scheduling(current_time, configuration, state)`. It returns an immutable `SchedulingDecision` whose `SchedulingAction` is `INITIAL_SELECTION`, `NEW_SELECTION`, `ADVANCE_REVEAL`, or `NO_ACTION`. Initial and new selections include `display_date`; decisions for a committed selection include `required_reveal_stage`. Invalid inputs raise `SchedulingEvaluationError` rather than producing a guessed date.

The evaluator calculates the current logical display date from resolved host-local day-start boundary instants as defined under Logical-date evaluation, using `scheduling.day_start`. With a committed selection, a different logical date requires a new selection for that date; the same date retains the selection and advances reveal progress monotonically. Repeated evaluation for one committed logical date does not request another selection. Evaluations are pure; they do not select content, persist state, prepare images, or operate a display.

`refrain.resolve_reveal_stages(selection)` returns the canonical ordered `CompositionVisibility` sequence for a committed daily selection. The coordinator uses this same sequence for image preparation and cache validation; scheduling evaluation derives its required stage index from that sequence. Simultaneous reveal times share a stage, fields scheduled at the quotation time appear in stage zero, and source and attribution may reveal in either order. The final stage includes every available optional field.

The required scheduling contract does not include `DisplayDayBoundary`, `DisplayDayBoundaryObserver`, and the `observed_boundary` argument to `evaluate_scheduling()`. Do not introduce a boundary-history subsystem in their place.

`refrain.next_scheduling_deadline(current_time, configuration, state)` returns the current time immediately when initial selection or a logical-date mismatch requires a selection; otherwise, it returns the next applicable committed reveal time or configured day-start time. `refrain.wait_for_scheduling_event(deadline, wake_event, ...)` waits for that deadline or an external wake event and returns control for reevaluation after a detected wall-clock adjustment. The coordinator remains responsible for calling `evaluate_scheduling()` and executing its decisions; waiting does not select content, mutate persistent state, prepare images, or operate a display.

The application coordinator executes returned decisions through the selection, persistence, preparation, and display components. For a committed selection whose logical date is unchanged, the required reveal stage is the later of the stage implied by its effective schedule in host-local time and the persisted highest stage. A new selection starts its own reveal progression. The scheduling context contains the display date and day-start time. Missing optional fields do not add reveal stages, and missed reveal times can advance directly to the latest applicable stage. A persisted stage beyond the sequence's final index is invalid and evaluation raises `SchedulingEvaluationError`.

When a reveal advancement is required, the coordinator publishes the corresponding prepared variant to each destination. Scheduling evaluation does not determine whether an image was successfully presented.

A failed display update does not invalidate the committed selection or its prepared images.

A subsequent successful update may skip intermediate stages and present the latest required image.

## Scheduling and delivery boundaries

The display scheduler determines which reveal stage should currently be presented. Each destination receives the prepared output image matching its output specification.

Normal scheduled reveals do not invoke the renderer or consult the content library.

The display backend owns physical display communication and recovery.

The committed daily selection remains authoritative when prepared images need to be recovered.

Time and configuration are inputs to the relevant responsibilities. Neither is an independent source of quotation-selection policy.

## Startup and daily transitions

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
12. Independently attempt publication of the corresponding prepared image to every participating destination.
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

## Startup information-view timing

The information view is independent of the committed daily selection. Preparing or displaying it must not create a new selection, modify selection histories, or advance reveal progress.

Automatic presentation occurs once on each application start, subject to the configured duration. It does not repeat at ordinary display-day boundaries.

The automatic duration defaults to 60 seconds. A duration of zero disables automatic presentation without disabling the information-view capability.

The configured duration is measured using elapsed monotonic time beginning when the first backend successfully publishes the information view.

Publication to other backends remains independent. A slow or unavailable backend must not delay the transition to daily presentation for other destinations.

If no backend successfully publishes the information view within a bounded initial attempt period, the application proceeds toward normal daily presentation rather than waiting indefinitely.

When the duration expires, Refrain determines the currently required daily presentation using the normal scheduling and recovery rules. It does not replay reveal stages that are no longer required.

An information-view preparation or publication failure must not invalidate the committed selection or prevent ordinary daily presentation when a functional display destination remains available.

The information view may be requested independently of automatic startup behavior, but it is not one of the defined runtime-control operations.

Use the existing display publication coordinator to distribute the prepared information-view image to configured backends.

The startup information-view interval is transient application state. It does not require durable storage or modification of the committed daily selection.

Use a monotonic clock for the configured display duration. Begin timing when the first backend successfully acknowledges publication of the information view.

Bound the initial attempt to obtain a successful information-view publication so recoverable backend failures cannot postpone daily presentation indefinitely.

Do not require successful publication by every backend before the information-view interval begins or ends.

When the interval ends, reevaluate the normal scheduling requirements and request the currently appropriate prepared daily image. Preserve the scheduled-presentation acknowledgement independently; information-view publication must not replace or invalidate it. Preserve independent backend execution, pending-update coalescing, and safe handling of active hardware transfers.

Do not reset or reconstruct display backends merely to transition between the information and daily views.

Information-view preparation failures must be reported without preventing ordinary daily presentation when that remains possible.

Include hardware-independent automated tests covering:

Include hardware-independent automated tests covering:

- default, disabled, and explicitly configured information-view durations;
- invalid duration values and documented fallback behavior;
- preservation of committed selection, repetition history, and reveal progression;
- preservation of normal scheduled-publication acknowledgement when an information view is published;
- publication to multiple independent backends;
- timer start after the first successful publication;
- wall-clock adjustments during the information-view interval;
- bounded initial publication attempts when no backend succeeds;
- transition to the latest required daily presentation after missed reveal events;
- failure isolation and shutdown during information-view presentation.

## Normal operation and waiting

After successful preparation, the application waits for the next meaningful scheduling event.

Scheduled reveal updates select an existing prepared image.

Normal operation must not require repeated content-library access or repeated rendering.

Clock adjustments are evaluated according to the display-day and reveal-progression rules.

The application must not rely on busy waiting to determine ordinary reveal times.

## Accelerated demo sessions

The optional `--demo SECONDS` operating mode repeatedly selects quotations and presents each canonical reveal stage at an accelerated interval. It bypasses normal time-of-day scheduling without manufacturing clock transitions. The automatic startup information view is suppressed.

The session determines its eligibility display date once from host-local time and the configured day start. Every subsequent selection uses that same date and the normal selection and resource-resolution procedure, including session repetition history. A date does not limit the number of selection revisions in this mode.

Demo progression belongs to the application controller, not the scheduler, renderer, or display backends. Each daily selection is committed before its complete required output-variant set is prepared or reused from cache. `resolve_reveal_stages()` supplies the same cumulative sequence used in normal operation, preserving simultaneous reveals and absent fields.

The initial stage is requested as soon as it is ready. Each valid prepared stage may progress even when no destination accepts its image. Its requested minimum monotonic viewing interval begins at the first successful backend acknowledgement, or at the publication attempt when none is available. Publication failure alone does not complete a stage or advance the demo; the controller's interval governs progression. Expiration completes the stage even when destinations are unavailable, failed, or withdrawn. After the final stage's interval, the controller may commit another selection. Preparation or image-loading failure leaves the stage pending and does not authorize progression or reselection. Publication remains owned by the existing coordinator, with independent backend workers, coalescing, and backend-owned refresh constraints; not every destination must acknowledge each stage.

Operational state, prepared artifacts, and global history are isolated in fresh temporary session storage using their existing formats. Configured and platform-standard production persistence locations are never used or modified in demo mode. The committed quotation, captured content preferences, canonical presentation, and reveal progression remain authoritative within the session. A complete valid prepared set remains stable while reused; after cache loss or invalidation, preparation reuses the canonical selections and resolves only effective destination overrides and output-dependent values from current configuration and available resources. The session continues selection and reveal progression when destinations are unavailable, failed, or withdrawn. Shutdown releases session resources; demo sessions are neither retained nor resumed.

Lifecycle, retry, timing, and testing implementation guidance is collected under [Accelerated demo sessions](#accelerated-demo-sessions).

`run_demo()` owns accelerated progression separately from normal scheduling. Load configuration first, then create standard-library temporary session storage for the existing operational-state store, prepared-image artifact store, and global-history store. Storage settings may be parsed as part of configuration but must not be used as demo persistence targets; do not inspect or open production persistence locations. Determine the initial display date through the OS-local/day-start calculation once; do not reevaluate wall time to drive demo stages.

Reuse the application selection, resource resolution, daily-selection commitment, reveal-progress persistence, image-cache recovery, and history-recording operations. Keep a pending selection proposal across commit retries, including uncertain publication followed by a failed reload, so an already published selection cannot be replaced inadvertently. Recover preparation or image-loading failures from the durable daily selection without skipping the requested stage. Best-effort history recording retains its ordinary semantics.

Use `resolve_reveal_stages()` for canonical progression. Publish prepared images with revision/stage identities through `DisplayPublicationCoordinator`. Wait interruptibly for any successful acknowledgement. Measure the viewing interval from `first_successful_publication_time()` when an acknowledgement exists; if no destination accepts the image, start the interval at its publication attempt. A valid prepared stage completes when this interval expires even if destinations are unavailable, failed, or withdrawn; publication failure alone neither completes nor advances a stage. After the final stage's interval, the controller may commit another selection. Preparation or image-loading failure leaves the stage pending and must not authorize progression or reselection. Use the same monotonic clock supplied to the coordinator. Initialization, preparation, publication failures, and wall-clock adjustments do not themselves alter committed selection or reveal state. Recheck elapsed time after interrupted or early waits; bound individual duration waits to avoid platform timeout overflow for large finite CLI intervals.

Use the normal independent backend retries and increasing application retry delays from 1 to at most 60 seconds. Do not reset backends between stages or require all destinations to succeed. Continue progression and retry waits while destinations are unavailable, failed, or withdrawn; only shutdown ends the session for those conditions.

Stop new work on Ctrl+C or SIGTERM. Close the publication coordinator before removing temporary storage, preserving its bounded worker shutdown and image-reference ownership. Attempt session cleanup even after fatal application errors; report cleanup failures without concealing the primary error or touching production files. Each invocation starts fresh and has no resumable session state. Suppress the startup information view in demo mode.

Cover CLI validation and normal-mode requirements, canonical progression, fixed eligibility dates, repeated revisions and pool exhaustion, stable resource identifiers, isolation from production files, fresh sessions, cleanup, interrupted waits, and preparation/publication/storage recovery with deterministic hardware-independent tests. Use injectable clocks, controlled waits, and fake backends instead of real-time sleeps. Include independent healthy/slow or unavailable destinations and all-backend loss; retain ordinary scheduler, startup, persistence, and recovery regression coverage. These tests do not establish physical e-paper behavior.

## Lifecycle recovery

Recovery is performed according to the stage at which an interruption occurred.

An interruption before selection commitment permits selection to be repeated.

An interruption after commitment preserves the committed selection.

Missing or incomplete prepared variants are regenerated as complete stage sets from the durable daily selection and its persisted canonical presentation, applying current destination overrides and output requirements without canonical reselection or reveal regression.

Recoverable destination and backend-service failures use bounded retries without delaying other destinations. Exhausted retries wait for a subsequent publication opportunity, and destination unavailability does not terminate the resident runtime.

After restart, each available backend is supplied with its currently required prepared variant without relying on persisted backend-specific presentation progress.

Recovery must not introduce additional history entries or silently substitute content.

Display backend failures must remain isolated from other destinations and must not invalidate content selection or persistent history.

Rendering failures must not cause reselection after a daily selection has been committed.

Content-library changes or validation failures must not modify an already committed daily selection.

An unrecoverable configuration or state error must be reported clearly rather than disguised as normal operation.

## Shutdown coordination

Normal shutdown must stop new presentation requests and safely release resources owned by every configured display backend.

Backend shutdown must account for active publication operations without permitting unsafe overlapping hardware access.

Shutdown waits for active synchronous publications only for a bounded period. It must not interrupt a backend operation or invoke that backend's cleanup concurrently with an active publication. If a publication remains blocked at the deadline, its worker retains the active image and attempts cleanup if the operation later returns; process termination may ultimately end a still-blocked worker.

Failure to close one backend must not prevent cleanup attempts for other backends.

Shutdown must not intentionally erase retained e-paper images.

Committed selection state, including the canonical presentation, remains available for subsequent startup recovery. Prepared images are a disposable cache that may be rebuilt from that canonical presentation.
