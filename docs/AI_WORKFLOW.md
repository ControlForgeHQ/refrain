# AI-Assisted Development Workflow

## Purpose

Refrain uses AI-assisted implementation as part of its normal development workflow.

`AGENTS.md` establishes mandatory repository-wide restrictions and directs contributors to this document.

This document defines the authoritative documentation responsibilities and the procedures for preparing, implementing, reviewing, validating, and revising AI-assisted development work.

## Source of truth

GitHub is the authoritative record of Refrain's implementation requirements, decisions, and development history.

The authoritative sources for implementation work are:

- `AGENTS.md` and this document, which establish mandatory contributor instructions and development procedures;
- the project documentation identified in the following section, which establishes existing system behavior, engineering requirements, and public interfaces;
- the assigned GitHub issue, which defines the approved scope, requirements, and acceptance criteria for the implementation.

An explicitly approved requirement may supersede existing documented behavior. Follow the approved requirement and report any resulting documentation discrepancies in accordance with `AGENTS.md`.

For revision work, the existing pull request, its review feedback, and its discussion additionally establish the requested changes.

Accepted decisions must be recorded in the appropriate repository documentation, GitHub issue, or pull-request discussion. Chat conversations are not substitutes for those records.

Implementation prompts should direct agents to these sources rather than duplicate their contents.

## Documentation ownership and changes

Read `docs/ARCHITECTURE.md` and `docs/ENGINEERING.md` in full before beginning implementation or revision work. Read other documentation relevant to the assigned task.

The authoritative documentation has distinct responsibilities:

- `docs/ARCHITECTURE.md` defines system behavior, component boundaries, persistent-state semantics, and architectural invariants.
- `docs/ENGINEERING.md` defines technical implementation standards, supported platforms, dependency constraints, and testing requirements.
- `docs/CLI.md` defines the public command-line interface, including commands, arguments, accepted values, results, and diagnostics.
- `docs/schemas/` contains the authoritative definitions of Refrain's data formats, including configuration, content, resources, publication, and persistent state where applicable.

Schema documents define data structures, field types, valid values, defaults, and validation constraints. They do not independently define runtime behavior. Runtime behavior belongs in Architecture; implementation requirements belong in Engineering.

Each requirement must have one authoritative owner. Reference that owner rather than duplicating requirements across documents. Report inconsistencies or ambiguities instead of silently choosing an interpretation.

Follow the document-editing restrictions in `AGENTS.md`. In particular, implementation work does not authorize changes to Architecture or Engineering unless the assigned instructions explicitly permit changes to the specific document.

When implementing an approved public-interface change, update the relevant CLI and schema documentation as part of the implementation. These updates must accurately describe the approved interface and must not introduce additional fields, commands, defaults, validation rules, or behavior beyond the authorized scope.

If implementation reveals that protected documentation is incorrect, incomplete, ambiguous, contradictory, or outdated, identify the affected document and section, explain the discrepancy, and recommend a specific correction in the pull-request discussion. Do not modify the protected document without the authorization required by `AGENTS.md`.

Every pull request must identify changes to public interfaces and their associated documentation. Explicitly describe changes to field names, accepted values, defaults, validation rules, command syntax, and externally observable results. Changes to CLI and schema documentation require specific maintainer review.

## Pull-request requirements

Create a draft pull request for the assigned GitHub issue. Keep the implementation within the approved scope and use the existing pull request for subsequent revisions.

When the pull request is intended to complete the assigned issue, include an explicit closing reference in its description:

```text
Closes #<issue>
```

The pull-request description must identify:

- the assigned issue and the implementation completed;
- significant implementation decisions or assumptions;
- tests and validation performed, including any limitations;
- changes to public interfaces and their associated documentation;
- documentation discrepancies requiring maintainer attention.

Do not merge pull requests or create additional GitHub issues without explicit authorization.

### Responding to review feedback

Treat the linked issue, existing pull request, and recorded review discussion as the authoritative context for revisions.

Address the requested feedback without introducing unrelated changes. If a correction requires an unapproved architectural decision or material scope expansion, report the conflict rather than proceeding.

Update the existing pull request rather than creating a replacement.

After making revisions, add a PR conversation comment summarizing:

- the feedback addressed;
- the changes made;
- additional validation performed;
- any remaining limitations or unresolved concerns.

Preserve the original pull-request description and chronological review discussion. Do not replace the original description with revision summaries.

## Validation

Follow the testing and validation requirements in `docs/ENGINEERING.md` and the assigned issue.

Run applicable automated tests in the implementation environment and report their results, including any tests that could not be performed.

GitHub Actions checks require maintainer approval before execution. Do not wait for CI approval or successful CI results before submitting the draft pull request.

When CI results are available, investigate failures reported through review feedback and correct them within the approved scope. Do not claim that CI has passed unless successful results have been verified for the current pull-request head.

Clearly distinguish:

- tests performed in the implementation environment;
- GitHub Actions results, when available;
- mocked, simulated, or hardware-independent validation;
- validation performed on actual supported hardware.

Report failed, pending, cancelled, unavailable, or unperformed checks and tests accurately. Never represent them as successful.

Do not claim physical hardware validation unless testing was actually performed on the relevant hardware. Identify hardware-dependent behavior that remains unverified.

Summarize validation performed and outstanding limitations in the pull-request description. Report additional validation results when responding to review feedback.
