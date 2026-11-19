# Installation and Service Operation

## Platform paths and publication root

The optional `storage.publish` setting overrides the publication root using the existing storage-path semantics: absolute paths are used as specified and relative paths are resolved from the selected configuration file. Its omitted default is a platform-standard per-user operational-data path:

| Platform | Default publication root |
|---|---|
| Linux | `$XDG_STATE_HOME/refrain/publish`, using the existing per-user fallback when the variable is missing, empty, or relative |
| Windows | `%LOCALAPPDATA%\Refrain\Publish` |
| macOS | `~/Library/Application Support/Refrain/Publish` |

The application-path resolver determines the effective root independently of the working directory. This extends the existing platform-aware path resolver rather than introducing a second path-selection mechanism. Standard maintenance commands always target the platform-standard installation locations, not a custom `storage.publish` override.

Use platform-standard per-user application-data facilities as the defaults for configuration, operational state, global history, and derived artifacts. Resolve standard locations at the command-line boundary without adding a dependency solely for path selection. Optional runtime storage overrides belong to application configuration; keep lower-level application and persistence interfaces explicit about the effective paths they receive.

On Linux, honor absolute XDG configuration, state, and cache bases and use the per-user fallbacks when those variables are missing, empty, or relative. On Windows, use the configured roaming and local application-data directories. Other supported desktop platforms should use their established per-user locations.

Use ordinary operating-system facilities where they satisfy the requirement. In particular:

- use systemd for supervised service operation;
- use standard process streams for application logging;
- use the local filesystem for ordinary application storage;
- use the operating system's local-time facilities for local scheduling.

Avoid creating a custom service manager, log daemon, database service, or scheduler without a demonstrated need.

Use `pathlib` for filesystem path handling.

Do not assume that application files, content files, persistent state, and generated images are located in the same directory.

Keep configuration and user content separate from operational state, global history, and derived artifacts. Custom fonts, backgrounds, and decorations are user-owned resources under `assets/{fonts,backgrounds,decorations}/` beside the effective configuration file; they are separate from bundled package resources and generated artifacts. Manifest references are relative to their package and must not escape it. Content-directory paths retain their configuration-relative or explicit-absolute semantics. Configuration resolves explicit relative storage paths against its own file; the command-line entry point combines these optional values independently with platform-standard defaults. Application functions continue to receive effective paths rather than performing implicit home-directory lookup.

Avoid assumptions tied to a particular username, home directory, mount point, or installation path.

Resolve relative paths consistently and document their interpretation.

The planned publication root extends the existing platform-aware path resolver. Its default is `$XDG_STATE_HOME/refrain/publish` on Linux, using the existing per-user fallback; `%LOCALAPPDATA%\Refrain\Publish` on Windows; and `~/Library/Application Support/Refrain/Publish` on macOS. An explicit `storage.publish` path follows the established storage semantics, including configuration-relative resolution. Do not add a separate path-selection mechanism or use a Linux installation path as a cross-platform default.

## Installed package resources

Wheel and source-distribution tests must verify that bundled manifests, referenced images and fonts, applicable font licenses, and `assets/README.md` are included. Installed-package discovery must use package-resource APIs and must not depend on a source checkout.

## Installation requirements

For supported Linux deployments, use an unprivileged application identity and systemd supervision. Hardware setup and permissions are specified in the packaged Waveshare backend guide.

The installed package includes a complete default configuration and sample content library as package resources. Explicit initialization copies these resources to standard per-user locations, but ordinary startup never performs installation or repairs missing user configuration.

A package repository, installer framework, or container runtime is not required.

Deployment instructions must identify the supported operating system, system dependencies, Python environment, configuration locations, and persistent-state requirements.

Installation must not depend on the developer's local directory structure.

Initialization is noninteractive and repeatable. Preflight every required path and destination type before writing. Reuse real directories, preserve an existing regular configuration file, and initially install samples only into a missing or empty standard content directory. Leave ordinary pre-existing nonempty content uninspected and untouched. A retry after interrupted sample installation may resume in the now-nonempty directory only when the temporary marker matches the packaged sample set and every existing expected sample matches its packaged bytes. Create only missing sample files exclusively and remove the marker after the sample set is complete. An invalid marker or conflicting sample requires manual inspection rather than treating arbitrary content as an interrupted installation. Create missing standard user asset category directories, accepting existing nonempty directories without inspecting or modifying their files; never copy bundled visual resources into them. Reuse state and cache directories without modifying existing state, history, or artifact files. Create the standard publication root without replacing its existing contents. Refuse links or unexpected objects that redirect or block safe access. On failure, report created destinations and leave them in place so a later initialization can retry safely when ownership is established.

Reset and purge are destructive standard-path operations and require exact interactive confirmation; they must not offer a noninteractive bypass. Resolve deletion scope only from platform-standard Refrain-owned locations, never from configured runtime storage values. Do not remove shared parent directories or follow a POSIX symlink, Windows junction, reparse point, or other filesystem indirection into an external tree. A linked standard root cannot establish safe ownership and must be refused; links encountered inside an owned tree must never be traversed as directories. Report the failed operation and affected path on permission or I/O errors, and do not perform out-of-scope recovery.

Reset removes only the standard state file, active and rotated global-history files, and Refrain-generated cache contents while preserving configuration, content, the complete user-assets tree, publication storage, and standard directory structure. Purge removes the Refrain-owned standard directory trees and their contents, including standard user assets under the configuration directory and the complete standard publication root after explicit confirmation. Configured custom publication paths are never reset or purged by these commands. Both operations are intended for use while Refrain is stopped; their standard-installation mutation paths must also participate in the runtime ownership lock described under [Resident ownership and authenticated control](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#resident-ownership-and-authenticated-control). Consumer shutdown is operator-managed, not enforced: consumers do not acquire the runtime ownership lock, and maintenance does not inspect or stop operating-system services. Operators must stop any consumer that may read data before purging that data or replacing its installation. Refrain does not guarantee safe concurrent reads if a consumer is left running. This ownership lock protects against cooperating Refrain processes, not arbitrary concurrent hostile filesystem mutation.

## Initialization and destructive maintenance

`refrain --initialize` creates the standard publication root without replacing or cleaning existing contents. `refrain --reset` preserves publication storage. `refrain --purge` removes the entire standard publication root and everything beneath it, including all destination directories, completed publications, and temporary files. Existing ownership locking, confirmation, idempotence, and filesystem-safety requirements apply. Services do not acquire the resident's exclusive runtime lock; destructive maintenance must therefore be coordinated with running consumers, which must be stopped before their publication data or installation is removed or replaced.

Consumer shutdown coordination is operator-managed, not enforced by Refrain. The resident ownership lock excludes a resident runtime and standard installation-maintenance command from each other; consumers do not acquire that lock, and maintenance does not query or stop system services. Operators must stop any consumer that may read data before purging that data or replacing its installation. This requirement does not promise protection from a consumer left running or from arbitrary concurrent filesystem access.

The command-line entry point resolves omitted runtime storage paths to the independently defined platform-standard per-user locations, regardless of the current working directory. Optional state, history, artifact, and publication-root overrides belong to application configuration; each explicit relative path is resolved from the selected configuration file, while each omitted value retains its own platform-standard default. Selecting another configuration file does not itself relocate storage, and a custom state path does not relocate history. The entry point passes effective paths to application and storage components, which do not infer platform locations.

Normal startup requires the selected configuration file to exist. It does not substitute the packaged default configuration, create an installation directory structure, or copy sample content. Relative content paths remain based on the selected configuration file. Custom visual resources are discovered by category beneath `assets/fonts/`, `assets/backgrounds/`, or `assets/decorations/` beside that effective configuration file and are referenced by registered identifier. Manifest image and font references are relative to their containing package and confined to that package. There is no arbitrary absolute-path custom-resource registration interface.

The explicit, noninteractive `--initialize` operation manages only standard per-user destinations and ignores runtime storage settings in configuration. It reuses existing real directories, preserves an existing regular `config.yaml` byte-for-byte, and copies the packaged default only when that file is absent. It installs packaged sample content only when the standard content directory is missing or empty; ordinary pre-existing nonempty content is left untouched and uninspected. An interrupted sample installation may be resumed only when its installation marker and every existing expected sample file can be positively verified; missing expected files may then be installed without overwriting existing files. Invalid markers, conflicting sample contents, or uncertain ownership require manual inspection rather than automatic repair. It creates missing `assets/`, `assets/fonts/`, `assets/backgrounds/`, and `assets/decorations/` directories while preserving any existing contents. It copies no bundled visual resources into user assets and does not validate files already there. Initialization reuses existing state and cache directories and never modifies existing state, history, or prepared artifacts. It creates the standard publication root without replacing or cleaning its existing contents and rejects unsafe publication paths. New files use exclusive creation, no empty state or history files are created, and failures leave already-created destinations in place for a safe retry. Initialization does not start selection, preparation, or display lifecycle operations.

Configuration and content remain user-owned inputs. Operational state and global history remain authoritative and historical persistence respectively; prepared artifacts remain derived output. Runtime creation of those persistence and artifact files remains owned by their existing components.

`--reset` and `--purge` are separate interactive operations for the standard per-user installation and must be run while Refrain is stopped. Reset removes only the platform-standard operational-state file, global-history records and rotations, and generated cache contents while preserving configuration, content, all user assets, publication storage, and installation directories; configured custom storage paths are untouched. Purge removes the Refrain-owned standard configuration, operational, cache, and publication directory trees, including configuration, content, and assets stored beneath the standard configuration directory and every destination and temporary file beneath the standard publication root; it does not follow configured storage paths or remove shared application-data parents. Neither operation reads runtime storage settings or starts the application lifecycle. Before purging or otherwise removing consumer-readable publication data, independent consumer services must be stopped using the operating-system service facilities that supervise them. Their deletion checks and confirmation requirements are described in [Initialization and destructive maintenance](#initialization-and-destructive-maintenance).

Platform paths, installation, and service operation are documented under [Platform paths and publication root](#platform-paths-and-publication-root), [Installation requirements](#installation-requirements), and [Service supervision and clock readiness](#service-supervision-and-clock-readiness); public configuration is specified in [the application-configuration schema](../schemas/CONFIGURATION.md).

Test path selection with injected platform and environment information. Exercise category-specific custom-resource discovery independently of the current working directory, including nested package references and manifest confinement, while verifying that content directories retain configuration-relative and explicit-absolute semantics. Exercise repeatable initialization, existing user data and assets, links, exclusive file creation, race-time destinations, marker-verified interrupted sample installation, partial failures, reset preservation, purge deletion, confirmation, and deletion boundaries using temporary locations; do not use developer application-data directories.

## Service supervision and clock readiness

Use systemd for unattended deployment on Raspberry Pi OS.

The service should start automatically when enabled and recover from unexpected application termination according to a bounded restart policy.

Service startup must not depend on network availability. A network-dependent destination must not prevent locally attached displays from operating.

Configure the host timezone and provide reliable clock synchronization appropriate to the deployment. The supplied systemd unit does not guarantee that clock synchronization has completed before Refrain starts. Systems without a reliable real-time clock may initially select content using an incorrect date; operators requiring a trustworthy initial selection must arrange for clock readiness before service startup.

Avoid duplicating systemd supervision in application code.

Graceful termination must allow the display backend to release resources safely.

This currently describes supervision of the resident. In the target architecture, each consumer is a separate executable from the same installation, has an independent system-service lifecycle, and reads its own top-level section of the shared configuration. The resident does not spawn, supervise, or depend on consumers. Configuration enablement and system-service enablement are separate. Use existing operating-system service facilities; do not implement a service manager. Consumer shutdown before maintenance is an operator responsibility; maintenance does not query or stop consumer services and does not prevent an independently running consumer from reading during purge.

## Service identity and permissions

Run Refrain with the minimum practical operating-system privileges.

Do not run the entire application as root merely because one hardware interface requires privileged access.

Document required SPI and GPIO permissions for the supported deployment.

Persistent state and generated images must be writable by the service identity.

User-authored content and configuration should not require write access from the running application unless a defined feature requires it.

## Persistent data locations

Keep user-authored content separate from application code and generated state.

Valid current-format selection state and histories must survive application restarts. Prepared images are disposable and may be regenerated. During prerelease development, incompatible state schemas do not require migration support. A diagnostic for incompatible platform-standard state may direct the operator to stop Refrain and run `refrain --reset`; for a configured state path outside the standard location, identify that path and require manual backup and quarantine/removal of only that file. `--reset` does not manage custom paths.

Avoid writing runtime state into the installed Python package directory.

Define and document platform-standard per-user paths rather than assuming a particular username or current working directory. Omitted state, global-history, and artifact paths independently retain their platform-standard defaults; demo persistence remains isolated in temporary storage.

## Application update compatibility

Application updates must not silently discard valid current-format selections or histories. Incompatible state from earlier prerelease development may require the explicit reset described above.

Persistent-state changes before the first release do not require migration from prior development schemas. Reassess compatibility when Refrain has released a public format; changes to public YAML schemas still require review against the documented interface.

The initial release does not require automatic updates or remote deployment management.
