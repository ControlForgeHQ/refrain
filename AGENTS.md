# AGENTS.md

This file provides mandatory repository-wide instructions.

## Protected documents

Never modify the following files:

- `AGENTS.md`
- `docs/AI_WORKFLOW.md`
- `README.md` (repository root)

Modify `docs/ARCHITECTURE.md` or `docs/ENGINEERING.md` only when explicitly authorized to modify the specific document. Permission must not be inferred from an implementation request, even when the implementation affects documented behavior.

If implementation reveals that a protected document is incorrect, ambiguous, contradictory, or outdated, report the discrepancy and recommend a specific correction without modifying the document.

## Conflicts and ambiguity

If an assigned requirement conflicts with these instructions, is internally contradictory, or requires a material decision not covered by the approved scope, stop and report the conflict.

Existing architectural or engineering documentation does not prevent implementing an explicitly approved change to Refrain's behavior. Proceed with the approved implementation and report any resulting documentation discrepancies or required updates.

Do not silently reinterpret ambiguous requirements, make unapproved architectural decisions, or expand the assigned scope.

## Mandatory development workflow

Before beginning work, read `docs/AI_WORKFLOW.md` in full and follow its instructions.

That document defines the authoritative documentation directory, development procedures, implementation expectations, and review requirements.

If `docs/AI_WORKFLOW.md` is unavailable, contradictory, or cannot be followed without violating the restrictions above, stop and report the problem rather than proceeding.
