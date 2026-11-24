# Image Server

## Component responsibility

`refrain-image-server` is a standalone HTTP consumer of Refrain filesystem publications. It provides read-only access to the current verified PNG image for each explicitly configured `publish` destination.

The service operates independently of the resident application. Resident publication success depends on filesystem publication commitment, not image-server availability. The resident does not start, stop, or supervise the image server.

The image server does not select quotations, render images, advance reveal schedules, or acknowledge destination publication. HTTP client activity does not affect resident scheduling or publication.

Use Python standard-library HTTP server facilities. Do not introduce an additional HTTP server dependency, web application framework, or general-purpose HTTP service abstraction.

## Configuration and startup

The service loads the selected application configuration, or the standard configuration when none is selected.

Startup requires an `image-server` section with a valid, nonempty `destinations` sequence referencing configured `publish` destinations. Missing or invalid required configuration prevents startup with an actionable diagnostic. Invalid optional settings follow the schema's warning-and-default rules.

Validate configuration and resolve applicable publication paths before initializing the HTTP listener.

Load configuration once at startup. Configuration changes require a service restart.

Support configured IPv4 addresses, IPv6 addresses, and hostnames. When hostname resolution produces multiple addresses, attempt to bind them in resolution order until one succeeds. Establish exactly one listening socket.

Missing publication directories, unavailable publications, and invalid current datasets do not prevent service startup.

The service can start and serve verified publications independently of resident availability.

Configuration fields and validation are defined in [Application Configuration](../schemas/CONFIGURATION.md#independent-image-server-settings). Command-line invocation and process exit codes belong to [CLI](../CLI.md#independent-image-server). Service supervision and filesystem permissions belong to [Installation and Service Operation](80-INSTALLATION_AND_SERVICE_OPERATION.md).

## Publication consumption

The image server consumes only the destinations identified in its configuration.

Use the shared publication reader to read and validate the complete current dataset for every supported request targeting a configured destination, including conditional requests and HEAD requests.

Follow the validation, consistency, bounded allocation, and retry requirements in [Filesystem Publication and Consumers](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#consumer-validation).

Serve the exact verified PNG bytes associated with the accepted dataset. Do not reopen the published image for response delivery after verification.

Do not resize, re-encode, convert, or otherwise modify image bytes.

Do not retain publication data between requests. Do not introduce background polling, filesystem watchers, publication caches, or cache invalidation mechanisms.

Incomplete, inconsistent, or unverified datasets must not be exposed as current publications. Do not substitute a previously verified image when the current publication is unavailable or invalid.

Publication unavailability for one destination must not prevent retrieval from other configured destinations.

The service must not modify publication datasets, authoritative operational state, or publication checkpoints. It does not acquire the resident ownership lock.

## HTTP interface

### Resource routing

Expose exactly one image resource for each destination explicitly selected by the image-server configuration:

`/destination/{destination_id}/current`

Destination identifiers are case-sensitive.

Resolve requested destinations only against the configured destination set. Never derive filesystem paths directly from unvalidated request data.

Do not expose publication metadata, manifests, destination enumeration, directory listings, historical publications, arbitrary files, or resident control operations.

HTTP binding controls network exposure but provides neither authentication nor encryption. Network-accessible deployments must be limited to trusted local networks and must not be exposed directly to untrusted networks or the public Internet.

HTTP requests must not permit filesystem traversal, publication modification, resident control, or disclosure of application configuration, content libraries, operational state, or credentials.

### Request methods and responses

Support GET and HEAD.

HEAD must produce the same response status and representation headers as an equivalent GET request without transmitting a response body.

Use the following application response statuses:

| Status | Condition |
|---|---|
| 200 OK | A verified current image is available and conditional request evaluation does not produce a 304 response. |
| 304 Not Modified | A verified current image satisfies the request's `If-None-Match` condition. |
| 400 Bad Request | Malformed HTTP request. |
| 404 Not Found | Unrecognized resource path or unconfigured destination. |
| 405 Method Not Allowed | Unsupported HTTP method. |
| 503 Service Unavailable | Current publication unavailable or invalid, or request-processing capacity or verification allowance exhausted. |

Standard HTTP protocol parsing and request-size errors may use their applicable HTTP status codes.

Responses with status 405 must include `Allow: GET, HEAD`.

Error responses must not disclose internal filesystem paths, configuration values, exception details, or publication metadata.

Successful 200 responses include:

- `Content-Type: image/png`
- `Content-Length` containing the exact encoded PNG byte count.
- `ETag` containing the strong entity tag defined below.
- `Cache-Control: no-cache`

Responses with status 304 include the current `ETag` and `Cache-Control: no-cache`, without a response body.

Error responses include `Cache-Control: no-store`.

### Conditional requests

Use the verified manifest's lowercase `image_sha256` value enclosed in double quotes as the strong HTTP entity tag.

Entity tags identify exact PNG representations, not publication events. Distinct publication events containing identical PNG bytes therefore have identical entity tags.

Support `If-None-Match` for GET and HEAD using standard HTTP weak comparison semantics, including multiple entity tags and the wildcard.

Complete current-publication verification before evaluating conditional requests. Never return 304 for an unavailable, invalid, or unverified current publication.

Do not implement partial image delivery, response compression, or content negotiation.

## Request execution and resource limits

Use bounded concurrent request handling with serialized publication verification.

Apply the following service-specific limits:

| Resource | Limit |
|---|---:|
| Concurrent request handlers | 4 |
| Concurrent publication verifications | 1 |
| Requests per connection | 1 |
| Complete HTTP request reception | 10 seconds |
| Waiting for and completing publication verification | 60 seconds |
| Complete HTTP response transmission | 120 seconds |
| Network write inactivity | 15 seconds |

Define each service-specific limit as a named constant with one authoritative definition. These limits are not application configuration fields.

Enforce the concurrent handler limit before creating additional request-handler threads. When capacity is exhausted, reject additional connections. Return 503 when a response can be delivered safely without exceeding the resource limits; otherwise close the connection.

Do not maintain an unbounded application-level request queue.

Each request-processing phase has an independent deadline. Time spent receiving a request or waiting for publication verification does not reduce the response transmission allowance.

Use monotonic time for deadline measurement.

Waiting for the verification slot and all bounded publication-reader attempts share the verification allowance.

Do not start verification after its allowance has expired. If the verification deadline expires during an active verification, do not deliver its eventual result as a successful response.

Do not forcibly terminate a thread performing filesystem operations. A verification that cannot be interrupted safely retains its verification slot until it finishes.

Release the verification slot when verification completes. Network response transmission must not retain the verification slot.

Retain the verified encoded image bytes only for the lifetime of the affected request. Release decoded image objects and other verification resources when no longer required.

Enforce reception and transmission deadlines by interrupting stalled network I/O. The write-inactivity timeout applies independently of the complete response transmission deadline.

Do not allow intermittent network progress to extend the complete reception or transmission deadline.

Close the connection after completing or terminating its single request.

Client disconnection, timeout, or request failure must release request-owned resources when safe to do so.

## Lifecycle and failure handling

### Startup and runtime failures

Missing or invalid required configuration is a configuration failure.

Failure to initialize the HTTP listener after exhausting applicable binding attempts is a service failure.

Both prevent successful startup and produce an actionable diagnostic.

Missing, inaccessible, invalid, or temporarily inconsistent publication datasets are request-level failures. Report unavailability without terminating the service. Subsequent requests independently attempt to verify the current publication.

Client disconnects and request-processing timeouts must not terminate the service.

Unexpected request-handler exceptions must be logged and terminate only the affected request.

Unrecoverable listener or service failures must produce an actionable diagnostic and terminate the service unsuccessfully.

Use the process exit codes defined in [CLI](../CLI.md#independent-image-server).

Do not implement internal listener restart loops, resident readiness checks, service supervision, or application-level watchdogs.

### Shutdown

On shutdown:

1. Stop accepting new connections and admitting new requests.
2. Cancel requests waiting for publication verification.
3. Allow active requests to complete within a single five-second graceful shutdown allowance.
4. Close remaining client connections and release service resources.
5. Terminate the process without waiting indefinitely for blocked request handlers or filesystem operations.

Define the graceful shutdown allowance as a named constant.

Do not begin new publication verifications after shutdown has been requested.

The service must not require completion of blocked read-only filesystem operations before process termination.

Normal shutdown is successful regardless of interrupted client requests.

Do not remove, repair, or otherwise modify publication data during shutdown.

## Logging and diagnostics

Follow [Development Standards](../DEVELOPMENT_STANDARDS.md#logging-and-diagnostics).

Use the following diagnostic levels:

| Event | Level |
|---|---|
| Successful startup, listening address, and configured destination IDs | INFO |
| Normal shutdown | INFO |
| Individual HTTP requests and response status | DEBUG |
| Client disconnections and request timeouts | DEBUG |
| Request-handler capacity exhaustion | DEBUG |
| Missing current publication | DEBUG |
| Invalid or inaccessible current publication | WARNING |
| Invalid optional configuration | WARNING |
| Unexpected request-handler exception | ERROR |
| Fatal configuration, listener, or service failure | ERROR |

Maintain bounded, process-local diagnostic state for configured destinations.

Log the first occurrence of a reportable publication failure. Suppress repeated warnings for equivalent failures affecting the same destination. Log materially changed failure conditions.

Log successful verification following a reported publication failure at INFO level and clear the corresponding failure diagnostic state.

Diagnostic state must not retain publication datasets, affect verification decisions, or change HTTP responses.

Do not log literary content, action payloads, raw HTTP request headers, or image data.

## Validation

Hardware-independent automated tests must cover:

- Required configuration acceptance and rejection.
- Destination reference validation and optional-setting defaults.
- Configuration isolation from resident-only services.
- Configuration, service-failure, and successful-shutdown exit codes.
- Independent startup with and without existing publication datasets.
- IPv4, IPv6, and hostname listener initialization where supported.
- Listener initialization and runtime failures.
- Resource routing, case-sensitive destination IDs, unconfigured destinations, and malformed paths.
- GET and HEAD response statuses, headers, and body semantics.
- Delivery of exact verified PNG bytes.
- Rejection of unsupported request methods.
- Strong entity-tag generation from verified image hashes.
- Conditional requests with matching and nonmatching tags, weak comparisons, multiple tags, and the wildcard.
- Identical PNG representations across distinct publication events.
- Rejection of conditional requests for invalid or unavailable publications despite matching previous entity tags.
- Scheduled and transient publication delivery.
- Missing, damaged, inaccessible, and concurrently replaced publication datasets.
- Independent destination availability and recovery.
- Concurrent handler limits and overload rejection.
- Serialized publication verification with overlapping response transmission.
- Independent request-phase deadlines and network write-inactivity timeout.
- Verification-allowance exhaustion without late successful delivery.
- Client disconnection and request-resource release.
- Bounded shutdown with active, queued, and blocked requests.
- Diagnostic levels, repeated-warning suppression, changed failure conditions, and recovery diagnostics.
- Read-only filesystem operation, traversal rejection, and prevention of unintended data exposure.
- Operation independently of the resident.

Exercise the actual HTTP interface through loopback listeners using operating-system-assigned ephemeral ports. Mocked request handlers alone are insufficient.

Use the shared publication writer and reader in integration tests exercising dataset integrity and concurrent publication.

Tests may substitute shorter resource-limit constants and controlled blocking operations. Prefer deterministic synchronization over arbitrary timing delays when testing concurrent operations.

Run applicable automated tests on Windows and Linux. Report platform-specific validation limitations explicitly.

Automated tests must not require systemd, external network availability, physical display hardware, or embedded HTTP clients.

Deployment validation on supported Raspberry Pi OS installations must establish:

- Independent systemd service management.
- Restart prevention following configuration failure.
- Supervisor-managed recovery following unexpected process termination.
- Successful image retrieval over a trusted local network.
- Publication verification performance and memory consumption alongside the resident.

Physical embedded-client validation is not required to complete image-server implementation.