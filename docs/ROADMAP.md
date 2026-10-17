# Roadmap

This document defines the planned evolution of Refrain.

It is authoritative for release goals, feature sequencing, milestone scope, and future product direction.

Runtime architecture and behavioral contracts belong in `docs/ARCHITECTURE.md`.

Engineering standards and implementation practices belong in `docs/ENGINEERING.md`.

Features planned for later releases must not be implemented early unless explicitly requested by an approved issue.

The roadmap describes the intended product outcome, not the implementation strategy.

---

# Version 0.1.0 — Core e-paper presentation

## Goal

Deliver a reliable, self-contained quotation display that selects one eligible entry per display day and progressively reveals information on a physical e-paper screen.

The first release should be useful in normal household operation without depending on a web interface, cloud service, or external integration.

## Required capabilities

### Content library

- Load quotation entries from local YAML files.
- Use stable entry identifiers independent of filenames.
- Support defined semantic fields for primary content, source, and attribution.
- Support entries whose optional attribution or source fields are absent.
- Validate the content library and provide actionable diagnostics.
- Support local content authoring without a content-management application.

### Daily content selection

- Select one eligible entry per logical display day.
- Support a configurable timezone and display-day start time.
- Support ordinary and special-date content eligibility.
- Give matching special-date content precedence over ordinary content.
- Maintain independent repetition histories for ordinary and special-date selection contexts.
- Exhaust eligible entries before repeating them within a selection cycle.
- Preserve the selected entry and required history across application restarts.

### Progressive reveals

- Reveal the primary quotation at the first scheduled presentation stage.
- Reveal additional semantic fields at configured times.
- Provide global default reveal scheduling with optional per-entry overrides.
- Preserve previously revealed information as new fields appear.
- Resume the stage appropriate to the current time after startup or interruption.
- Skip missed intermediate updates rather than replaying them.

### Visual presentation

- Produce complete 1600 × 1200 presentation images.
- Provide one attractive, typography-first default layout.
- Support meaningful typography and spacing configuration.
- Preserve the primary quotation's positioning across reveal stages.
- Reserve layout space for information revealed later.
- Support predominantly dark text on a paper-white background, with optional restrained color accents.
- Handle content that cannot fit the layout without silent truncation.

### Physical display

- Support the Waveshare 13.3-inch e-Paper HAT+ (E).
- Operate on Raspberry Pi OS Lite, initially targeting Raspberry Pi 3 B+.
- Perform complete display updates at the configured reveal stages and display-day boundary.
- Avoid unnecessary refreshes.
- Handle recoverable display communication failures.
- Preserve the existing image when practical during application failures or restarts.
- Support normal unattended operation and graceful shutdown.

### Development and validation

- Allow content selection and presentation rendering to be exercised without display hardware.
- Include automated coverage for selection, scheduling, persistence, validation, and rendering behavior where practical.
- Provide an inspectable rendered-image output for development and troubleshooting.
- Validate physical display behavior on the target hardware.
- Document installation, configuration, content creation, and ordinary operation.

## Non-goals

Version 0.1 does not include:

- a companion website;
- public internet publishing;
- a browser-based content editor;
- Music Assistant integration;
- external playback actions;
- remote administration;
- content synchronization between devices;
- multiple physical display targets;
- multiple presentation themes;
- a general plugin system;
- online quotation retrieval;
- animations or partial-refresh effects.

The priority is correctness, unattended reliability, and a polished physical presentation.

---

# Version 0.2.0 — Companion web presentation

## Goal

Make the current Refrain presentation accessible through a companion web experience without changing the daily-selection model or requiring a public deployment.

The companion experience should provide a convenient way to view the day's quotation and explore its associated information from a phone or other browser.

## Planned capabilities

- Provide a local browser-accessible presentation of the current content.
- Display the current quotation and appropriately revealed information.
- Support responsive presentation on phones, tablets, and desktop browsers.
- Present relevant source information and optional links where available.
- Preserve the physical display as an independent presentation destination.
- Avoid requiring public internet access or third-party hosting.
- Define a clear interface for obtaining presentation information without duplicating content-selection policy.

## Non-goals

Version 0.2 does not require:

- public hosting;
- internet-facing administrative interfaces;
- a content editor;
- media playback integration;
- user accounts;
- cloud synchronization;
- a general-purpose API platform.

The objective is a useful local companion, not a comprehensive web-management application.

---

# Future development — External actions

## Goal

Allow selected content to offer optional contextual actions without introducing external-service dependencies into Refrain's core presentation behavior.

Music Assistant playback is the initial intended use case.

## Potential capabilities

- Associate supported actions with selected content entries.
- Expose appropriate actions through an interactive presentation.
- Invoke configured local integrations.
- Allow playback through Music Assistant where the integration is enabled.
- Restrict privileged actions to authorized local users or interfaces.
- Continue normal content presentation when an optional integration is unavailable.

## Constraints

External actions must remain separate from content selection and rendering.

An entry must remain displayable when its associated action cannot be executed.

External integrations must not be reachable through anonymous public presentation merely because that presentation exposes the content.

The first external action should establish a real demonstrated requirement before the project introduces a general integration framework.

---

# Future development — Optional public publishing

## Goal

Allow Refrain content to be viewed outside the local network without exposing privileged operations or requiring direct inbound access to the primary display device.

## Potential capabilities

- Publish a restricted, presentation-safe representation of the current content.
- Support deployment of the public presentation on a separate host.
- Update published content as the daily selection and reveal stage change.
- Operate without exposing local administrative or playback interfaces.
- Make public publishing entirely optional.

## Constraints

Public presentation and privileged local operation must have distinct trust boundaries.

A separate public deployment must not require unrestricted access to the primary Refrain host or trusted local services.

An outbound-only publishing model is preferred where it meets the requirements.

Authentication, publication transport, hosting, and update semantics must be reviewed before implementation.

---

# Future development — Content authoring and presentation enhancements

These capabilities may be considered after the core presentation and companion experience are established.

## Potential capabilities

- A browser-based content editor.
- Improved content library browsing and validation.
- Additional presentation layouts.
- Expanded typography and visual customization.
- Additional scheduling and eligibility rules when required.
- Content import and export.
- More convenient installation and update workflows.

These items are not commitments to a particular release.

Each should be evaluated against demonstrated user needs and the added maintenance cost.

---

# Release priorities

Development should proceed in the following order:

1. Establish repository documentation, engineering standards, and contributor workflow.
2. Define and validate the initial content and configuration contracts.
3. Implement and test content loading, daily selection, and persistent state.
4. Implement and test reveal scheduling and hardware-independent rendering.
5. Integrate and validate the physical e-paper display.
6. Establish reliable unattended operation on the target Raspberry Pi.
7. Complete Version 0.1 validation, documentation, and release.
8. Proceed to the companion web presentation.
9. Evaluate later integrations and public publishing independently.

Implementation work should be divided into narrowly scoped GitHub issues, each with observable acceptance criteria and appropriate validation requirements.

Version 0.1 is complete only when the required behavior has been demonstrated, substantive review findings have been resolved, and the physical display has been validated on the target hardware.