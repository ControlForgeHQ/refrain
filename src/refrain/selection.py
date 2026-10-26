"""Propose repetition-aware quotation selections."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from .eligibility import EligibleQuotationPool, QuotationCandidate


@dataclass(frozen=True)
class SelectionProposal:
    """A provisional candidate and the repetition history proposed with it."""

    selected_candidate: QuotationCandidate | None
    proposed_repetition_history: frozenset[str]
    pool_was_reset: bool
    base_revision: int = 0


def select_quotation(
    pool: EligibleQuotationPool,
    repetition_history: Iterable[str],
    random_source: random.Random | None = None,
    *,
    base_revision: int = 0,
) -> SelectionProposal:
    """Propose a selection without modifying inputs, tied to its source state revision."""
    if type(base_revision) is not int or base_revision < 0:
        raise ValueError("base_revision must be a nonnegative integer")
    history = set(repetition_history)
    if not pool.candidates:
        return SelectionProposal(
            selected_candidate=None,
            proposed_repetition_history=frozenset(history),
            pool_was_reset=False,
            base_revision=base_revision,
        )

    pool_identities = {candidate.identity for candidate in pool.candidates}
    unused_identities = pool_identities - history
    pool_was_reset = not unused_identities
    if pool_was_reset:
        history.difference_update(pool_identities)
        unused_identities = pool_identities

    eligible_candidates = [candidate for candidate in pool.candidates if candidate.identity in unused_identities]
    highest_priority = max(candidate.priority for candidate in eligible_candidates)
    highest_priority_candidates = [
        candidate for candidate in eligible_candidates if candidate.priority == highest_priority
    ]
    identities = sorted({candidate.identity for candidate in highest_priority_candidates})

    chooser = random_source if random_source is not None else random.Random()
    selected_identity = chooser.choice(identities)
    matching_occurrences = sorted(
        (candidate for candidate in highest_priority_candidates if candidate.identity == selected_identity),
        key=lambda candidate: candidate.entry.id,
    )
    selected_candidate = chooser.choice(matching_occurrences)
    history.add(selected_identity)

    return SelectionProposal(
        selected_candidate=selected_candidate,
        proposed_repetition_history=frozenset(history),
        pool_was_reset=pool_was_reset,
        base_revision=base_revision,
    )
