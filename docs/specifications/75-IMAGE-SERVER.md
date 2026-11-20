# Image Server

## Component responsibility

`refrain-image-server` is a standalone HTTP consumer of Refrain filesystem publications. It provides access to the current verified PNG image for each configured `publish` destination.

The service operates independently of the resident application. Resident publication success depends on filesystem publication commitment, not image-server availability. The resident does not start, stop, or supervise the image server.

## Configuration and lifecycle

The service loads the selected application configuration, or the standard configuration when none is selected.

Startup requires a valid `image-server` configuration section identifying at least one configured `publish` destination. Missing or invalid configuration prevents startup and produces an actionable diagnostic.

Configuration fields and validation are defined in [Application Configuration](../schemas/CONFIGURATION.md#independent-image-server-settings). Command-line invocation belongs to [CLI](../CLI.md). Service supervision and filesystem permissions belong to [Installation and Service Operation](80-INSTALLATION_AND_SERVICE_OPERATION.md).

## Publication consumption

The image server consumes only the destinations identified in its configuration.

It reads and validates completed publication datasets according to [Filesystem Publication and Consumers](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#consumer-validation). Incomplete, inconsistent, or unverified datasets must not be exposed as current publications.

The service must not modify publication datasets, authoritative operational state, or publication checkpoints. It does not acquire the resident ownership lock.

## HTTP delivery

The service provides read-only HTTP access to verified published images.

HTTP requests must not permit filesystem traversal, publication modification, resident control, or disclosure of application configuration, content libraries, operational state, or credentials.

Unavailable or invalid current publications must produce an explicit unavailable result rather than unverified image content.

The service does not select quotations, render images, advance reveal schedules, or acknowledge destination publication. HTTP client activity does not affect resident scheduling or publication.

## Validation

Hardware-independent automated tests must cover configuration acceptance, independent startup and shutdown, verified image delivery, invalid and unavailable publications, read-only filesystem access, and listener failures.

Tests must not require external network availability or physical display hardware.