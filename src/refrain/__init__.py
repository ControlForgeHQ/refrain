"""Hardware-independent Refrain components."""

from .config import (
    ApplicationConfiguration,
    ApplicationConfigurationError,
    ConfigurationDiagnostic,
    FontResource,
    QuotationRegion,
    RevealSchedule,
    load_application_config,
)
from .content import (
    ContentDiagnostic,
    ContentEntry,
    ContentLibraryError,
    EligibilityRule,
    Quotation,
    RevealOverrides,
    load_content_library,
    normalize_quotation,
)
from .eligibility import (
    EligibilitySpecificity,
    EligibleQuotationPool,
    QuotationCandidate,
    build_eligible_quotation_pool,
)
from .persistence import (
    DailySnapshot,
    GlobalHistoryRecord,
    PersistentState,
    PersistentStateError,
    PersistentStateStore,
    ResolvedFont,
    SchedulingContext,
    StateCommitError,
    StateRecoveryError,
    UnsupportedStateVersionError,
)
from .selection import SelectionProposal, select_quotation

__all__ = [
    "ApplicationConfiguration",
    "ApplicationConfigurationError",
    "ConfigurationDiagnostic",
    "ContentDiagnostic",
    "ContentEntry",
    "ContentLibraryError",
    "DailySnapshot",
    "EligibilityRule",
    "EligibilitySpecificity",
    "EligibleQuotationPool",
    "FontResource",
    "GlobalHistoryRecord",
    "QuotationRegion",
    "Quotation",
    "QuotationCandidate",
    "PersistentState",
    "PersistentStateError",
    "PersistentStateStore",
    "ResolvedFont",
    "SelectionProposal",
    "RevealSchedule",
    "RevealOverrides",
    "SchedulingContext",
    "StateCommitError",
    "StateRecoveryError",
    "UnsupportedStateVersionError",
    "load_content_library",
    "load_application_config",
    "normalize_quotation",
    "build_eligible_quotation_pool",
    "select_quotation",
]
