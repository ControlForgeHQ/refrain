# Scheduling and Application Lifecycle

## Civil time and logical-date evaluation

The host operating system is the sole authority for local timezone and daylight-saving rules. Refrain does not configure or persist a timezone identifier.

Display-day and reveal schedules use host-local civil time. Use timezone-aware datetimes for absolute event timestamps and monotonic elapsed time for durations.

Do not assume that a local calendar day contains exactly 24 elapsed hours.

An ambiguous scheduled wall time resolves to its first occurrence; a nonexistent scheduled wall time resolves to the first valid local instant after the gap. Apply these rules to reveal deadlines and display-day boundaries, including non-hour offset transitions.

Logical-date evaluation orders the current instant and resolved display-day boundaries as timezone-aware instants, not solely by their local `HH:MM` values.

Changing the host timezone is an operating-system operation. Refrain does not need to adapt its scheduling while running; restarting afterward is acceptable. At the next scheduling evaluation, the current host-local logical display date determines whether the committed selection remains active. Reveal progression does not move backward while that logical date remains unchanged.

For an existing committed selection whose display date remains the current logical display date, retain the committed resolved reveal-stage sequence after a host-timezone change. Do not recalculate its reveal instants, merge or split its stages, or remap its persisted stage ordinal. The active host-local timezone continues to determine the current logical display date and the resolution of future selections.

Clock changes must be handled according to the established display-day transition and reveal-progression policies.

The display day begins at a configured local time.

For example, with a configured start time of 06:00, a display day normally begins at 06:00 and remains active until the following configured day-start boundary.

The local calendar date associated with a new selection determines its special-date eligibility.

A committed daily selection remains authoritative while its display date matches the current logical display date.

Whenever the current logical display date differs from the committed selection's display date, Refrain establishes a new selection for the current logical date when eligible content is available. This rule applies during continuous operation, after restart, and after either forward or backward clock adjustments. It does not depend on observing a particular boundary crossing.

Repeated scheduling evaluations for the same committed logical date must not generate duplicate selections. Display failures, content-library changes, and missed reveal events do not independently trigger reselection.

Skipped display dates do not require retrospective selection or presentation.

With `day_start: "06:00"`:

- Monday 07:00 to Monday 03:00 changes the logical date from Monday to Sunday and requires a new selection evaluation.
- Monday 15:00 to Monday 10:00 keeps the same logical date and selection; reveal progress is retained.
- Monday 23:00 to Tuesday 02:00 keeps the same logical date and selection.
- Tuesday 02:00 to Tuesday 07:00 changes the logical date from Monday to Tuesday and requires a new selection evaluation.

Moving to another logical date does not reverse or remove prior selection or history records. A successfully committed new selection has its own reveal progression.

The logical display date is the local calendar date associated with the most recent resolved day-start boundary not later than the current instant.

Resolve the configured day-start for the current host-local calendar date using the local-time rules: an ambiguous wall time uses its first occurrence, and a nonexistent wall time uses the first valid local instant after the gap. Compare the current instant with that resolved boundary using timezone-aware instant ordering. At or after the boundary, the logical display date is the boundary's local calendar date; otherwise, it belongs to the preceding resolved display-day boundary. Do not determine whether the boundary has passed using only a local wall-clock-value comparison.

On ordinary dates, this remains equivalent to the intuitive rule: before `day_start`, use the preceding local calendar date; at or after `day_start`, use the current local calendar date.

For example, with `day_start: "06:00"`, Monday 05:00 has logical display date Sunday, and Monday 07:00 has logical display date Monday.

During a fall-back transition with `day_start: "01:30"` inside the repeated interval, the first occurrence of 01:30 is authoritative. Both the interval after that occurrence and before the fold, and the second occurrence of 01:15, belong to the new logical display date: the resolved boundary has already passed in absolute time. The repeated hour must not temporarily regress the logical date or create extra selections or history records. During a spring-forward gap containing the configured day-start, the preceding logical date remains active until the first valid local instant after the gap.

On startup and during ordinary scheduling, compare this date with the committed selection's display date. A mismatch requires evaluation of a new selection for the current logical date; skipped dates do not require retrospective selections. The committed date and day-start context are sufficient for this comparison. Do not require a boundary-observation event, retain an outdated selection because a boundary was not observed, or persist or infer clock-observation history.

On startup, Refrain recovers the committed selection and its highest previously reached reveal stage.

The active stage must be at least the previously reached stage.

When a new daily selection is committed, reveal progress begins according to that selection's applicable schedule and current time.

Clock adjustments that establish a new display day follow the rules defined in the display-day model.

Use operating-system local civil time for display-day calculations and reveal resolution at selection commitment. Resolve future day-start boundaries and new selections with operating-system local-time rules; a timezone-aware value returned by `datetime.now().astimezone()` may contain only the current offset and is not sufficient to resolve future dates.

Keep local wall-time conversion isolated so tests can inject deterministic local-time rules without changing the process timezone.

Resolve day-start boundaries through the same isolated local-time conversion rules used for scheduled deadlines. Compare the current instant with the resolved day-start boundary for the current local calendar date; at or after it, use the boundary's local calendar date, otherwise use the preceding resolved display-day boundary's date. Compare timezone-aware instants in absolute-time order (for example, after conversion to UTC), preserving the distinction between occurrences in a fold. Do not implement this as a bare local `time` comparison when the date can contain an ambiguous or nonexistent boundary.

Do not use fixed-duration sleeps as a substitute for correct calendar-boundary calculations.

The scheduler should ordinarily wait until the next meaningful event rather than polling continuously.

`next_scheduling_deadline()` derives reveal deadlines from the committed selection's frozen absolute UTC instants and combines them with the next configured day-start boundary resolved using the active host-local timezone. `wait_for_scheduling_event()` waits interruptibly and periodically rechecks wall time, returning control after a clock adjustment so the coordinator can recalculate an obsolete deadline. Scheduling is based on comparing the current logical display date with the committed selection's date, not on a boundary-observation event.

Separate the current time source from scheduling policy sufficiently to permit controlled test inputs.

Use monotonic elapsed time for retry intervals and other durations that should not be affected by wall-clock adjustments.

Persist the display date and day-start context required by the logical-date model.

Test logical-date comparison across restarts, missed day starts, backward and forward clock adjustments, and large forward jumps.

Require deterministic hardware-independent tests with explicit current instants and injected local-time rules, without changing the host operating-system clock or process timezone. Cover:

- ordinary dates before, exactly at, and after day start, preserving the previous/current local calendar date behavior;
- a fall-back transition with day start inside the repeated interval, verifying that the first occurrence is the boundary;
- current time after the first day-start occurrence but before the clock fold, retaining the new logical date;
- current time during the second occurrence of a wall time earlier than day start, such as second-occurrence 01:15 with `day_start: "01:30"`, retaining the new logical date rather than temporarily regressing;
- a spring-forward transition with day start inside the nonexistent interval, retaining the preceding logical date before the first valid instant after the gap and using the new logical date at and after that instant;
- non-hour offset folds and gaps where supported by the injected local-time rules;
- startup, restart, and fresh evaluation within those transition intervals without prior boundary observations;
- repeated evaluation and restart with a committed selection for the evaluated logical date, producing only one selection and no duplicate history records while retaining monotonic reveal progression;
- frozen reveal deadlines after restart and host-timezone changes while the logical display date remains unchanged;
- reveal-stage coalescing when distinct local wall times resolve to the same instant during daylight-saving gaps, including cumulative visibility, stage-zero coalescing, and absence of duplicate stages.

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

The effective reveal schedule must be resolved before committing the daily selection record. Entry reveal overrides are validated according to [Content-entry semantics](20-CONTENT_AND_CONFIGURATION.md#content-entry-semantics).

Subsequent changes to global configuration or the original entry do not alter the committed schedule.

Reveal timing is evaluated relative to the logical display day associated with the selection.

If the current time requires a later reveal stage, advance directly to it; a forward clock adjustment may require that advancement immediately.

Reveal progression never moves backward within a committed selection.

Within one logical display date, reveal progression is monotonic. A new committed selection begins its own reveal progression.

Operational state owns the highest reached reveal stage. Successful advancement must be committed to `state.json` before updating the shared publication checkpoint's reveal visibility. A failed checkpoint update does not reverse the committed progression. Recovery reconciles visibility from operational state without discarding otherwise valid resolved presentation choices.

An invalid persisted or requested reveal stage must not be accepted as valid progression. Reject invalid stage values before persistent writes. Report the condition with an actionable warning and suspend further progression for the affected selection until corrected, while leaving unrelated application functionality available.

Stage persistence and checkpoint synchronization follow [Selection revisions and atomic writes](30-SELECTION_AND_PERSISTENCE.md#selection-revisions-and-atomic-writes).

## Scheduling interfaces and waits

The hardware-independent scheduling evaluator determines whether an initial or new selection is required, the display date for that selection, and the required reveal stage for a committed selection. It accepts an explicit timezone-aware current timestamp, application configuration, and recovered persistent state.

The public interface is `refrain.evaluate_scheduling(current_time, configuration, state)`. It returns an immutable `SchedulingDecision` whose `SchedulingAction` is `INITIAL_SELECTION`, `NEW_SELECTION`, `ADVANCE_REVEAL`, or `NO_ACTION`. Initial and new selections include `display_date`; decisions for a committed selection include `required_reveal_stage`. Invalid inputs raise `SchedulingEvaluationError` rather than producing a guessed date.

The evaluator calculates the current logical display date from resolved host-local day-start boundary instants as defined under Logical-date evaluation, using `scheduling.day_start`. With a committed selection, a different logical date requires a new selection for that date; the same date retains the selection and advances reveal progress monotonically. Repeated evaluation for one committed logical date does not request another selection. Evaluations are pure; they do not select content, persist state, prepare images, or operate a display.

The canonical ordered `CompositionVisibility` sequence is resolved at selection commitment. Resolve each present field's scheduled local time to an absolute instant using the established civil-time rules before grouping reveal stages. Fields whose resolved instants are identical share one stage, even when their configured wall times differ. Each stage reveals every field scheduled for its instant and retains all fields revealed by preceding stages. The quotation and any fields resolving to its initial instant appear in stage zero. Missing optional fields do not create stages. Source and attribution may reveal in either order. The final stage includes every available optional field.

When committing a new selection, resolve and persist the complete sequence of absolute reveal instants and cumulative visibility. Scheduling evaluation, deadline calculation, image preparation, and recovery use this frozen sequence for the committed selection. They must not independently resolve its authored reveal times using subsequently changed host-timezone rules.

`refrain.resolve_reveal_stages(selection)` returns the committed cumulative visibility sequence. New selections resolve their sequence using the host-local civil-time rules applicable at commitment.

The coordinator uses this same cumulative sequence for image preparation and cache validation. Scheduling evaluation derives its required stage index from the sequence. Stage ordering and equality are determined by resolved instants, not by comparing local `HH:MM` values alone.

The required scheduling contract does not include `DisplayDayBoundary`, `DisplayDayBoundaryObserver`, and the `observed_boundary` argument to `evaluate_scheduling()`. Do not introduce a boundary-history subsystem in their place.

`refrain.next_scheduling_deadline(current_time, configuration, state)` returns the current time immediately when initial selection or a logical-date mismatch requires a selection; otherwise, it returns the next applicable frozen absolute UTC reveal instant or configured day-start boundary resolved using the active host-local timezone. `refrain.wait_for_scheduling_event(deadline, wake_event, ...)` waits for that deadline or an external wake event and returns control for reevaluation after a detected wall-clock adjustment. The coordinator remains responsible for calling `evaluate_scheduling()` and executing its decisions; waiting does not select content, mutate persistent state, prepare images, or operate a display.

The application coordinator executes returned decisions through the selection, persistence, preparation, and display components. For a committed selection whose logical date is unchanged, the required reveal stage is the later of the stage implied by its frozen resolved reveal-stage sequence at the current instant and the persisted highest stage. A new selection starts its own reveal progression. The scheduling context contains the display date and day-start time. Missing optional fields do not add reveal stages, and missed reveal times can advance directly to the latest applicable stage.

A persisted stage beyond the sequence's final index is invalid, and evaluation raises `SchedulingEvaluationError`. The application coordinator must report the failure and suspend reveal progression for the affected selection without treating the invalid value as a valid stage, terminating unrelated destination operations, or replacing committed literary content.

When a reveal advancement is required, the coordinator commits operational progression and synchronizes checkpoint visibility independently of backend acknowledgement. It then requests the corresponding prepared variant from each participating destination. Scheduling evaluation does not determine whether an image was successfully presented.

A failed display update does not invalidate the committed selection or its prepared images.

A subsequent successful update may skip intermediate stages and present the latest required image.

## Scheduling and delivery boundaries

The display scheduler determines which reveal stage should currently be presented. Each destination receives the prepared output image matching its output specification and effective presentation requirements.

Normal scheduled reveals select prepared images rather than invoking the renderer or consulting the content library. Image regeneration when required is a separate preparation responsibility.

The display backend owns physical display communication and recovery.

The committed daily selection remains authoritative when prepared images need to be recovered. The matching complete publication checkpoint supplies persisted destination-independent artistic choices, subject to the approved checkpoint-loss recovery rules.

Time and configuration are inputs to the relevant responsibilities. Neither is an independent source of quotation-selection policy.

Publication admission, destination acknowledgement, per-instance serialization, coalescing, retries, and backend failure isolation are defined under [Scheduled delivery and acknowledgement](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#scheduled-delivery-and-acknowledgement).

## Startup and daily transitions

Normal startup performs the following logical operations:

1. Load application configuration, accepting documented defaults and recoverable configuration problems while reporting diagnostics.
2. Recover and validate persistent operational state, if available.
3. Evaluate whether an existing committed selection remains active under the display-day transition rules.
4. When a new selection is required, complete content discovery and validation, constructing an effective library from accepted entries.
5. Commit a new selection when eligible content is available. When the effective library is usable but contains no quotation eligible for the current logical date, use the no-eligible-content fallback defined below without creating a selection.
6. For a committed selection, recover or construct its content and presentation checkpoints under the established state-first persistence and recovery requirements.
7. Verify that all required reveal-stage images are available and valid. Reuse compatible complete image sets or regenerate them from the committed selection, completed checkpoint, current applicable configuration, and available resources. Prepare the no-eligible-content fallback independently when applicable.
8. Initialize configured display backends independently.
9. If automatic information-view presentation is enabled, prepare and request publication of the information view.
10. Observe the bounded information-view startup behavior and transition to daily presentation when its interval expires, or proceed directly when automatic presentation is disabled or cannot be completed.
11. Determine the currently required daily reveal stage, respecting committed reveal progression and the current logical display date, or select the fully revealed fallback presentation when applicable.
12. Independently request publication of the corresponding prepared image to every participating destination.
13. Continue operating until shutdown.

The application may prepare or recover the committed daily presentation before or during information-view publication. Information-view presentation does not defer required selection commitment or alter authoritative reveal progression.

The information-view duration begins with the first successful publication acknowledgement, not with process launch or the beginning of image preparation.

An unsuccessful initial information-view publication attempt must not indefinitely delay ordinary presentation.

The transition to daily presentation requests the image appropriate to the current scheduling state. Missed intermediate reveal stages are not replayed.

Recoverable configuration problems and individual invalid content files or entries must not prevent otherwise valid operation.

A valid committed selection does not require its original content entry or a currently usable content library to remain available.

If no committed selection exists and a usable effective content library cannot be constructed, startup cannot establish a daily presentation and must report an actionable error.

If a new selection is required during continuous operation but content directories are missing or inaccessible, source enumeration is incomplete, or the effective content library contains no valid quotations, Refrain must not clear repetition history, commit an empty selection, or replace previously committed operational state. It must preserve existing prepared images where practical and report the failure.

When a new selection is required during continuous operation but no usable effective content library can be constructed, the application coordinator retries the selection attempt after a five-minute monotonic delay. While the same logical display date remains current, scheduling reevaluation or an external wake event must not bypass this retry delay.

A change to a different logical display date permits an immediate new selection attempt, regardless of the preceding retry delay. Successful content recovery resumes normal selection and scheduling.

The retry deadline is process-local coordinator state. Do not persist it or incorporate retry policy into the pure scheduling evaluator. Restarting permits an immediate attempt.

This retry behavior does not apply to a healthy effective library with no quotation eligible for the current logical display date. That condition continues to use the no-eligible-content fallback without repeated same-date selection attempts.

Startup without an existing committed selection and without a usable content library retains its established actionable startup error.

### No-eligible-content fallback

When content discovery completes successfully and produces a usable effective library containing valid quotations but none eligible for the current logical display date, Refrain must present a fallback instead of treating the library as unavailable.

The fallback uses the exact curated quotation supplied by the application for the information view, attributed to `Forge, Refrain Development Team`. Render it using the normal literary presentation facilities with all available literary fields fully revealed. It is not the branded information view and does not use its runtime-information layout.

The fallback is not a committed daily selection. It must not create a synthetic content entry or selection revision, modify authoritative operational state or repetition history, append global history, or advance reveal progress.

A previously committed selection for another logical date remains unchanged in persistent state. Presenting the fallback must not misrepresent that earlier selection as belonging to the current display date.

Do not repeatedly attempt a new selection for the same logical date during ordinary operation after determining that the healthy effective library has no eligible quotation. Evaluate content eligibility again for the next logical display date.

The fallback does not apply to missing or inaccessible content sources, incomplete discovery or enumeration, or an effective library containing no valid quotations. These conditions retain the established unavailable-library error and preservation behavior.

### Display-day transition

At a recognized display-day transition, the application:

1. Determines the new display date.
2. Completes content discovery and validation, constructing an effective content library from accepted entries.
3. If no quotation is eligible in an otherwise usable effective library, prepares the no-eligible-content fallback without changing committed operational state.
4. Otherwise, removes obsolete repetition identities based on the effective library and performs eligibility, repetition, priority, and random quotation selection.
5. Creates and atomically commits the daily selection record, updated repetition history, next selection revision, initial reveal progress, and required scheduling context.
6. Persists the content-only publication checkpoint, then resolves and persists the complete content-and-presentation checkpoint before destination-specific preparation.
7. Records the committed selection in global history on a best-effort basis.
8. Generates or reuses all required compatible reveal-stage images.
9. Determines the stage appropriate to the current time.
10. Independently requests presentation of the corresponding image through each participating backend.

Steps concerning selection commitment, checkpoints, and global history do not apply to the no-eligible-content fallback.

An unavailable or empty effective content library prevents a new selection without modifying committed operational state. A healthy library with no eligible quotation follows the fallback behavior instead.

Selection is complete at operational-state commitment, independently of whether checkpoint persistence, global-history recording, image preparation, or display communication subsequently succeeds.

A failure after commitment must not trigger reselection.

Presentation completion is tracked independently for each destination and does not change the committed selection.

Failure to initialize an individual display backend must not prevent other configured destinations from becoming operational. Failures affecting one destination on a shared backend instance must not be reported as successful for other destinations or silently treated as failures of unrelated backend instances.

The implementation may organize these operations differently provided their externally observable behavior and required persistence ordering are preserved.

Automated tests must cover:

- unavailable sources, incomplete discovery, and libraries with no valid quotations;
- five-minute monotonic retry timing, external wakes, logical-date changes, restart, successful content recovery, and isolation from healthy no-eligible-content fallback;
- healthy effective libraries with no eligible quotation, including the exact information-view quotation, required attribution, full reveal, and normal literary rendering;
- no synthetic selection, repetition-history mutation, publication checkpoint update, or global-history event for the fallback;
- preservation of an existing committed selection for another display date during fallback presentation;
- retry of ordinary eligibility at the next logical display date;
- successful selection with individual invalid files or entries excluded;
- state-first checkpoint construction and recovery during startup and display-day transitions;
- independently failed and healthy destinations during startup and ordinary publication.

## Startup information-view timing

The information view is independent of the committed daily selection. Preparing or displaying it must not create a new selection, modify selection histories or publication checkpoints, or advance reveal progress.

Automatic presentation occurs once on each application start, subject to the configured duration. It does not repeat at ordinary display-day boundaries.

The automatic duration defaults to 60 seconds. A duration of zero disables automatic presentation without disabling the information-view capability.

The configured duration is measured using elapsed monotonic time beginning when the first backend successfully acknowledges publication of the information view.

Publication to other backends remains independent. A slow or unavailable backend must not delay the transition to daily presentation for other destinations.

The initial opportunity to obtain a successful information-view acknowledgement must be bounded. If no backend succeeds within that period, Refrain must stop waiting for the information-view interval and proceed toward normal daily presentation.

When the configured information-view interval expires, or the bounded initial attempt period ends without success, pending information-view jobs that have not started backend publication must expire rather than delaying the currently required scheduled presentation.

An information-view publication already active on a backend instance must be allowed to complete safely. The next required scheduled presentation for that instance follows the active operation without overlapping it. Other backend instances proceed independently.

When the information-view interval expires, Refrain determines the currently required daily presentation using the normal scheduling and recovery rules. It does not replay reveal stages that are no longer required.

An information-view preparation or publication failure must not invalidate the committed selection or prevent ordinary daily presentation when a functional display destination remains available.

The information view may be requested independently of automatic startup behavior, but it is not one of the defined runtime-control operations.

Use the existing display publication coordinator to distribute prepared information-view images to configured backends. Do not create a separate backend-publication mechanism or reset display backends merely to transition between information and daily views.

The startup information-view interval is transient application state. It does not require durable storage or modification of the committed daily selection.

Do not require successful publication by every backend before the information-view interval begins or ends.

Preserve scheduled-presentation acknowledgement independently; information-view publication must not replace or invalidate it. Preserve per-instance serialization, independent backend execution, pending scheduled-update coalescing, and safe handling of active hardware transfers.

Information-view preparation failures must be reported without preventing ordinary daily presentation when that remains possible.

Include hardware-independent automated tests covering:

- default, disabled, and explicitly configured information-view durations;
- invalid duration values and documented fallback behavior;
- preservation of committed selection, repetition history, checkpoint data, and reveal progression;
- preservation of normal scheduled-publication acknowledgement when an information view is published;
- publication to multiple independent backends and destinations sharing a backend instance;
- timer start after the first successful publication acknowledgement;
- wall-clock adjustments during the information-view interval;
- bounded initial publication attempts when no backend succeeds;
- expiration of pending information-view jobs that have not started;
- completion of an active information-view update before the next scheduled update on the same backend instance;
- independent progress by other backend instances during slow information-view publication;
- transition to the latest required daily presentation after missed reveal events;
- failure isolation and shutdown during information-view presentation.

## Normal operation and waiting

After successful preparation, the application waits for the next meaningful scheduling event.

Scheduled reveal updates select an existing prepared image.

Normal operation must not require repeated content-library access or repeated rendering while the committed selection and its compatible prepared images remain usable.

Clock adjustments are evaluated according to the display-day and reveal-progression rules.

The application must not rely on busy waiting to determine ordinary reveal times.

Explicit local quotation inspection and one-shot reveal-stage rendering belong to `refrain-viewer` and are defined by the [public CLI](../CLI.md).

## Lifecycle recovery

Recovery is performed according to the stage at which an interruption occurred.

An interruption before successful operational-state selection commitment permits normal selection to be repeated when required.

An interruption after commitment preserves the committed selection, its revision, repetition history, effective reveal schedule, frozen resolved reveal-stage sequence, and highest reached reveal stage.

On startup, recover and validate operational state before publication checkpoints or prepared images. The publication checkpoint must match the current committed selection and satisfy its required schema form.

A valid content-only checkpoint permits completion of destination-independent artistic resolution. A valid complete presentation checkpoint preserves its resolved artistic choices across restart and destination preparation, regardless of subsequent changes to resource pools or configuration.

A missing, damaged, invalid, or stale publication checkpoint must be reconstructed from authoritative operational state. When the sole durable record of resolved artistic choices has been lost, resolve those choices again and emit an actionable warning that the resulting appearance may differ. Recovery must not reselect literary content, increment the revision, change repetition history, or reduce reveal progress.

If checkpoint visibility is behind committed operational reveal progression, synchronize visibility from operational state while preserving otherwise valid artistic choices.

Checkpoint construction and recovery must follow the state-first persistence requirements defined in [Selection and Persistence](30-SELECTION_AND_PERSISTENCE.md#recovery-and-state-compatibility).

Missing or incomplete prepared variants are regenerated as complete compatible stage sets from the committed selection, valid completed presentation checkpoint, current applicable destination overrides, output requirements, and available resources. A compatible healthy cache remains reusable without checking for configuration or asset changes.

Regeneration must not independently reselect persisted artistic choices while their authoritative checkpoint remains valid. When checkpoint loss required new artistic resolution, previously prepared artifacts must not be reused solely because their selection revision and output dimensions match; preparation compatibility must reflect the resolved presentation requirements.

Recoverable destination and backend-service failures use bounded retries without delaying other backend instances. Exhausted retries wait for a subsequent publication opportunity, and destination unavailability does not terminate the resident runtime.

After restart, each available participating destination is supplied with its currently required prepared variant without relying on persisted destination-specific presentation acknowledgements.

Recovery must not introduce additional history entries or silently substitute literary content.

Display backend failures must remain isolated from other destinations and must not invalidate content selection or persistent history. A shared backend-instance failure must affect only the destinations actually dependent on that instance.

Rendering failures must not cause reselection after a daily selection has been committed.

Content-library changes or validation failures must not modify an already committed daily selection.

An unrecoverable configuration or operational-state error must be reported clearly rather than disguised as normal operation.

An existing physical e-paper image must be preserved when recovery cannot safely complete.

Automated tests must cover recovery across selection commitment, both publication checkpoint boundaries, reveal advancement, checkpoint visibility synchronization, cache regeneration, backend failures, and application restart. Tests must distinguish loss of an artistic checkpoint from loss of a prepared-image cache and verify preservation of valid authoritative state.

## Shutdown coordination

Normal shutdown must stop admission of new presentation requests, stop recoverable retries, and safely release resources owned by every configured backend instance.

Use one 60-second foreground shutdown deadline for the complete coordination and worker-drain operation, not an independent 60-second allowance for each backend, destination, or worker.

Admitted one-shot publication operations remain owned by the resident during shutdown. Allow them to reach terminal outcomes within the remaining shutdown deadline while preventing new admission. Unstarted or unadmitted requests must not indefinitely delay backend cleanup.

When the foreground deadline expires, report outstanding per-destination publication outcomes as unconfirmed rather than successful or definitively failed. A timeout does not prove that the corresponding backend publication did not occur.

Backend shutdown must account for active publication operations without permitting unsafe overlapping hardware access.

Do not interrupt a backend operation or invoke that backend's cleanup concurrently with an active publication on the same instance. This applies when one backend instance serves multiple named destinations.

If a synchronous publication remains blocked at the deadline, its worker retains the active image and backend resources until the operation returns or the process exits. The worker must attempt safe deferred cleanup if the operation later returns. Do not free resources still owned by an active operation.

Failure to close one backend instance must not prevent cleanup attempts for other independent backend instances.

Retain exclusive resident ownership while backend workers or deferred cleanup still require protected resources. Release ownership only after safe cleanup completes or allow the operating system to release it on process exit. Do not expose the installation as available to another resident while protected backend operations remain active.

Shutdown must not intentionally erase retained e-paper images.

Committed operational state and the valid publication checkpoint remain available for subsequent startup recovery. Prepared images are disposable cache entries that may be regenerated using the established recovery rules.

Automated tests must cover:

- the single 60-second foreground deadline across multiple backend workers;
- safe completion or deferred cleanup of blocked active publications without concurrent backend access;
- unconfirmed per-destination outcomes when the deadline expires;
- admitted one-shot work continuing independently of disconnected clients;
- independent cleanup of healthy backend instances when another instance remains blocked;
- retention of active image and backend resources until safe release;
- exclusive ownership throughout outstanding protected operations;
- preservation of committed state, publication checkpoints, and retained e-paper imagery during shutdown.