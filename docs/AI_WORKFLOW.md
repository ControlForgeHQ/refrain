# AI-Assisted Development Workflow

## Purpose

Refrain uses AI-assisted implementation as part of its normal development workflow.

AI implementation agents are treated as contributors whose work is specified, reviewed, validated, and merged through GitHub issues and pull requests.

Project-wide contributor instructions are defined in `AGENTS.md`.

Architecture, engineering standards, public configuration formats, and product direction are defined in the repository documentation referenced by `AGENTS.md`.

This document defines only the workflow used to launch, review, and revise AI-assisted implementation work.

## Source of truth

GitHub is the durable record for implementation work.

The authoritative sources for an implementation are:

- the assigned GitHub issue;
- `AGENTS.md`;
- the project documentation referenced by `AGENTS.md`.

For revision work, the authoritative sources additionally include:

- the existing pull request;
- review comments;
- PR discussion.

Launch prompts should direct implementation agents to these sources rather than duplicating their contents.

Chat discussions may be used to explore design decisions and prepare implementation issues, but accepted decisions must be recorded in the appropriate repository artifacts.

## Normal workflow

The normal implementation cycle is:

1. Define one independently reviewable capability or bug fix.
2. Create a GitHub issue describing the required outcome and acceptance criteria.
3. Launch the implementation agent using the standard implementation prompt.
4. Review the resulting draft pull request.
5. Record requested changes in the GitHub PR review or discussion.
6. If revisions are required, launch the agent using the standard PR update prompt.
7. Re-review the updated pull request.
8. Perform manual or hardware validation where required.
9. Record significant validation results or limitations in the PR discussion.
10. Merge only after review and validation succeed.

Issues should remain narrowly scoped.

Pull requests should normally correspond to one implementation issue.

Significant architectural decisions must be resolved before implementation begins.

## Preparing implementation issues

Issues should define the desired result without unnecessarily prescribing the implementation.

An implementation issue should identify:

- the problem or missing capability;
- the intended outcome;
- the scope of the work;
- relevant architectural or public-interface constraints;
- observable acceptance criteria;
- required tests and validation;
- required documentation changes;
- explicit non-goals where useful.

Reference authoritative project documentation rather than copying its requirements into every issue.

Implementation details may be prescribed when they are necessary to preserve an established design decision or prevent a known failure mode.

Avoid combining unrelated functionality merely because it touches the same component.

Where possible, prefer issues that produce independently testable and reviewable progress.

An issue requiring unresolved architectural decisions is not ready for implementation.

## Standard implementation prompt

Use the following prompt to launch an AI implementation agent.

Only the GitHub issue URL should normally need to change.

```text
Implement the GitHub issue:

https://github.com/ControlForgeHQ/refrain/issues/<issue>

Read and follow AGENTS.md before making changes.

Read the linked issue in its entirety and implement it exactly as specified.

If you cannot access the issue or required repository documentation, stop and explain why rather than guessing.

Create a draft pull request when the implementation is complete.

Do not merge the pull request or open additional issues.
```

The implementation agent is expected to obtain architecture, engineering, validation, documentation, and scope guidance through `AGENTS.md` and the documents it references.

Do not duplicate those instructions in the launch prompt.

The GitHub issue is responsible for describing the specific task.

## Standard PR update prompt

Use the following prompt when an existing pull request requires changes.

Only the pull-request URL should normally need to change.

```text
Address the latest unresolved review feedback and discussion on this pull request:

https://github.com/ControlForgeHQ/refrain/pull/<pr>

Read and follow AGENTS.md before making changes.

Use the existing pull request, its linked implementation issue, and the recorded review discussion as the authoritative specification for this revision.

Address only the requested feedback.

If the requested changes require a material scope or architecture change, stop and explain the conflict rather than broadening the implementation automatically.

Update the existing draft pull request rather than creating a new one.

After completing the revision, add a PR conversation comment summarizing the changes and validation performed.

Do not merge the pull request or open additional issues.
```

Revision summaries belong in PR conversation comments rather than replacing the original PR description.

This preserves the chronological request-response history.

## Pull-request review

AI-generated pull requests are reviewed using the same standards as other contributions.

Review should determine whether:

- the assigned issue was implemented correctly;
- scope was respected;
- documented architecture was preserved;
- public interfaces remain consistent with their specifications;
- persistent-state and recovery behavior are correct;
- component and resource ownership remain clear;
- dependencies are justified;
- regression coverage is adequate;
- documentation changes are correct and appropriately located;
- required validation was performed;
- hardware-dependent behavior remains unverified where actual hardware testing was unavailable.

Review feedback should distinguish required corrections from recommended improvements and optional polish.

Substantive feedback must be recorded in GitHub rather than existing only in a separate AI conversation.

This allows human reviewers and implementation agents to work from the same durable history.

## Revision cycle

The normal revision cycle is:

```text
GitHub issue
    |
    v
implementation agent
    |
    v
draft pull request
    |
    v
review
    |
    +-- accepted --> validation / merge
    |
    +-- changes requested
            |
            v
       GitHub review feedback
            |
            v
       implementation agent
            |
            v
       updated PR
            |
            v
       PR response summary
            |
            v
       re-review
```

Avoid reproducing detailed review instructions in the PR update prompt.

The review discussion itself should contain the required technical context.

Do not close substantive review findings solely because a new implementation has been pushed.

Verify that the revised implementation addresses the finding.

## Validation

Automated regression validation is part of implementation.

Manual and physical hardware validation may be completed during review when the implementation environment cannot perform it.

Refrain's hardware-independent components should be testable without a Raspberry Pi or e-paper display.

Hardware-dependent changes require appropriate validation on the supported target hardware before they can be considered fully verified.

When hardware validation materially increases confidence in a change, record the results in the PR discussion.

Do not infer actual hardware validation from mocked, simulated, or hardware-independent tests.

Validation limitations must remain visible until resolved or explicitly accepted.

## Completing an issue

An implementation issue is complete when:

- its acceptance criteria have been satisfied;
- required tests and validation have been completed or explicitly resolved;
- necessary documentation updates are included;
- substantive review findings have been addressed;
- the implementation has been accepted and merged.

The existence of a working implementation or an open pull request does not, by itself, establish completion.

Do not close issues prematurely when required hardware validation or significant review work remains outstanding.

## Workflow principles

The AI workflow should remain intentionally thin.

Project knowledge belongs in:

- authoritative repository documentation;
- GitHub issues;
- pull-request discussions and reviews.

The launch prompt exists only to direct the agent to these sources and define the immediate GitHub workflow action.

If the standard prompt begins accumulating architecture, coding standards, validation requirements, or issue-specific implementation guidance, that information probably belongs elsewhere.

The workflow should evolve when repeated experience shows that a change improves implementation quality, review quality, traceability, or efficiency.