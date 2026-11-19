# Development Standards

## Implementation discipline and resource budgets

Refrain is intended to operate unattended for extended periods.

An incorrect selection, inconsistent persistent state, missed reveal, or unnecessary display refresh can undermine the intended experience.

Prefer behavior that can be demonstrated correct over behavior that is merely convenient to implement.

Test assumptions where possible rather than encoding speculative behavior into the application.

Prefer straightforward Python code and a limited dependency set.

Avoid unnecessary frameworks, background services, abstractions, and configuration options.

Do not introduce complexity solely to accommodate hypothetical future features.

A small amount of duplication is preferable to introducing an abstraction without a demonstrated benefit.

The Raspberry Pi 3B+ is the minimum supported Raspberry Pi platform for Version 0.1.

Favor implementations that can operate within modest memory, CPU, and storage budgets.

Avoid unnecessary resident data, polling, heavyweight dependencies, and background processing.

Do not retain all decoded reveal-stage images in memory merely because they were generated together.

Use measurements from representative hardware to justify performance-related changes.

Correctness and maintainability take precedence over speculative micro-optimization.

## Python compatibility and continuous integration

Refrain is implemented in Python 3.

Use a Python version supported by the targeted Raspberry Pi OS release.

Do not require a separately installed interpreter when the operating system's supported Python version meets the project's needs.

Avoid language features or third-party packages that unnecessarily exclude supported deployment platforms.

The project's minimum supported Python version must be established in the project metadata once implementation begins.

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

## Code structure, formatting and typing

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

Use Black for Python formatting and Ruff for linting.

The project uses a target line length of 120 characters.

Line length is a readability guideline rather than an absolute restriction. Prefer keeping a clear expression on one line when splitting it would make the code harder to understand.

Do not introduce artificial line breaks solely to satisfy historical terminal-width conventions.

Configuration belongs in `pyproject.toml` and must be applied consistently by contributors and automated checks.

Source files should not require editor-specific configuration to maintain consistent formatting.

Do not suppress diagnostics without a documented reason.

Formatting-only changes should not be mixed with unrelated behavior changes.

Use Python type annotations to clarify interfaces and important data structures.

Type annotations should make the code easier to understand and maintain.

Do not introduce complicated generic types, protocols, or abstract class hierarchies solely to satisfy static typing.

A static type checker may be introduced when it provides demonstrated value.

## Error reporting and recovery ownership

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

## Comments and interface documentation

Comments should explain intent, architectural constraints, or non-obvious behavior.

Do not write comments that simply restate the code.

Document public interfaces and complex behavior where that documentation materially improves understanding.

Use precise terminology consistent with [shared terminology](specifications/10-SYSTEM_CONTRACTS.md#shared-terminology).

## Dependency policy and isolation

Keep the runtime dependency set small and explicit.

Dependencies must be justified by required functionality.

Prefer maintained libraries with clear licensing and support for the target Python and Linux environments.

Do not introduce dependencies for deferred future features.

Development and testing dependencies must be distinguishable from production runtime dependencies.

Use a project-local Python virtual environment for development.

A virtual environment is also preferred for deployed application dependencies when practical.

The virtual environment must not be committed to the repository.

Runtime dependencies should be installed using a reproducible, documented process.

Avoid modifying the operating system's Python package environment through unrestricted global `pip` installations.

Declare the supported dependency versions or ranges in project metadata.

Dependencies should be installed reproducibly for validation and deployment.

Updates must be tested against the supported Python version and target platform.

Avoid unnecessarily restricting compatible patch releases unless compatibility evidence justifies the restriction.

Keep hardware-specific imports and dependencies isolated within the display backend.

Content loading, selection, persistence, scheduling, and rendering tests must not require Raspberry Pi GPIO or SPI libraries.

The hardware-independent application must remain importable on development systems without the physical display attached.

## Logging and diagnostics

Use Python's standard `logging` facilities.

Emit application logs to standard output and standard error as appropriate for supervised execution.

Do not require a separate log server, database, or third-party logging framework.

Allow systemd and journald to manage ordinary deployed logs.

Avoid implementing application-specific log rotation or persistent diagnostic log files without a demonstrated need.

Global selection history is structured application data and must remain separate from ordinary diagnostic logging.

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

Diagnostics must distinguish a rejected input value from a failure of the entire configuration or content library.

Recoverable validation problems must remain visible to the operator without preventing unrelated valid settings or entries from being accepted.

Fatal errors must identify the missing or unusable requirement and the next useful troubleshooting step.

Configuration and content diagnostics must preserve their source location where available.

Diagnostic facilities must not mutate persistent state or operate the physical display unless explicitly intended to do so.

## Automated testing and configuration fixtures

Use pytest for hardware-independent automated tests.

Tests should verify observable behavior and documented contracts rather than relying unnecessarily on private implementation details.

Tests of application behavior must use explicit test inputs rather than depending on incidental values from the shipped default configuration or the current bundled resource inventory. Tests may assert exact shipped values only when those values are themselves contractual requirements. Bundled-resource integrity tests must validate the current package contents without requiring test modifications whenever valid resources are added, removed, or replaced.

Keep three configuration-testing responsibilities separate:

- Application-default tests omit optional settings and verify documented fallback values, required settings, and effective constraints. Exercise operation when its actual prerequisites are satisfied.
- Configuration-processing tests supply controlled inputs for parsing, validation, precedence, ordering, and diagnostics. Prefer small synthetic resources where resource characteristics matter; avoid fixtures that inherit unrelated shipped settings.
- Shipped-configuration tests load the actual `config.default.yaml`, validate its effective settings and resource availability, and exercise representative preparation or rendering without freezing incidental choices.

Exact-value assertions remain appropriate for documented contracts, deliberately supplied fixture values, deterministic rendering or selection scenarios, and persistent-state or protocol compatibility. A valid change to shipped configuration or bundled resources must not unnecessarily invalidate unrelated behavioral tests. Comparing parsed pools with their source YAML alone is insufficient: also verify usability and retain rejection or diagnostic coverage for invalid configuration and unavailable resources.

Every substantive behavior change should include focused regression coverage where practical.

The ability to import and test core components without Raspberry Pi hardware is a project requirement.

## Deterministic testing

Randomized selection tests should use controlled random sources where deterministic outcomes are needed.

Do not rely on statistical luck to make unit tests pass.

## Isolated filesystem testing

Use temporary directories and isolated test state.

## Measurement and validation reporting

Measure memory use, image-preparation time, and storage requirements on the Raspberry Pi 3B+ when those characteristics materially affect supported deployment targets. Do not reject rendering-quality decisions solely because they add work to infrequent daily image preparation.

Do not introduce caching, concurrency, or performance optimization without evidence that it improves an observed limitation.

The repository should provide consistent commands for:

- formatting verification;
- linting;
- automated tests;
- package or source installation verification where applicable.

The exact commands must be documented alongside the configured development tools.

A change is not considered validated merely because its Python files import successfully.

Record validation limitations honestly.

## Versioning and compatibility

Use semantic versioning for project releases.

Version 0.1 establishes the initial usable release.

During pre-1.0 development, compatibility-breaking changes may be necessary, but they must be deliberate and documented.

Treat published content and configuration formats as user-facing interfaces.

Avoid unnecessary changes that invalidate existing YAML libraries.

Persisted-state changes must be evaluated for their effect on recovery across software updates.

Do not promise compatibility with unimplemented future hardware, web interfaces, or integrations.

## Limits on engineering infrastructure

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
