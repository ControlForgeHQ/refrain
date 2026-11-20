# Installation and Service Operation

## Platform paths and publication root

Refrain uses platform-standard per-user directories for configuration, operational state, generated artifacts, filesystem publications, runtime ownership, and authenticated local control.

The application-path resolver is authoritative for standard path construction. Use one resolver at command-line boundaries rather than independently reconstructing platform paths in application components.

The supported standard locations are:

| Purpose | Linux | Windows |
|---|---|---|
| Configuration directory | `$XDG_CONFIG_HOME/refrain` | `%APPDATA%\Refrain` |
| Configuration file | Configuration directory `/config.yaml` | Configuration directory `\config.yaml` |
| Content directory | Configuration directory `/content` | Configuration directory `\content` |
| User assets | Configuration directory `/assets` | Configuration directory `\assets` |
| State directory | `$XDG_STATE_HOME/refrain` | `%LOCALAPPDATA%\Refrain\State` |
| Prepared artifacts | `$XDG_CACHE_HOME/refrain/artifacts` | `%LOCALAPPDATA%\Refrain\Cache\artifacts` |
| Publication root | `$XDG_STATE_HOME/refrain/publish` | `%LOCALAPPDATA%\Refrain\Publish` |

On Linux, use these base-directory fallbacks when the corresponding XDG environment variable is absent, empty, or not absolute:

| Variable | Fallback |
|---|---|
| `XDG_CONFIG_HOME` | `~/.config` |
| `XDG_STATE_HOME` | `~/.local/state` |
| `XDG_CACHE_HOME` | `~/.cache` |

On Windows, resolve the roaming configuration location from `APPDATA` and local operational locations from `LOCALAPPDATA`. Both must identify valid absolute per-user paths.

The standard runtime ownership and local-control metadata locations are:

| Purpose | Linux | Windows |
|---|---|---|
| Ownership lock | `$XDG_STATE_HOME/.refrain-ownership.lock` | `%LOCALAPPDATA%\.refrain-ownership.lock` |
| Control metadata directory | `$XDG_STATE_HOME/.refrain-control` | `%LOCALAPPDATA%\.refrain-control` |
| Control endpoint metadata | Control metadata directory `/endpoint.json` | Control metadata directory `\endpoint.json` |

Apply the XDG fallback rules to runtime ownership and control metadata as well.

The ownership lock and control metadata remain outside standard Refrain installation directories removed by `--reset` or `--purge`.

Endpoint and credential contents, authentication, permissions, stale-endpoint handling, and actual local socket or pipe naming are defined under [Resident ownership and authenticated control](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#resident-ownership-and-authenticated-control).

Filesystem publication defaults to a Refrain-owned per-user directory and does not require an HTTP listener or network service.

On Linux, the standard publication root is a child of the standard state directory. The root's ownership and cleanup scope must remain confined to `publish/` and must not affect sibling operational files.

On Windows, state, cache, and publication directories are separate children of the local Refrain operational-data directory.

A standard publication root may share a parent with protected operational storage. Path validation must distinguish permitted shared ancestry from actual overlap of publication cleanup scope with protected files or directories.

### Effective runtime paths

The optional `storage` configuration mapping supplies independent overrides for:

- `content`
- `state`
- `artifacts`
- `publish`

The authoritative field names, defaults, and validation constraints are defined under [Storage](../schemas/CONFIGURATION.md#storage).

An absolute configured path is used as specified. A relative configured path is resolved against the directory containing the selected configuration file, not the current working directory.

An omitted path retains its own platform-standard default. Selecting an alternate configuration file does not automatically relocate state, artifacts, or publication storage.

The omitted content path follows the selected configuration file as defined by the configuration schema.

`storage.state` identifies one directory containing three fixed files:

| Filename | Responsibility |
|---|---|
| `state.json` | Authoritative operational selection, scheduling, repetition history, and reveal progression. |
| `publication.json` | Current publication checkpoint and durable destination-independent artistic choices. |
| `global-history.jsonl` | Best-effort chronological selection history. |

Rotated global-history segments reside in that same directory.

Changing `storage.state` relocates these files together. Global history has no independent path override.

Prepared-image artifacts are derived data under the effective `storage.artifacts` directory.

Filesystem publication datasets are stored under the effective `storage.publish` directory. Each destination owns a direct child named from its validated destination ID.

The effective publication root must satisfy the protected-path and filesystem-containment requirements in [Publication paths and containment](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#publication-paths-and-containment).

Standard installation-management commands use only standard paths, regardless of runtime configuration overrides.

Application and persistence components receive resolved effective paths explicitly. They must not independently discover home directories, interpret relative configuration paths, or infer storage locations from the current working directory.

Use `pathlib` for filesystem path handling.

Keep configuration, content, and user assets separate from operational state, publication checkpoints, generated artifacts, and published datasets.

Do not write operational data into the installed Python package directory.

Standard per-user path conventions may be retained for macOS where existing code already provides them, but macOS is not a supported or maintained deployment or testing platform. Do not add macOS-specific support requirements or imply platform validation.

## Installed package resources

The installed Python distribution includes:

- The editable default application configuration.
- The packaged sample content library.
- Bundled font, background, and decoration resources.
- Their applicable manifests and referenced assets.
- Required font licenses and copyright information.
- `assets/README.md`.
- Required service and deployment resources.

Use package-resource APIs for bundled resource discovery. Installed operation must not require a source checkout or assume a development repository layout.

Custom visual resources are user-owned and located beneath `assets/fonts/`, `assets/backgrounds/`, and `assets/decorations/` beside the selected configuration file.

Manifest resource paths are relative to their containing asset package and must not escape that package.

User assets and bundled resources are distinct. Initialization must not copy packaged visual assets into the user's asset directories.

Wheel and source-distribution tests must verify that the required manifests, referenced resources, licenses, sample content, configuration, and asset documentation are included and accessible after installation.

## Installation requirements

The minimum supported Python version is 3.13.

The primary deployment target is Raspberry Pi OS Lite on Raspberry Pi hardware, initially validated on the Raspberry Pi 3B+ with the supported Waveshare 13.3-inch e-Paper HAT+ (E).

Raspberry Pi OS is the principal supported Linux deployment environment.

Other Linux distributions may operate using compatible facilities but are not individually validated or promised as supported deployments.

Windows supports hardware-independent development and resident testing, including configuration, content, scheduling, persistence, rendering, local runtime control, desktop presentation, and filesystem publication as applicable.

Windows does not provide the Raspberry Pi-specific Waveshare SPI/GPIO hardware integration.

macOS is not a supported or maintained target.

Use ordinary operating-system facilities for process management, logging, local timekeeping, filesystem storage, and hardware access.

Do not introduce a custom service manager, log daemon, database service, container requirement, or external scheduler without a demonstrated need.

The installed package must operate independently of the developer's directory structure.

Normal runtime startup requires an existing selected configuration file. It must not silently initialize the installation, copy sample content, or replace missing configuration with packaged defaults.

Explicit installation is performed by `refrain --initialize`.

The public syntax, confirmation requirements, and exit behavior of installation-management commands belong to [CLI](../CLI.md#primary-refrain-application).

Installation and deployment documentation must identify the supported operating system, Python environment, required dependencies, persistent paths, service identity, and physical hardware permissions where applicable.

Hardware-independent tests must run on Windows and Linux without requiring physical display hardware or systemd.

## Initialization and destructive maintenance

Installation-management commands operate only on the standard per-user Refrain installation.

They do not use configured custom storage paths, including paths relative to an alternate configuration file.

`--initialize`, `--reset`, and `--purge` acquire the exclusive standard installation ownership lock non-blockingly before modifying installation data.

If another Refrain runtime or installation-management operation owns the lock, the requested operation must fail with an actionable diagnostic and perform no mutation.

One-shot runtime-control clients do not acquire this ownership lock.

Independent consumers also do not acquire it. Operators must stop consumers before destructive maintenance affects their installation or publication data.

### Initialization

`refrain --initialize` is noninteractive, repeatable, and limited to standard locations.

Before writing:

1. Resolve all standard paths.
2. Validate packaged configuration and sample content.
3. Preflight the required destination paths and existing filesystem objects.
4. Reject links, redirection, unsafe objects, and conflicting destinations.
5. Establish that existing data can be preserved without overwriting it.

Initialization creates missing standard configuration, content, user-assets, state, artifact, and publication directories.

It installs the packaged default `config.yaml` only when the standard configuration file is absent.

An existing regular configuration file is preserved byte-for-byte.

Initialization creates the standard user-assets directory and its `fonts`, `backgrounds`, and `decorations` category directories when missing.

Existing user-asset files and nonempty category directories are preserved without inspecting or modifying their contents.

Bundled visual assets remain package-owned and are not copied into the user-assets tree.

Install packaged sample content only when the standard content directory is missing or empty, subject to verified interrupted-installation recovery.

An ordinary pre-existing nonempty content directory must be left untouched and uninspected.

### Interrupted sample installation

Sample installation uses an installation-owned temporary marker identifying the packaged sample set.

If sample installation was interrupted and the content directory is now nonempty, resume only when:

- The marker identifies the expected packaged sample set.
- Every existing expected sample file matches its packaged bytes.
- Missing expected samples can be created safely without replacing existing files.

Create only missing expected sample files, using exclusive file creation.

Remove the marker after the complete sample set has been successfully installed.

An absent or invalid marker, conflicting file content, or uncertain ownership in a nonempty directory must not be interpreted as a resumable installation.

Report the condition and require manual inspection rather than overwriting user content.

Initialization must tolerate an interrupted prior attempt without treating arbitrary files as owned installation artifacts.

### Initialization persistence boundaries

Initialization creates or reuses standard state and artifact directories without modifying existing persistent state, history, publication checkpoints, or generated image artifacts.

It must not create placeholder `state.json`, `publication.json`, or global-history files.

It creates the standard publication root when missing but must not replace, clean, or modify existing publication datasets during initialization.

Use exclusive creation for new files and safe directory-creation procedures that reject unexpected objects appearing during the operation.

A failure leaves successfully created destinations in place for a safe subsequent retry.

Report the failed operation and the created or affected paths.

Initialization does not select content, commit daily state, prepare images, start the resident, or initialize display backends.

### Reset

`refrain --reset` is an interactive destructive operation on standard runtime state and generated caches.

It requires both standard input and output to be interactive terminals and an exact confirmation of `RESET`.

There is no noninteractive confirmation bypass.

Cancellation must leave the installation unchanged.

Reset removes:

- Standard `state.json`.
- Standard `publication.json`.
- Standard active global-history file.
- Standard rotated global-history segments.
- Refrain-generated contents of the standard cache and prepared-artifact directories.

Reset preserves:

- Standard `config.yaml`.
- Content and user asset files.
- Bundled package resources.
- The complete standard publication root and its datasets.
- Standard installation directory structure.
- Runtime ownership and control metadata locations outside the reset scope.
- Every configured custom storage path.

Reset must not recursively delete the standard state directory merely to remove the three fixed persistent files.

This is particularly important on Linux, where the standard publication root is a child of the standard state directory.

Reset does not use runtime configuration or infer custom storage paths.

### Purge

`refrain --purge` removes the complete standard per-user Refrain installation after exact interactive confirmation of `PURGE REFRAIN`.

Both input and output must be interactive terminals. There is no noninteractive bypass.

Cancellation must leave the installation unchanged.

Purge removes the Refrain-owned standard directory trees for:

- Configuration, including standard content and user assets.
- Operational data, including state, publication checkpoints, global history, and filesystem publications.
- Generated caches and artifacts.

The complete standard publication root is within purge scope. Every contained destination directory, completed dataset, temporary file, and other object is subject to safe removal.

Purge removes all contents physically within its owned deletion roots, not only recognized filenames or generated artifacts.

It must not remove shared parent directories or unrelated user and application data.

The runtime ownership lock and control metadata are kept outside the owned installation trees so deletion does not remove the lock used to exclude a concurrent resident.

Configured custom state, content, artifact, and publication paths are never followed or deleted by purge.

### Filesystem deletion safety

Resolve destructive-operation targets from standard application paths only.

Before deletion, verify that each root is an actual directory owned by the standard installation and is not a symbolic link, junction, reparse point, or other redirected filesystem object.

Reject unsafe roots rather than following their targets.

When traversing an owned tree, inspect entries without following filesystem links.

A link encountered within an owned tree may be removed as a contained object, but its target must never be traversed or deleted.

Remove contained regular files and directories according to their actual ownership and location, including unfamiliar files beneath an established purge root.

Do not traverse outside the declared deletion scope.

Treat unexpected object types, unsafe root ownership, permission failures, and uncertain containment as actionable errors.

Do not silently skip failed deletions or attempt recovery outside the standard owned paths.

Use temporary test directories and injected path resolution for destructive-operation tests. Never run those tests against the developer's actual application-data directories.

### Consumer maintenance exclusion

Independent consumers do not participate in the resident ownership lock.

Before purging publication data or replacing consumer installation files, the operator must stop affected consumer services through their operating-system service facilities.

Maintenance commands do not query, stop, or manage consumer services automatically.

The ownership lock excludes cooperating Refrain resident and installation-management processes; it does not promise protection against arbitrary external filesystem mutation or consumers left running during destructive maintenance.

Automated tests must cover:

- Standard path selection under injected Linux and Windows environments.
- Omitted and explicit storage paths.
- Standard-only initialization, reset, and purge behavior.
- Configured custom storage isolation.
- Exclusive ownership and busy-lock rejection.
- Repeatable initialization and preservation of existing user data.
- Exclusive file creation and race-time destination changes.
- Marker-verified interrupted sample installation.
- Preservation of nonempty content and user-assets trees.
- Creation without placeholder state or history files.
- Reset removal of all three fixed persistent files and rotated history.
- Reset preservation of publication storage, including Linux's nested standard layout.
- Purge removal of all contents beneath owned standard roots.
- Root symlink, junction, and reparse-point rejection.
- Safe removal of contained links without following their targets.
- Permission failures and partial-operation diagnostics.
- Independent consumer maintenance boundaries.
- Windows and Linux filesystem behavior.

## Service supervision and clock readiness

Use systemd for supervised unattended deployment on Raspberry Pi OS.

The resident service should start automatically when enabled and recover from unexpected process termination under a bounded restart policy.

Normal resident startup must not require network availability.

The absence, failure, or delayed startup of an independent consumer must not prevent resident content selection, persistence, image preparation, or direct-display operation.

Independent consumers use their own operating-system service lifecycles.

The resident does not spawn, supervise, restart, or depend on consumer services.

Consumer enablement in application configuration is separate from operating-system service enablement.

Do not introduce application-level service supervision merely to replace systemd.

### Clock readiness

Refrain uses the host operating system's local timezone and timekeeping facilities.

Configure the deployment's local timezone and provide appropriate clock synchronization.

The supplied systemd service does not guarantee that clock synchronization has completed before the resident starts.

A device without a reliable real-time clock may initially evaluate an incorrect logical display date.

Operators requiring correct initial selection must arrange for trustworthy clock readiness before service startup.

A later clock correction is handled by the normal logical-date and reveal-scheduling rules in [Scheduling and Application Lifecycle](40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md).

Do not add an independent timezone database, custom clock daemon, or network-time dependency inside Refrain.

### Shutdown

The resident must honor the single 60-second foreground shutdown deadline defined in [Shutdown coordination](40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#shutdown-coordination).

Shutdown stops new publication admission and recoverable retries while allowing admitted operations to finish safely within the remaining deadline.

Do not call backend cleanup concurrently with an active publication on the same instance.

A blocked operation may require deferred cleanup or process exit for final resource release.

Retain exclusive resident ownership while protected backend resources or control handlers remain active.

The service supervisor may impose its own process-stop policy, but that policy must not be implemented as independent per-backend application shutdown deadlines.

Service shutdown must not intentionally clear retained e-paper images.

Document consumer shutdown and maintenance ordering separately from ordinary resident shutdown.

Hardware-independent tests must cover bounded shutdown, concurrent backend operations, deferred cleanup, and safe ownership release.

## Service identity and permissions

Run the resident under the minimum practical operating-system privileges.

Do not require root merely because the supported Waveshare hardware uses SPI and GPIO.

Configure the relevant device nodes, GPIO character-device permissions, and service-group membership for the supported Raspberry Pi OS deployment.

Hardware-specific setup belongs to the packaged Waveshare backend guide and [Waveshare conversion and controller lifecycle](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#waveshare-conversion-and-controller-lifecycle).

The service identity must have appropriate access to:

- The selected application configuration and content.
- Registered user-owned rendering resources.
- Effective operational-state storage.
- Prepared-artifact storage.
- Effective filesystem-publication destinations.
- Protected resident ownership and local-control metadata.
- Supported hardware devices when that backend is configured.

User-authored configuration, content, and assets should remain read-only to the running application unless a defined operation requires modification.

Operational state, publication checkpoints, generated artifacts, and owned publication datasets require write access by their responsible application components.

Protect runtime-control credentials and endpoint metadata from other users using the platform-specific rules in [Resident ownership and authenticated control](60-DESTINATIONS_AND_RUNTIME_CONTROL.md#resident-ownership-and-authenticated-control).

Consumers require read access only to their configured publication datasets and relevant configuration.

They must not require write access to Refrain-owned publication directories or authoritative operational state.

A public consumer's access to publication files must be restricted appropriately for its configured audience and trust boundary.

Do not rely on destination action filtering as a substitute for filesystem permissions or service authorization.

## Persistent data locations

Keep user-authored content and configuration separate from installed code and generated operational data.

Valid current-format `state.json`, `publication.json`, and global-history data must survive ordinary application restart.

The operational state file owns the committed daily selection and reveal progression.

The publication checkpoint owns durable resolved destination-independent artistic choices.

Global history is best-effort and is not authoritative for operational recovery.

Prepared images are disposable cache entries that may be regenerated from the committed selection and valid publication checkpoint.

Completed filesystem-publication datasets remain independently consumable through their verified manifests.

Do not conflate these four responsibilities or introduce additional authoritative state through service or installation paths.

An incompatible or corrupt standard operational-state file must produce an actionable diagnostic.

For standard-path operational state, diagnostics may direct the operator to stop Refrain and run `refrain --reset`.

For a configured state directory outside the standard location, identify the actual affected file and require manual backup and quarantine or removal of only that file.

`--reset` must not operate on configured custom storage.

Checkpoint recovery, reveal-progress reconciliation, and persistent compatibility belong to [Selection and Persistence](30-SELECTION_AND_PERSISTENCE.md#recovery-and-state-compatibility).

Filesystem-publication recovery belongs to [Dataset commit and consumer recovery](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#dataset-commit-and-consumer-recovery).

No accelerated `--demo` runtime or separate demo persistence lifecycle is defined.

## Application update compatibility

Application updates must not silently discard valid current-format committed selections, publication checkpoints, or global-history records.

Only the current prerelease internal operational-state schema is supported.

Earlier development-state schemas do not require migration, compatibility readers, or historical rendering branches.

Incompatible prerelease state may require the explicit recovery or reset procedure described above.

Changes to public configuration, content, asset, publication, CLI, or consumer interfaces still require review against their authoritative schemas and approved compatibility requirements.

Reassess persistent-format compatibility when Refrain establishes its first public release.

The initial release does not require automatic application updates, remote deployment management, or a custom upgrade service.