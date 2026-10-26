from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from refrain import (
    ContentEntry,
    EligibilityRule,
    EligibilitySpecificity,
    Quotation,
    build_eligible_quotation_pool,
    load_content_library,
)


def make_entry(
    entry_id: str,
    *rules: EligibilityRule,
    quotations: tuple[str, ...] = ("A synthetic quotation.",),
    priority: int = 0,
    source: str | None = None,
    attribution: str | None = None,
) -> ContentEntry:
    return ContentEntry(
        id=entry_id,
        quotations=tuple(Quotation(text=text, identity=text) for text in quotations),
        source=source,
        attribution=attribution,
        priority=priority,
        eligibility=rules,
    )


@pytest.mark.parametrize(
    ("rule", "display_date", "expected"),
    [
        (EligibilityRule(ordinary=True), date(2026, 2, 1), EligibilitySpecificity.ORDINARY),
        (EligibilityRule(month=2), date(2026, 2, 1), EligibilitySpecificity.MONTH),
        (EligibilityRule(day=31), date(2026, 3, 31), EligibilitySpecificity.DAY),
        (EligibilityRule(month=2, day=29), date(2024, 2, 29), EligibilitySpecificity.MONTH_DAY),
        (
            EligibilityRule(year=2024, month=2, day=29),
            date(2024, 2, 29),
            EligibilitySpecificity.YEAR_MONTH_DAY,
        ),
    ],
)
def test_each_eligibility_specificity_matches(
    rule: EligibilityRule, display_date: date, expected: EligibilitySpecificity
) -> None:
    result = build_eligible_quotation_pool((make_entry("matching", rule),), display_date)

    assert result.specificity is expected
    assert len(result.candidates) == 1


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        ((EligibilityRule(ordinary=True),), EligibilitySpecificity.ORDINARY),
        ((EligibilityRule(ordinary=True), EligibilityRule(month=2)), EligibilitySpecificity.MONTH),
        (
            (EligibilityRule(month=2), EligibilityRule(day=29)),
            EligibilitySpecificity.DAY,
        ),
        (
            (EligibilityRule(day=29), EligibilityRule(month=2, day=29)),
            EligibilitySpecificity.MONTH_DAY,
        ),
        (
            (EligibilityRule(month=2, day=29), EligibilityRule(year=2024, month=2, day=29)),
            EligibilitySpecificity.YEAR_MONTH_DAY,
        ),
    ],
)
def test_successively_higher_matching_rules_win(
    rules: tuple[EligibilityRule, ...], expected: EligibilitySpecificity
) -> None:
    result = build_eligible_quotation_pool((make_entry("entry", *rules),), date(2024, 2, 29))

    assert result.specificity is expected


def test_global_specificity_precedes_priority_and_expands_all_quotations() -> None:
    ordinary = make_entry(
        "ordinary",
        EligibilityRule(ordinary=True),
        quotations=("Ordinary one.", "Ordinary two."),
        priority=10_000,
    )
    month = make_entry("month", EligibilityRule(month=2), priority=500)
    exact = make_entry(
        "exact",
        EligibilityRule(year=2024, month=2, day=29),
        quotations=("Exact one.", "Exact two."),
        priority=-10_000,
        source="Synthetic source",
        attribution="Synthetic author",
    )

    result = build_eligible_quotation_pool((ordinary, month, exact), date(2024, 2, 29))

    assert result.specificity is EligibilitySpecificity.YEAR_MONTH_DAY
    assert {candidate.text for candidate in result.candidates} == {"Exact one.", "Exact two."}
    assert {candidate.priority for candidate in result.candidates} == {-10_000}
    assert all(candidate.entry is exact for candidate in result.candidates)
    assert all(candidate.entry.source == "Synthetic source" for candidate in result.candidates)
    assert all(candidate.entry.attribution == "Synthetic author" for candidate in result.candidates)
    assert {candidate.identity for candidate in result.candidates} == {"Exact one.", "Exact two."}


def test_multiple_entries_contribute_individual_candidates_to_the_winning_pool() -> None:
    first = make_entry(
        "first",
        EligibilityRule(day=17),
        quotations=("First entry, first quotation.", "First entry, second quotation."),
        priority=20,
        source="First source",
    )
    second = make_entry(
        "second",
        EligibilityRule(day=17),
        quotations=("Second entry quotation.",),
        priority=-20,
        source="Second source",
    )

    result = build_eligible_quotation_pool((first, second), date(2026, 10, 17))

    assert result.specificity is EligibilitySpecificity.DAY
    assert {candidate.text for candidate in result.candidates} == {
        "First entry, first quotation.",
        "First entry, second quotation.",
        "Second entry quotation.",
    }
    assert {candidate.entry.id for candidate in result.candidates} == {"first", "second"}
    assert {candidate.priority for candidate in result.candidates} == {-20, 20}


def test_overlapping_rules_and_rule_order_do_not_duplicate_candidates() -> None:
    rules = (
        EligibilityRule(ordinary=True),
        EligibilityRule(month=2),
        EligibilityRule(day=29),
        EligibilityRule(month=2, day=29),
        EligibilityRule(year=2024, month=2, day=29),
    )
    forward = make_entry("entry", *rules, quotations=("First.", "Second."))
    reverse = make_entry("entry", *reversed(rules), quotations=("First.", "Second."))

    first = build_eligible_quotation_pool((forward,), date(2024, 2, 29))
    second = build_eligible_quotation_pool((reverse,), date(2024, 2, 29))

    assert first.specificity is second.specificity is EligibilitySpecificity.YEAR_MONTH_DAY
    assert (
        {candidate.identity for candidate in first.candidates}
        == {candidate.identity for candidate in second.candidates}
        == {"First.", "Second."}
    )
    assert len(first.candidates) == len(second.candidates) == 2


@pytest.mark.parametrize(
    ("display_date", "expected"),
    [
        (date(2024, 2, 29), EligibilitySpecificity.MONTH_DAY),
        (date(2025, 2, 28), None),
        (date(2026, 3, 31), EligibilitySpecificity.DAY),
        (date(2026, 4, 30), None),
    ],
)
def test_recurring_calendar_boundaries(display_date: date, expected: EligibilitySpecificity | None) -> None:
    if display_date.month == 2:
        entry = make_entry("leap", EligibilityRule(month=2, day=29))
    else:
        entry = make_entry("day-31", EligibilityRule(day=31))

    result = build_eligible_quotation_pool((entry,), display_date)

    assert result.specificity is expected
    assert bool(result.candidates) is (expected is not None)


def test_exact_date_rule_matches_only_its_year() -> None:
    entry = make_entry("exact", EligibilityRule(year=2024, month=10, day=17))

    assert build_eligible_quotation_pool((entry,), date(2024, 10, 17)).specificity is (
        EligibilitySpecificity.YEAR_MONTH_DAY
    )
    assert build_eligible_quotation_pool((entry,), date(2025, 10, 17)).specificity is None


def test_empty_library_and_no_matches_return_explicit_empty_results() -> None:
    special_only = make_entry("special", EligibilityRule(month=12))

    for library in ((), (special_only,)):
        result = build_eligible_quotation_pool(library, date(2026, 5, 4))

        assert result.specificity is None
        assert result.candidates == ()


def test_content_library_order_does_not_change_specificity_or_membership() -> None:
    entries = (
        make_entry("month", EligibilityRule(month=2), quotations=("Month.",)),
        make_entry("day", EligibilityRule(day=29), quotations=("Day.",)),
        make_entry("exact", EligibilityRule(year=2024, month=2, day=29), quotations=("Exact.",)),
    )

    first = build_eligible_quotation_pool(entries, date(2024, 2, 29))
    second = build_eligible_quotation_pool(tuple(reversed(entries)), date(2024, 2, 29))

    assert first.specificity is second.specificity is EligibilitySpecificity.YEAR_MONTH_DAY
    assert (
        {candidate.identity for candidate in first.candidates}
        == {candidate.identity for candidate in second.candidates}
        == {"Exact."}
    )


def test_evaluation_does_not_mutate_content_entries() -> None:
    entry = make_entry("entry", EligibilityRule(ordinary=True), quotations=("Preserved.",))
    library = (entry,)

    build_eligible_quotation_pool(library, date(2026, 10, 17))

    assert library == (entry,)
    assert entry.eligibility == (EligibilityRule(ordinary=True),)
    assert entry.quotations == (Quotation(text="Preserved.", identity="Preserved."),)


def test_yaml_loaded_content_can_be_evaluated_without_application_configuration(tmp_path: Path) -> None:
    data = {
        "id": "yaml-entry",
        "priority": -2,
        "source": "YAML source",
        "eligibility": [{"month": 10, "day": 17}],
        "quotations": ["First YAML quotation.", "Second YAML quotation."],
    }
    (tmp_path / "entry.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    library = load_content_library(tmp_path)
    result = build_eligible_quotation_pool(library, date(2026, 10, 17))

    assert result.specificity is EligibilitySpecificity.MONTH_DAY
    assert {candidate.text for candidate in result.candidates} == {
        "First YAML quotation.",
        "Second YAML quotation.",
    }
    assert all(candidate.priority == -2 for candidate in result.candidates)
    assert all(candidate.entry.source == "YAML source" for candidate in result.candidates)


def test_yaml_loader_default_ordinary_eligibility_is_evaluated(tmp_path: Path) -> None:
    data = {"id": "ordinary-entry", "quotations": ["Available every day."]}
    (tmp_path / "entry.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")

    result = build_eligible_quotation_pool(load_content_library(tmp_path), date(2026, 5, 4))

    assert result.specificity is EligibilitySpecificity.ORDINARY
    assert result.candidates[0].text == "Available every day."
