"""Evaluate content eligibility and construct quotation candidate pools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from typing import Iterable, Optional

from .content import ContentEntry, EligibilityRule, Quotation


class EligibilitySpecificity(IntEnum):
    """Supported eligibility levels, ordered from lowest to highest."""

    ORDINARY = 0
    MONTH = 1
    DAY = 2
    MONTH_DAY = 3
    YEAR_MONTH_DAY = 4


@dataclass(frozen=True)
class QuotationCandidate:
    """A quotation and the content-entry metadata it inherits."""

    quotation: Quotation
    entry: ContentEntry

    @property
    def text(self) -> str:
        """Return the quotation's original display text."""
        return self.quotation.text

    @property
    def identity(self) -> str:
        """Return the quotation's normalized identity."""
        return self.quotation.identity

    @property
    def priority(self) -> int:
        """Return the containing entry's priority."""
        return self.entry.priority


@dataclass(frozen=True)
class EligibleQuotationPool:
    """The candidates at the highest matching specificity for a display date."""

    specificity: Optional[EligibilitySpecificity]
    candidates: tuple[QuotationCandidate, ...]


def _matching_specificity(rule: EligibilityRule, display_date: date) -> Optional[EligibilitySpecificity]:
    if rule.year is not None and rule.month is not None and rule.day is not None:
        if (rule.year, rule.month, rule.day) == (display_date.year, display_date.month, display_date.day):
            return EligibilitySpecificity.YEAR_MONTH_DAY
    elif rule.month is not None and rule.day is not None:
        if (rule.month, rule.day) == (display_date.month, display_date.day):
            return EligibilitySpecificity.MONTH_DAY
    elif rule.day is not None:
        if rule.day == display_date.day:
            return EligibilitySpecificity.DAY
    elif rule.month is not None:
        if rule.month == display_date.month:
            return EligibilitySpecificity.MONTH
    elif rule.ordinary:
        return EligibilitySpecificity.ORDINARY
    return None


def build_eligible_quotation_pool(content_library: Iterable[ContentEntry], display_date: date) -> EligibleQuotationPool:
    """Return quotation candidates at the highest specificity matching ``display_date``.

    The input is expected to contain validated entries, as returned by
    ``load_content_library``. Entries and their quotations are not modified.
    """
    eligible_entries: list[tuple[ContentEntry, EligibilitySpecificity]] = []
    for entry in content_library:
        matching = (
            specificity
            for rule in entry.eligibility
            if (specificity := _matching_specificity(rule, display_date)) is not None
        )
        specificity = max(matching, default=None)
        if specificity is not None:
            eligible_entries.append((entry, specificity))

    winning_specificity = max((specificity for _, specificity in eligible_entries), default=None)
    candidates = tuple(
        QuotationCandidate(quotation=quotation, entry=entry)
        for entry, specificity in eligible_entries
        if specificity == winning_specificity
        for quotation in entry.quotations
    )
    return EligibleQuotationPool(specificity=winning_specificity, candidates=candidates)
