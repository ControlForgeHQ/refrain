# AGENTS.md

This file provides repository-wide instructions for automated contributors working on Refrain.

It is an entry point to the project's authoritative documentation, not a replacement for that documentation.

## Read the project documentation

Before making substantive changes, read the relevant project documents:

1. `docs/ROADMAP.md`
2. `docs/ARCHITECTURE.md`
3. `docs/ENGINEERING.md`
4. `docs/CONTENT_FORMAT.md`, when working with content, configuration, validation, or public YAML interfaces

These documents have distinct responsibilities:

- `docs/ROADMAP.md` defines product scope, release goals, and development priorities.
- `docs/ARCHITECTURE.md` defines runtime behavior, component boundaries, persistent-state semantics, and architectural invariants.
- `docs/ENGINEERING.md` defines implementation standards, dependency practices, testing, deployment, and review requirements.
- `docs/CONTENT_FORMAT.md` defines the public YAML configuration and content-entry schemas.

Do not treat instructions in this file as a substitute for those documents.

For AI-assisted development procedures, consult `docs/AI_WORKFLOW.md`.

## Respect documentation ownership

Each authoritative document owns a distinct category of project information.

Do not duplicate architectural behavior, engineering requirements, public schema definitions, or release planning across multiple documents.

When updating documentation:

- identify the document responsible for the information;
- preserve its existing terminology, organization, and purpose;
- update other documents only where consistency requires it;
- prefer references over duplicating authoritative requirements.

If documentation is inconsistent, identify the conflict rather than silently choosing an interpretation.

If a requested change requires a material architectural decision, raise that decision for review before implementing it.

## Follow the assigned scope

Implement only the behavior requested by the assigned GitHub issue or explicit instruction.

Do not:

- implement deferred roadmap features early;
- introduce speculative abstractions or extensibility frameworks;
- perform unrelated refactoring;
- expand public configuration interfaces without authorization;
- add unnecessary runtime dependencies or background services;
- replace established architectural decisions with alternative designs without review.

Prefer the smallest maintainable change that satisfies the stated requirements.

When requirements are ambiguous, consult the relevant authoritative documentation before making assumptions.

## Preserve architectural boundaries

Maintain the responsibilities established in `docs/ARCHITECTURE.md`.

In particular, do not:

- place quotation-selection policy in rendering or display-output code;
- introduce hardware dependencies into hardware-independent components;
- allow presentation failures to cause an already committed quotation to be reselected;
- bypass the established persistent-state commitment and recovery semantics;
- redefine quotation identity or selection precedence within individual components;
- modify committed presentation state merely because source content or configuration changes.

Do not introduce additional processes, external services, or generic plugin mechanisms without an approved requirement.

The initial implementation must remain appropriate for resource-constrained Raspberry Pi hardware.

## Respect public interfaces

The YAML configuration and content-entry formats are public interfaces.

Use `docs/CONTENT_FORMAT.md` as the authority for their field names, value types, defaults, and validation rules.

Do not silently introduce undocumented fields, reinterpret existing values, or change established defaults.

Changes to public interfaces require corresponding specification updates and compatibility consideration.

Persistent internal state is not automatically a public interface, but its compatibility and recovery requirements must still be respected.

## Validate honestly

Follow the validation requirements in `docs/ENGINEERING.md` and the assigned issue.

Add focused regression tests where practical.

Distinguish between:

- automated tests;
- hardware-independent integration tests;
- simulated or mocked hardware tests;
- validation performed on actual Raspberry Pi and e-paper hardware.

Do not claim physical hardware validation unless actual hardware was used.

If required validation cannot be performed in the implementation environment, report the limitation explicitly.

Do not treat successful imports, compilation, or mocked tests as proof of correct physical display behavior.

## Pull-request workflow

Create implementation pull requests as drafts.

Keep each implementation pull request focused on one GitHub issue unless the approved scope explicitly requires otherwise.

When a pull request is intended to complete an issue, include an explicit closing reference in its description:

```text
Closes #<issue>
```

A descriptive issue reference alone is insufficient when the issue should close on merge.

The pull request must summarize:

- the implementation and its purpose;
- the related issue;
- validation performed;
- validation not performed;
- significant assumptions or limitations;
- relevant documentation changes.

When completing an implementation issue, provide a concise completion summary identifying the principal files changed.

When addressing review feedback, update the existing pull request.

Add a PR conversation comment summarizing:

- the requested changes addressed;
- implementation revisions;
- additional validation performed;
- remaining limitations, if any.

Preserve the pull-request discussion as the durable record of implementation decisions and review outcomes.

Do not merge a pull request or create additional issues unless explicitly authorized.

## When requirements conflict

If a task cannot be completed correctly without:

- changing documented architecture;
- violating an architectural invariant;
- expanding the assigned scope materially;
- changing a public interface unexpectedly;
- introducing an unapproved major dependency or service;
- making an unresolved design decision;

stop and explain the conflict.

Do not silently redesign Refrain to make the immediate task easier.

An implementation is complete only when its acceptance criteria are satisfied, required validation is reported, and substantive review feedback has been resolved.