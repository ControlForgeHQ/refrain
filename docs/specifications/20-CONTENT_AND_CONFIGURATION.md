# Content and Configuration

## Content semantics and identity

Refrain supports quotations and short-form literary content without assuming that an entry represents a song.

An entry may identify a song, book, film, person, event, personal message, or another source.

Source-specific integrations must not be embedded in core content validation, quotation identity, selection, scheduling, or rendering behavior.

Content entries define authored literary information and preferences. They do not directly control display backends, persistent operational state, filesystem publication, or external action execution.

The authoritative authored field contract belongs to [Content Entries](../schemas/CONTENT.md).

## Content-entry semantics

Each content entry has one stable identifier, one or more quotations, and optional shared metadata.

Supported entry-level semantics include:

- Source and attribution.
- Priority and calendar eligibility.
- Effective reveal-schedule overrides.
- Font, role-face, background, decoration, color, and presentation-style preferences.
- Ordered opaque action declarations.

All quotations within an entry inherit its metadata, eligibility, reveal overrides, presentation preferences, and actions.

Individual quotations do not have independent identifiers or overrides. A quotation requiring different authored treatment belongs in another entry.

An entry must contain at least one valid quotation.

The number of quotations in an entry has no arbitrary project-defined upper limit.

Priority defaults to zero. It is a signed integer without a project-defined minimum or maximum.

Priority affects selection only after date specificity and repetition eligibility have been evaluated.

Omitted optional fields have their documented defaults or absence semantics. Omission must not be treated as an invalid explicitly supplied value.

The `source` and `attribution` fields are optional. When supplied, each must contain non-whitespace text.

Preserve leading and trailing whitespace in otherwise valid source and attribution strings rather than silently trimming them.

Missing optional literary fields remain absent. Do not represent absence by empty, whitespace-only, or null strings.

Validate entry-level reveal overrides before an entry participates in selection.

Every supplied reveal override must be valid against the effective global schedule and configured day start, including overrides for source or attribution fields absent from the entry.

An invalid effective reveal schedule excludes the affected entry without invalidating unrelated eligible entries.

The quotation appears at the configured day start. Source and attribution may reveal simultaneously, at day start, or in either valid order.

The exact entry fields, accepted values, defaults, and validation constraints are defined in [Content Entries](../schemas/CONTENT.md).

A committed daily selection captures the selected quotation's complete literary content, effective schedule, applicable preferences, and ordered action declarations independently of its original entry.

Changes to the originating entry affect future selections but must not change the content or schedule of an already committed selection.

Commitment and snapshot ownership belong to [Selection and Persistence](30-SELECTION_AND_PERSISTENCE.md).

## Entry and quotation identity

Every content entry has a stable, explicit identifier independent of its YAML filename and directory location.

Entry identifiers must be unique across the effective content library.

Renaming or relocating a content file must not change its entry identity.

Individual quotations do not require authored identifiers.

Quotation repetition identity is derived from normalized quotation text alone.

Normalize quotation identity by:

1. Applying Unicode NFC normalization.
2. Replacing each sequence of whitespace characters, including tabs and line breaks, with one space.
3. Removing leading and trailing whitespace.

Capitalization, punctuation, spelling, and other non-whitespace characters remain significant.

Preserve the original quotation text, including Unicode, whitespace, authored line breaks, and paragraph structure, for selection snapshots and presentation.

Normalization is used only for identity comparison and repetition tracking. It must not modify displayed literary content.

Two quotations with identical normalized text share one repetition identity regardless of their entry identifiers, source, attribution, eligibility, priority, or presentation preferences.

Moving a quotation between entries or changing its metadata must not create a new repetition identity when its normalized text is unchanged.

Do not implement fuzzy matching or semantic-equivalence detection.

Duplicate quotation identities are permitted in authored content. Selection and repetition eligibility must treat them according to the normalized identity contract in [Selection and Persistence](30-SELECTION_AND_PERSISTENCE.md#candidate-identity-and-priority).

Automated tests must cover Unicode normalization, whitespace folding, preservation of original text, significant punctuation and case, cross-entry duplicates, and stable identity after file moves or metadata changes.

## Library loading and validation

Content is maintained in UTF-8 YAML files.

The supported authored format is exactly one content-entry mapping per file, as specified in [Content Entries](../schemas/CONTENT.md#yaml-document).

### Discovery

Discover content files recursively beneath the effective `storage.content` directory.

Recognize supported YAML source files independently of directory depth.

Do not follow symbolic-link directories or content-file symlinks during discovery.

Directory structure and filesystem enumeration order must not determine entry identity, eligibility, repetition behavior, priority, or candidate selection.

Content discovery must distinguish:

- Successful complete enumeration with all files accepted.
- Successful complete enumeration with some files or entries rejected.
- Successful complete enumeration with a usable library but no quotation eligible for the current display date.
- Missing or inaccessible content sources.
- Incomplete or failed source enumeration.
- Successful enumeration containing no valid quotations.

A completed enumeration containing rejected files may still establish a usable effective library when at least one valid quotation remains.

A failed or incomplete enumeration must never be treated as successful discovery of a smaller library.

Diagnostics must identify unreadable sources, failed directory enumeration, rejected files, and invalid entries where possible.

### Validation and rejection

Validate each discovered file before admitting its entry to the effective library.

A malformed or unsupported YAML file is rejected in its entirety.

Because the format defines one entry per file, a structurally invalid entry also excludes that file's entry.

Invalid entries must not invalidate unrelated valid entries.

Entry-fatal conditions include:

- Missing or invalid required fields.
- Invalid entry identifiers.
- Empty quotation collections or invalid quotation members.
- Unknown entry fields.
- Invalid source or attribution values.
- Invalid priority or eligibility declarations.
- Invalid reveal declarations or effective schedules.
- Malformed font, role-face, style, or other structurally invalid entry preferences.

Recoverable action and color-member errors follow their field-specific rules rather than automatically excluding the entry.

Duplicate identifiers must be resolved without relying on discovery order.

When multiple otherwise accepted entries declare the same identifier, exclude every conflicting entry and report the complete conflict. Do not retain whichever file happened to be enumerated first.

The effective library contains only accepted entries and their validated quotation data.

The loader must not fabricate missing quotations, modify authored text, silently reinterpret unsupported expressions, or rewrite user files.

### Selection availability

Load or refresh the effective content library when a new daily selection is required.

An already committed selection does not require its original YAML entry to remain available.

Missing directories, inaccessible content sources, failed enumeration, and completed libraries containing no valid quotations cannot support a new selection.

Such failures must not trigger repetition-history cleanup, commit an empty daily selection, or replace valid authoritative operational state.

A usable effective library containing valid quotations but none eligible for the current logical display date is a different condition.

For that healthy no-eligible-content condition, use the fully revealed application-owned quotation fallback defined in [No-eligible-content fallback](40-SCHEDULING_AND_APPLICATION_LIFECYCLE.md#no-eligible-content-fallback).

The fallback does not create a synthetic committed selection, increment the selection revision, modify repetition history, or append global history.

Do not repeatedly retry eligibility for the same logical date after the healthy no-eligible condition has been established during ordinary operation. Reevaluate for the next logical display date.

Do not use that fallback for unavailable sources, incomplete enumeration, or a library containing no valid quotations.

Content changes are considered at subsequent selection opportunities. Automatic filesystem watching, interactive editing, and immediate reloading of an active selection are not required.

Automated tests must cover:

- Recursive discovery of nested YAML files.
- Non-following behavior for directory and file symlinks.
- Complete enumeration with independently rejected invalid files.
- Deterministic exclusion of conflicting entry identifiers.
- Missing, inaccessible, or incompletely enumerated sources.
- Healthy libraries containing no eligible quotation.
- Healthy no-eligible fallback without synthetic state or history.
- Retry of normal eligibility at the next logical display date.
- No repetition-history cleanup after incomplete discovery.
- No dependence on source files after selection commitment.
- Invalid reveal overrides for absent literary fields.

## Parsing and source rejection

Use a maintained YAML parser with safe loading behavior.

Do not deserialize arbitrary Python objects or execute YAML tags, constructors, or expressions from application configuration, content entries, or asset manifests.

Reject unsupported YAML constructs according to the corresponding public schema.

Configuration and content have separate validation policies.

An unreadable, malformed, or structurally unsupported application-configuration document is not usable. Report an actionable error rather than guessing at its contents.

An invalid content source is excluded independently when discovery has otherwise succeeded.

Do not permit a malformed file to change the meaning of another entry or cause the entire effective library to be discarded when unrelated valid content remains usable.

A failed directory traversal or incomplete discovery is a library-level failure, not an independently rejected entry.

Use stable diagnostic identification rather than relying on filesystem enumeration order.

Do not use mapping order to establish content-selection policy.

Do not introduce speculative YAML repair, multiple-entry file formats, implicit file-based IDs, or unsupported schema extensions.

The authoritative parsing and validation rules belong to [Application Configuration](../schemas/CONFIGURATION.md), [Content Entries](../schemas/CONTENT.md), and [Assets](../schemas/ASSETS.md).

## Configuration acceptance and defaults

Build an effective application configuration from accepted values, documented defaults, and validated resource registries.

The authoritative configuration field names, types, required values, defaults, and error classifications belong to [Application Configuration](../schemas/CONFIGURATION.md).

Do not invent defaults or reinterpret explicitly invalid values to bypass a required constraint.

Missing required values without a supported fallback are fatal.

Unknown configuration fields are diagnosed and handled according to the schema.

Destination `overrides` are strict. Unknown keys, unsupported values, wrong types, or invalid resource identifiers are errors rather than ordinary warning-and-ignore cases.

Configured destination geometry, IDs, audience, capacity, storage paths, font declarations, and other expressly strict fields must satisfy their schema constraints before runtime startup.

Validate global literary insets against the design-canvas aspects used by configured destinations.

Do not reject an otherwise valid configuration solely because its insets would be invalid for an unsupported or unused destination aspect.

When destination configuration introduces an additional aspect, validate the effective global insets for that aspect.

Decoration-specific inset validation uses the same configured-aspect domain, as defined in [Assets](../schemas/ASSETS.md#presentation-insets).

### Diagnostics

Omitted optional configuration and content fields apply their documented defaults or absence semantics silently.

Do not emit informational messages solely to announce an omitted optional value or an ordinary documented default.

An explicitly invalid recoverable value produces an actionable warning identifying the affected field and the resulting exclusion, omission, or documented fallback.

A fatal configuration or library condition produces an actionable error.

Useful operational `INFO` messages remain permitted for actual events that are not configuration or content problems.

Diagnostics must distinguish:

- `INFO`: Relevant operational information without an invalid-value condition.
- `WARNING`: A recoverable invalid value, excluded resource or entry, or other condition that allows valid operation.
- `ERROR`: A required condition that cannot be established for the requested operation.

Do not flood ordinary runtime logs with repeated warnings about unchanged recoverable conditions.

A warning must not be silently converted into a successful interpretation of invalid authored data.

Validation must not rewrite user configuration, content, manifests, or assets.

Automated tests must cover omitted defaults without informational notices, explicitly invalid recoverable values, fatal requirements, strict destination overrides, configured-aspect inset validation, and preservation of authored files.

## Resource registries and pool expansion

Configuration loading owns resource discovery, registration, deterministic collision handling, and construction of effective resource registries and named pools.

The resource types are:

- Font bundles.
- Backgrounds.
- Decorations.
- Palette identifiers and color pools.

Fonts, backgrounds, and decorations have independent registries.

Resource discovery is separate from automatic-selection pool membership.

### Resource discovery and registration

Discover bundled resources through Python package-resource APIs.

Discover user resources recursively beneath the applicable category directories beside the effective configuration file:

- `assets/fonts/`
- `assets/backgrounds/`
- `assets/decorations/`

An alternate configuration file determines its own user-assets root. The working directory and the standard configuration directory do not supply additional user assets when an alternate configuration is selected.

The content directory is independent of the user-assets root.

Do not monitor, modify, or generate files in user-owned resource directories during configuration loading.

Recognize resource-package boundaries and do not register internal package images as independent standalone backgrounds.

Do not follow symlink directories, manifest symlinks, or standalone image symlinks during discovery.

Validate manifest structure, stable identifiers, file references, readability, and applicable resource integrity before registration.

Confine referenced resource files to their owning package.

Reject absolute references, parent traversal, external-path escapes, and unsafe filesystem redirection according to [Assets](../schemas/ASSETS.md#resource-paths).

Invalid resources are excluded independently with actionable diagnostics. Unrelated valid resources remain available.

A successfully registered resource is available by its stable identifier even when it is not included in the default pool.

Do not require explicit resources to be members of an automatic-selection pool.

### Identifier collisions

Resource identifiers are case-sensitive and category-scoped.

Bundled resource declarations with valid claimed identifiers take precedence over custom resources claiming the same identifiers.

A readable bundled manifest with a valid identifier claims that identifier even when another field makes the bundled resource unusable.

A bundled standalone background similarly claims its valid filename-stem identifier.

A custom resource claiming an identifier already claimed by a bundled resource is excluded.

Validate individual custom resources before evaluating collisions among custom registrations.

When multiple otherwise valid custom resources in the same category claim one identifier, exclude all of those conflicting custom resources.

Do not choose a collision winner by discovery or filesystem enumeration order.

An invalid custom resource does not claim its identifier for custom collision detection.

Identifiers in different categories are independent.

### Font registration

Font bundles register their available faces independently of role-face preferences.

Each usable bundle requires a readable, loadable `regular` face.

An invalid, unavailable, or unsafe required regular face excludes the bundle.

An invalid optional face, including an unsafe path, is diagnosed and excluded individually without discarding an otherwise usable bundle.

Do not follow invalid optional paths outside the owning font package.

Malformed optional role-preference metadata is warned about and ignored without automatically excluding an otherwise usable font bundle or decoration.

Registration establishes loadable face availability. It does not determine the eventual winning quotation, source, or attribution role faces.

A syntactically valid role preference may name a face absent from the ultimately selected bundle. Resolve and recover that preference at presentation preparation, following [Font bundles, role faces and recovery](50-PRESENTATION_AND_RENDERING.md#font-bundles-role-faces-and-recovery).

### Background and decoration registration

Register standalone backgrounds and packaged background and decoration resources according to their respective asset schemas.

Source images must satisfy their defined PNG representation, dimension, integrity, and decoded-pixel safety requirements.

Reject invalid required manifest data, unusable source images, and intrinsically invalid layer definitions without excluding unrelated assets.

Validate decoration `presentation_insets` against only the design-canvas aspects used by configured destinations.

Exclude a decoration with insets invalid for any configured aspect, with an actionable warning.

Do not reject a decoration merely because its insets would fail for a supported aspect not used by configured destinations.

Canvas-specific transformation validity remains a preparation responsibility when it cannot be established during registration.

Successful registration does not guarantee every later output-specific composition will succeed.

Ordinary decoration preparation discards an entire selected decoration when any eligible layer fails, then uses the documented no-decoration fallback without modifying the canonical selection.

Strict explicitly requested viewer resources instead report their preparation failures.

These fallback boundaries belong to [Graphical layers and transformations](50-PRESENTATION_AND_RENDERING.md#graphical-layers-and-transformations).

### Named pools and membership

After resource registration, resolve named pools against their category-specific registries and the effective palette.

The five independent namespaces are:

- `fonts.pools`
- `backgrounds.pools`
- `decorations.pools`
- `text.colors.pools`
- `decorations.colors.pools`

Pool references remain within their own category.

The reserved `builtin` pool has category-specific membership defined by [Application Configuration](../schemas/CONFIGURATION.md#pool-declarations).

For file-backed resources, `builtin` contains only successfully registered bundled resources.

Custom or unusable resources must not enter the file-backed `builtin` pool.

Both color `builtin` pools contain the palette identifier `black`.

A configured `@builtin` reference explicitly opts into that category's built-in membership.

Discovery does not automatically add registered assets to the effective default pool.

Do not insert arbitrary discovered resources, emergency resources, or implicit `@builtin` references into configured pools.

Resolve nested named-pool references depth-first in declaration order.

Preserve the first occurrence of each distinct usable identifier.

Skip references on the active recursion path to prevent cyclic expansion; independently shared subpools may still contribute their usable members.

Malformed, unknown, or unavailable members are diagnosed and excluded independently.

Pool expansion does not perform random selection.

Preserve every named pool's actual expanded membership, including an empty pool.

An explicitly referenced empty pool remains empty. It does not silently gain fallback values or bundled members.

Background and decoration pools may explicitly contain the reserved `"none"` absence value.

Automatic background or decoration fallback to `"none"` is distinct from inserting that value into a named pool.

Color pools may fall back to the built-in `black` choice under the defined artistic resolution policy without changing named-pool membership.

### Selection and runtime recovery

Canonical artistic selection uses the registered resources and resolved pools according to [Canonical resolution and resource precedence](50-PRESENTATION_AND_RENDERING.md#canonical-resolution-and-resource-precedence).

A resource may be explicitly preferred by content or decoration even when absent from an automatic-selection pool.

A syntactically valid but unavailable content font, background, or decoration identifier is not an entry-fatal error. Diagnose it and follow the applicable lower-priority preference or preparation recovery behavior.

A syntactically invalid content preference remains subject to the content schema's entry-rejection rules.

The reserved value `"none"` is valid for background and decoration suppression only. A content `font: "none"` is invalid and excludes the entry before selection.

A required `fonts.pools.default` declaration must satisfy the configuration schema even when another usable explicit font preference exists.

The effective default font pool retains its actual usable membership. Do not silently insert bundled fonts into that pool.

Canonical font resolution prefers the entry font, then the selected decoration font, then the effective default font pool.

The unconditional packaged `source-sans-3/regular` resource is an emergency readability fallback during font resolution or preparation. It is not implicit membership in the default or `builtin` pool and must not overwrite a valid persisted canonical choice during runtime recovery.

Destination font overrides remain strict single registered-bundle identifiers applied after canonical selection. They do not define additional pools or independent random selection.

For literary text and decoration colors, distinguish invalid preference structure from invalid individual candidates.

An invalid outer content `text_color` or `decoration_color` declaration excludes the content entry.

Within a structurally valid nonempty sequence, diagnose and exclude invalid member types, malformed identifiers, direct RGB literals, and unavailable candidates individually.

Keep valid candidates. When none remain usable, fall through to the next applicable preference level without invalidating the entry.

Do not combine candidates across preference levels or count duplicate identifiers as additional selection weight.

Color preferences in background and decoration manifests use their separately defined recoverable metadata policy.

A valid complete prepared-image cache remains reusable without rechecking asset availability.

When regeneration is needed, preserve canonical artistic choices from the valid presentation checkpoint and apply current permitted effective resource recovery without literary reselection.

Automated tests must cover:

- Bundled and recursive custom discovery.
- Package boundaries, unsafe references, and symlink exclusion.
- Resource registration independent of pool membership.
- Bundled claims and deterministic custom collisions.
- Required regular and optional font-face validation.
- Configured-aspect decoration inset validation.
- Standalone and packaged background validation.
- Pool names, category isolation, nested expansion, cycles, and deduplication.
- Reserved `builtin` membership without implicit insertion.
- Explicit registered resource preferences outside default pools.
- Empty effective pools and preference fallthrough.
- Valid but unavailable versus syntactically invalid font preferences.
- Unconditional emergency font recovery without pool mutation.
- Strict destination font overrides.
- Content color outer-structure rejection and member-level recovery.
- Preservation of canonical choices during runtime fallback.

## Opaque action declarations

Content entries may declare ordered opaque semantic actions inherited by every quotation in the entry.

Refrain validates the generic action envelope but does not interpret payloads, execute actions, infer external services, or require an action implementation for ordinary presentation.

Action fields, supported visibility audiences, defaults, and authored limits are defined in [Content Entries](../schemas/CONTENT.md#actions).

A malformed action declaration is discarded with an actionable warning without rejecting its containing entry or unrelated valid actions.

A malformed top-level action collection follows the content schema's recoverable empty-sequence behavior.

Preserve valid action declaration order, duplicates, audience declarations, and opaque payload text exactly.

Apply the documented limit of 100 accepted valid actions per entry. Later valid actions exceeding the limit are omitted with a warning; malformed declarations do not consume that limit.

Validate UTF-8 payload byte limits independently of Python character counts.

Represent accepted actions as immutable values in validated entries and committed selection snapshots.

The committed snapshot retains the complete accepted ordered action list.

The shared publication checkpoint also retains that complete list. Destination preparation must not filter or modify it.

At completed scheduled publication finalization, filter an independent copy of the actions to the target destination's explicitly configured `public` or `private` audience.

Do not infer audience from destination naming or treat public and private visibility as hierarchical.

Preserve included actions' original declaration order, duplicates, payloads, and visibility arrays.

Publication-specific action and metadata limits belong to [Destination metadata and audience filtering](70-FILESYSTEM_PUBLICATION_AND_CONSUMERS.md#destination-metadata-and-audience-filtering).

Actions never trigger execution merely because they were selected, prepared, rendered, cached, or published.

Automated tests must cover malformed-action recovery, action-count and payload limits, inheritance, order and duplicate preservation, immutable snapshot capture, checkpoint preservation, destination audience filtering, and absence of implicit execution.