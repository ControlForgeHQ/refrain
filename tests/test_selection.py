from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import TypeVar

import yaml

from refrain import (
    ContentEntry,
    EligibilityRule,
    EligibilitySpecificity,
    EligibleQuotationPool,
    Quotation,
    QuotationCandidate,
    build_eligible_quotation_pool,
    load_content_library,
    normalize_quotation,
    select_quotation,
)

_T = TypeVar("_T")


class FixedRandom(random.Random):
    def __init__(self, *indices: int) -> None:
        super().__init__(0)
        self.indices = list(indices)
        self.populations: list[tuple[object, ...]] = []

    def choice(self, sequence: Sequence[_T]) -> _T:
        self.populations.append(tuple(sequence))
        return sequence[self.indices.pop(0)]


def make_candidate(
    entry_id: str,
    text: str,
    *,
    identity: str | None = None,
    priority: int = 0,
    source: str | None = None,
    attribution: str | None = None,
) -> QuotationCandidate:
    entry = ContentEntry(
        id=entry_id,
        quotations=(Quotation(text=text, identity=identity or normalize_quotation(text)),),
        source=source,
        attribution=attribution,
        priority=priority,
        eligibility=(EligibilityRule(ordinary=True),),
    )
    return QuotationCandidate(quotation=entry.quotations[0], entry=entry)


def make_pool(*candidates: QuotationCandidate) -> EligibleQuotationPool:
    return EligibleQuotationPool(specificity=EligibilitySpecificity.ORDINARY, candidates=candidates)


def test_selects_single_identity_and_proposes_consumption() -> None:
    candidate = make_candidate("only", "One quotation.")
    history: set[str] = set()

    result = select_quotation(make_pool(candidate), history, FixedRandom(0, 0))

    assert result.selected_candidate is candidate
    assert result.proposed_repetition_history == {candidate.identity}
    assert not result.pool_was_reset
    assert history == set()


def test_selects_distinct_equal_priority_identities_without_order_bias() -> None:
    candidates = (
        make_candidate("third", "Third."),
        make_candidate("first", "First."),
        make_candidate("second", "Second."),
    )
    selected: list[str] = []

    for order in (candidates, tuple(reversed(candidates))):
        result = select_quotation(make_pool(*order), (), FixedRandom(1, 0))
        selected.append(result.selected_candidate.identity)

    assert selected == ["Second.", "Second."]


def test_random_choice_population_contains_distinct_identities_not_occurrences() -> None:
    repeated = tuple(make_candidate(f"duplicate-{index}", "Repeated.") for index in range(5))
    other = make_candidate("other", "Other.")
    chooser = FixedRandom(0, 0)

    result = select_quotation(make_pool(*repeated, other), (), chooser)

    assert result.selected_candidate.identity == "Other."
    assert chooser.populations[0] == ("Other.", "Repeated.")


def test_consumed_high_priority_identity_cannot_displace_unused_lower_priority() -> None:
    consumed = make_candidate("consumed", "Consumed.", priority=10_000)
    available = make_candidate("available", "Available.", priority=-10_000)

    result = select_quotation(
        make_pool(consumed, available),
        {consumed.identity},
        FixedRandom(0, 0),
    )

    assert result.selected_candidate is available
    assert result.proposed_repetition_history == {consumed.identity, available.identity}
    assert not result.pool_was_reset


def test_highest_priority_supports_positive_zero_negative_and_unbounded_values() -> None:
    candidates = (
        make_candidate("negative", "Negative.", priority=-(2**100)),
        make_candidate("zero", "Zero.", priority=0),
        make_candidate("positive", "Positive.", priority=2**100),
    )

    result = select_quotation(make_pool(*candidates), (), FixedRandom(0, 0))

    assert result.selected_candidate is candidates[2]


def test_selects_zero_priority_after_positive_identity_is_consumed() -> None:
    positive = make_candidate("positive", "Positive.", priority=1)
    zero = make_candidate("zero", "Zero.", priority=0)
    negative = make_candidate("negative", "Negative.", priority=-1)

    result = select_quotation(
        make_pool(positive, zero, negative),
        {positive.identity},
        FixedRandom(0, 0),
    )

    assert result.selected_candidate is zero


def test_exhausted_single_identity_resets_only_that_pool_identity() -> None:
    candidate = make_candidate("single", "Single.")
    unrelated = "An identity from another context."
    history = {candidate.identity, unrelated}

    result = select_quotation(make_pool(candidate), history, FixedRandom(0, 0))

    assert result.selected_candidate is candidate
    assert result.pool_was_reset
    assert result.proposed_repetition_history == {unrelated, candidate.identity}
    assert history == {unrelated, candidate.identity}


def test_exhausted_pool_resets_selectively_and_reapplies_priority() -> None:
    lower = make_candidate("lower", "Lower.", priority=0)
    higher = make_candidate("higher", "Higher.", priority=4)
    unrelated = "Unrelated."
    history = {lower.identity, higher.identity, unrelated}

    result = select_quotation(make_pool(lower, higher), history, FixedRandom(0, 0))

    assert result.selected_candidate is higher
    assert result.pool_was_reset
    assert result.proposed_repetition_history == {unrelated, higher.identity}
    assert history == {lower.identity, higher.identity, unrelated}


def test_duplicate_normalized_identity_shares_repetition_and_uses_top_priority_occurrence() -> None:
    high = make_candidate(
        "high",
        "Same\n  quotation.",
        priority=5,
        source="High-priority source",
    )
    low = make_candidate(
        "low",
        "Same quotation.",
        priority=-5,
        source="Low-priority source",
    )
    other = make_candidate("other", "Other.", priority=5)

    result = select_quotation(make_pool(low, other, high), (), FixedRandom(1, 0))

    assert high.identity == low.identity == "Same quotation."
    assert result.selected_candidate is high
    assert result.selected_candidate.entry.source == "High-priority source"
    assert result.proposed_repetition_history == {high.identity}


def test_duplicate_occurrences_with_different_metadata_resolve_the_selected_occurrence() -> None:
    first = make_candidate("a", "Shared.", source="First source", attribution="First author")
    second = make_candidate("b", "Shared.", source="Second source", attribution="Second author")

    result = select_quotation(make_pool(second, first), (), FixedRandom(0, 1))

    assert result.selected_candidate is second
    assert result.selected_candidate.entry.source == "Second source"
    assert result.selected_candidate.entry.attribution == "Second author"


def test_pool_membership_is_evaluated_dynamically_for_each_context() -> None:
    shared = make_candidate("shared", "Shared.")
    current = make_candidate("current", "Current.")
    history = {shared.identity, "Unrelated."}

    current_result = select_quotation(make_pool(shared, current), history, FixedRandom(0, 0))
    shared_result = select_quotation(make_pool(shared), history, FixedRandom(0, 0))

    assert current_result.selected_candidate is current
    assert not current_result.pool_was_reset
    assert current_result.proposed_repetition_history == {shared.identity, "Unrelated.", current.identity}
    assert shared_result.selected_candidate is shared
    assert shared_result.pool_was_reset
    assert shared_result.proposed_repetition_history == {"Unrelated.", shared.identity}


def test_proposed_history_carries_shared_identity_into_selective_reset_in_another_context() -> None:
    shared_first = make_candidate("shared-first", "Shared.")
    first_context_only = make_candidate("first-context", "First context.")
    second_context_only = make_candidate("second-context", "Second context.")
    unrelated = "Unrelated."
    initial_history = {second_context_only.identity, unrelated}

    first_result = select_quotation(
        make_pool(shared_first, first_context_only),
        initial_history,
        FixedRandom(1, 0),
    )
    shared_second = make_candidate("shared-second", "Shared.", source="Second context source")
    second_result = select_quotation(
        make_pool(shared_second, second_context_only),
        first_result.proposed_repetition_history,
        FixedRandom(1, 0),
    )

    assert first_result.selected_candidate is shared_first
    assert first_result.proposed_repetition_history == {
        shared_first.identity,
        second_context_only.identity,
        unrelated,
    }
    assert second_result.selected_candidate is shared_second
    assert second_result.pool_was_reset
    assert second_result.proposed_repetition_history == {shared_second.identity, unrelated}
    assert initial_history == {second_context_only.identity, unrelated}


def test_empty_pool_returns_nonexceptional_unchanged_proposal() -> None:
    history = {"Previously consumed."}

    result = select_quotation(make_pool(), history, FixedRandom())

    assert result.selected_candidate is None
    assert result.proposed_repetition_history == history
    assert not result.pool_was_reset
    assert history == {"Previously consumed."}


def test_repeated_proposals_are_deterministic_and_do_not_mutate_inputs() -> None:
    candidates = (make_candidate("one", "One."), make_candidate("two", "Two."))
    pool = make_pool(*candidates)
    history = {candidates[0].identity}
    chooser_one = FixedRandom(0, 0)
    chooser_two = FixedRandom(0, 0)

    first = select_quotation(pool, history, chooser_one)
    second = select_quotation(pool, history, chooser_two)

    assert first == second
    assert first.selected_candidate is candidates[1]
    assert first.proposed_repetition_history == {"One.", "Two."}
    assert history == {"One."}
    assert pool.candidates == candidates


def test_yaml_content_to_eligible_pool_to_provisional_selection(tmp_path: Path) -> None:
    data = {
        "id": "yaml-entry",
        "priority": -2,
        "source": "YAML source",
        "attribution": "YAML author",
        "eligibility": [{"month": 10, "day": 26}],
        "quotations": ["First YAML quotation.", "Second YAML quotation."],
    }
    (tmp_path / "entry.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    entries = load_content_library(tmp_path)
    pool = build_eligible_quotation_pool(entries, date(2026, 10, 26))
    proposal = select_quotation(pool, (), FixedRandom(1, 0))

    assert proposal.selected_candidate.text == "Second YAML quotation."
    assert proposal.selected_candidate.entry.source == "YAML source"
    assert proposal.selected_candidate.entry.attribution == "YAML author"
    assert proposal.selected_candidate.priority == -2
    assert proposal.proposed_repetition_history == {"Second YAML quotation."}
    assert not proposal.pool_was_reset
