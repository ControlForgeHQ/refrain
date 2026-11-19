# Content and Configuration

## Content semantics and identity

Refrain must support quotations and short-form content without assuming that an entry represents a song.

An entry may refer to a song, book, film, person, event, personal message, or another source.

Source-specific behavior must not be embedded in the core quotation-selection model.

## Content-entry semantics

Entries use a defined set of semantic fields rather than arbitrary user-defined presentation fields.

The initial model distinguishes:

- a stable entry identifier;
- one or more quotations;
- optional source information;
- optional attribution information;
- an optional integer priority;
- eligibility and scheduling metadata;
- optional reveal-schedule overrides;
- an optional ordered sequence of opaque actions.

Each content entry must contain at least one valid quotation.

Source, attribution, priority, eligibility, reveal configuration, and actions belong to the content entry and apply to every quotation it contains. Actions are opaque declarations; Refrain does not interpret or execute them.

Individual quotations do not have independent configuration overrides.

A quotation requiring different treatment must be placed in a separate content entry.

Optional presentation fields may be omitted when they are not meaningful for an entry.

Priority defaults to zero when omitted.

Priority is a signed integer with no project-defined minimum or maximum. Higher numerical values indicate higher selection priority.

Priority influences selection only after date specificity and repetition eligibility have been evaluated.

The complete YAML field definitions, value formats, validation rules, and supported scheduling expressions will be established as part of [content-entry schema](../schemas/CONTENT.md).

Additional content metadata may be introduced when required by an accepted feature, without changing the meaning of existing fields.

Content entries own shared configuration, while individual quotations are the units of selection.

## Entry and quotation identity

Every content entry has a stable identifier independent of its YAML filename or directory location.

Entry identifiers must be unique within the content library.

Renaming or moving an entry's file must not create a new logical entry.

Individual quotations do not require separately assigned identifiers.

Quotation identity is derived from normalized quotation text rather than from the containing entry's identifier, filename, source, or attribution.

Moving a quotation between entries or changing its associated metadata must not cause it to be treated as a previously unseen message when its normalized text is unchanged.

Quotation identity is determined by normalizing the quotation's text.

Normalization consists of:

- applying Unicode NFC normalization;
- replacing consecutive whitespace characters, including line breaks and tabs, with a single space;
- removing leading and trailing whitespace.

Capitalization, punctuation, spelling, and other non-whitespace characters remain significant.

The original quotation text, including its intended formatting, is preserved for presentation.

Normalization is used for identity comparison and history tracking, not for modifying displayed content.

Two quotations with identical normalized text represent the same message for repetition purposes, regardless of their containing entries or associated metadata.

The application is not required to perform fuzzy matching or detect semantically equivalent quotations with different wording.

Duplicate quotations across content entries are treated as a content-authoring concern rather than a separate architectural problem.

Quotation repetition identity depends on normalized text rather than entry metadata.

Automated testing should cover:

- stable entry and quotation identities;
- normalized quotation matching;

## Library loading and validation

Content is initially maintained as YAML files, ordinarily with one entry per file.

Each entry may contain an arbitrary number of quotations.

Directory organization is an authoring convenience and must not determine an entry's identity or selection behavior.

The runtime loads content when a new daily selection is required.

Automatic filesystem watching, interactive editing, and immediate reloading in response to file changes are not required.

Changes to source content affect subsequent selections, not an already committed selection.

Once a daily selection has been committed, its presentation must not depend on continued access to the corresponding YAML entry.

A usable content library may contain rejected files or entries. Refrain must preserve valid content rather than require every discovered source to pass validation.

Content must be validated before it becomes available for selection.

Invalid content files and entries are excluded from the effective content library without invalidating unrelated valid content.

Validation must identify errors such as:

- malformed or unsupported YAML;
- missing required fields;
- empty quotation collections;
- empty or invalid quotation text;
- duplicate entry identifiers;
- unknown fields;
- invalid field values;
- invalid priority values;
- unsupported eligibility expressions;
- invalid reveal schedules.

Diagnostics must identify the affected entry or source file where possible.

A malformed YAML file is excluded in its entirety.

Invalid entries are excluded individually where their source representation permits independent validation.

Conflicting duplicate entry identifiers must not be resolved according to filesystem enumeration order.

The effective content library contains only accepted, validated entries.

A partially accepted library is usable when source discovery has completed successfully and at least one valid quotation remains.

Missing or inaccessible content directories, failed source discovery, and libraries containing no valid quotations cannot support a new selection.

These library-level failures must not trigger repetition-history cleanup.

Invalid content must not produce undefined selection or rendering behavior.

A malformed entry must not silently change the meaning of another entry.

Validation must not impose an arbitrary project-specific numerical limit on priority or the number of quotations in an entry.

Detailed content validation rules and diagnostic severity are defined in [content validation and diagnostics](../schemas/CONTENT.md#validation-and-diagnostics).

Automated testing should cover:

- content-file parsing failures and independent rejection of invalid entries;
- partial content-library acceptance with valid entries preserved;
- duplicate entry identifiers and deterministic conflict handling;
- missing, inaccessible, and empty content libraries;

## Parsing and source rejection

Use a maintained YAML parser with safe loading behavior.

Do not deserialize arbitrary Python objects from application configuration or content files.

Application configuration and content files have separate validation and recovery policies defined in [configuration validation](../schemas/CONFIGURATION.md#validation-and-compatibility) and [content validation](../schemas/CONTENT.md#validation-and-diagnostics).

A syntax error in application configuration prevents that document from being interpreted; the application must report an actionable error rather than guess at its contents.

A syntax error in an individual content file excludes that file without invalidating unrelated content files.

Where the supported content format permits independent entry validation, reject individual invalid entries without discarding unrelated valid entries.

Content source discovery must distinguish a complete examination containing rejected entries from missing directories, inaccessible sources, or failed enumeration.

Duplicate entry identifiers must be handled independently of filesystem enumeration order.

Do not depend on YAML mapping order or filesystem enumeration order for selection policy.

Do not implement speculative YAML syntax repair or unsupported multi-entry formats.

## Configuration acceptance and defaults

Configuration must be explicit, documented, and validated.

Both application configuration and content entries use YAML, with separate schemas defined in [Application Configuration](../schemas/CONFIGURATION.md) and [Content Entries](../schemas/CONTENT.md).

Construct an effective application configuration from accepted values, documented defaults, and usable registered resources.

Distinguish fatal validation errors from recoverable warnings and informational default notices.

Apply only defaults established by [the application-configuration schema](../schemas/CONFIGURATION.md). Do not invent fallback values to bypass missing required settings.

Unknown application-configuration fields and invalid optional values must be reported and handled according to the configuration contract without unnecessarily preventing operation.

Destination `overrides` follow the stricter public contract in [Destination overrides](../schemas/CONFIGURATION.md#destination-overrides): reject unsupported keys, types, and values rather than handling them as ordinary ignored unknown fields or falling back to resource pools.

When optional values are omitted, informational default notices should be consolidated where practical rather than generating excessive startup output.

Discover bundled and user-owned assets when loading effective configuration, using package-resource APIs for bundled resources and category directories relative to the effective configuration for user assets. Do not monitor, modify, or generate files in user asset directories. Safely validate each manifest and resource independently; confine manifest references to their package and do not follow symlinks during discovery.

Construct registries from valid discovered identifiers, then resolve named pools once against those registries and the effective palette. Do not add discovered resources to user-defined pools except through the reserved `@builtin` reference, whose file-backed membership is limited to successfully registered bundled assets. Custom resources cannot shadow bundled identifiers, and all custom resources in a same-category collision are excluded deterministically.

An unavailable font preference in an otherwise valid content entry does not invalidate that entry. Report it and proceed to the next font preference, using the effective default pool only when automatic selection is required. An empty effective pool must not invalidate an otherwise usable explicit content-entry or decoration preference.

Validate discovered backgrounds individually against the PNG requirements in [background assets](../schemas/ASSETS.md#background-assets) and [image layers](../schemas/ASSETS.md#image-layers). Preserve valid resources when another asset fails. Build the effective default background pool from its resolved definition. Report unavailable content-entry background preferences without rejecting otherwise valid entries.

Validate content independently by source file and, where supported, by entry. Preserve accepted entries when other entries fail validation.

A malformed entry-level action is a recoverable item-level warning: discard that action and continue validating the remaining actions without rejecting the content entry. Keep action diagnostics separate from entry-fatal diagnostics. Preserve valid action order and exact opaque payload strings, enforce the documented action-count and UTF-8 payload limits, and represent actions as immutable values in entries and committed snapshots.

A nonempty effective content library may be used for new selections even when individual sources were rejected.

Do not treat missing or inaccessible sources, unsuccessful discovery, or an empty effective content library as successful content removal for repetition-history cleanup.

Do not rewrite user-authored configuration or content files as part of validation.

Automated testing should cover:

- application configuration parsing, defaults, warnings, and fatal validation errors;
- missing optional values with documented defaults;
- explicitly invalid optional values with and without defaults;
- unrecognized application-configuration fields;

## Resource registries and pool expansion

Configuration loading owns asset discovery, validation, collision handling, and construction of independent font, background, and decoration registries. Bundled resources are discovered through Python package-resource APIs; user resources are discovered recursively under the corresponding `assets/{fonts,backgrounds,decorations}/` directory beside the effective configuration. Discovery occurs once when configuration is loaded. It does not monitor or modify user directories.

Discovery establishes availability by stable identifier only. After discovery, configuration loading resolves category-scoped named pools against those registries and the effective palette. The reserved `builtin` pool for fonts, backgrounds, and decorations contains only successfully registered bundled resources; color `builtin` pools contain `black`. Custom or unusable assets do not enter file-backed built-in membership. Other discovered resources are not added to automatic-selection eligibility unless a configured pool explicitly names them.

Asset manifests are safely parsed and their references are confined to their owning package. Invalid resources are isolated with diagnostics. Custom identifiers cannot shadow identifiers claimed by packaged resources, and every custom resource in an intra-category collision is excluded deterministically.

Application configuration retains the actual resolved concrete membership of each named pool, including an empty pool. Pool references are category-local. Expansion is depth-first in declaration order, preserves the first occurrence of each usable identifier, and silently skips references to pools on the active recursion path. Expansion does not choose randomly; each distinct candidate receives equal probability at the later selection point. Invalid, unavailable, malformed, and unknown references are diagnosed and excluded without discarding other candidates. Automatic background and decoration selection may use the category's `"none"` fallback when the effective default pool has no usable members, but this never inserts `"none"` into any named pool. An explicitly referenced empty pool, including `@default`, remains empty and follows ordinary preference fallthrough; strict viewer overrides referencing an empty pool fail. Background and decoration pools may explicitly contain the reserved value `"none"`, representing the intentional absence of that resource.

Bundled fonts, backgrounds, and decorations are package-owned resources accessed through package-resource mechanisms. User-provided resources belong under the `assets/` directory beside the effective configuration file, separated into `fonts/`, `backgrounds/`, and `decorations/`; they are not generated cache data. The configuration loader discovers and validates resources in these locations when effective configuration is loaded.

Refrain maintains an effective font registry containing usable bundled and discovered font bundles.

Application configuration defines category-scoped named pools using stable identifiers and resolves their references after resource discovery. The reserved `builtin` font pool contains successfully registered bundled fonts; it is included in automatic selection only when explicitly referenced. The effective default font pool contains only distinct usable fonts from its resolved definition and may be empty.

Unusable or invalid user font registrations are excluded from the effective registry with appropriate warnings. Custom font identifiers cannot override identifiers claimed by readable bundled manifests.

Validate all manifest-declared font faces when loading application configuration; each discovered bundle must provide a usable regular face. Validate the optional role-preference mapping independently from the registered `faces` resources. Invalid optional preference metadata is warned about and ignored without invalidating an otherwise usable bundle or decoration.

Validation must establish that each registered file exists, is readable, and can be loaded by the renderer.

Validate the syntax of content-entry face preferences during content-library loading. Report a valid but unavailable winning face when the selected bundle and preferences are resolved for a complete image preparation.

Automated testing should cover:

- recursive asset discovery, package boundaries, manifest schemas, safe relative references, symlink escapes, malformed-resource isolation, identifier validation, collisions, and discovered-resource membership in default pools only through explicit `@builtin` references;
- category-scoped named-pool name validation, reserved `builtin`, recursive expansion order, deduplication, independently shared subpools, direct/indirect cycles, invalid references, and empty/malformed definitions;
- built-in membership from registered bundled resources only, including exclusion of unusable and custom resources, dynamic membership, deterministic order, and no implicit background/decoration `none`;
- pool references at configuration, content, asset-manifest, and CLI preference levels, including category isolation, precedence, strict explicit overrides, empty-pool fallback, and concrete selection before preparation;
- unavailable or invalid registered fonts and effective named/default font-pool construction;
- built-in and custom palette values, invalid palette definitions, and effective named/default color-pool construction;
- bundled and custom standalone and packaged background registration, layer validation, independent rejection of invalid PNGs, reserved identifiers, and default-pool construction;

## Opaque action declarations

Content entries may declare optional, ordered actions that are captured as opaque semantic data in the committed daily selection.

Refrain validates the generic action envelope but does not interpret payloads, execute actions, or require external integrations to display quotations.

Automated testing should cover:

- entry-level action envelope validation, warning-and-drop behavior, supported audiences, opaque payload preservation, UTF-8 payload sizing, action-count limits, duplicate/order preservation, and entry-level inheritance;
