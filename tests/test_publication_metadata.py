from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from refrain.geometry import ResolvedOutputSpecification
from refrain.publication_metadata import (
    PUBLICATION_METADATA_VERSION,
    PublicationMetadataError,
    build_prepared_metadata,
    validate_publication_metadata,
)
from refrain.renderer import CompositionVisibility


def _document():
    snapshot = SimpleNamespace(
        entry_id="entry",
        quotation_text="A thought worth keeping.",
        source=None,
        attribution=None,
        font=None,
        background=None,
        decoration=None,
        font_faces={},
        text_color=None,
        decoration_color=None,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        display_date=date(2026, 10, 26),
        actions=(),
        presentation_style="centered",
    )
    reconstruction = {
        "content_entry": {
            "id": "entry",
            "quotations": ["A thought worth keeping."],
            "presentation_style": "centered",
            "reveal": {"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
            "eligibility": [{"ordinary": True}],
        },
        "presentation_style": "centered",
        "background": "none",
        "decoration": "none",
        "fonts": {
            "bundle": "lora",
            "faces": {"quotation": "regular", "source": "regular", "attribution": "regular"},
        },
        "colors": {"text": "black", "decoration": None},
        "qr": {"enabled": True, "available": False},
        "font_size_range": {"minimum": 12, "maximum": 32},
        "insets": {"left": 384, "right": 384, "top": 216, "bottom": 216},
    }
    return build_prepared_metadata(
        selection_revision=4,
        snapshot=snapshot,
        output_specification=ResolvedOutputSpecification("16:9", (1920, 1080)),
        stage_index=0,
        visibility=CompositionVisibility(),
        reconstruction=reconstruction,
    )


def test_preparation_metadata_uses_explicit_nulls_for_publication_fields() -> None:
    document = _document()

    validate_publication_metadata(document, stage="preparation")

    assert document["schema_version"] == PUBLICATION_METADATA_VERSION
    assert document["publication_id"] is None
    assert document["published_at"] is None
    assert document["destination_id"] is None
    assert document["actions"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("destination_id"),
        lambda value: value.update(publication_id="not-yet-published"),
        lambda value: value.update(published_at=""),
        lambda value: value.update(schema_version=99),
        lambda value: value["presentation"].update(selection_revision=None),
        lambda value: value["reconstruction"]["fonts"]["faces"].pop("source"),
        lambda value: value["reconstruction"]["colors"].update(text=None),
    ],
)
def test_preparation_validation_rejects_missing_or_inappropriate_values(mutation) -> None:
    document = _document()
    mutation(document)

    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="preparation")


def test_completed_validation_requires_publication_owned_fields() -> None:
    document = _document()

    with pytest.raises(PublicationMetadataError, match="publication_id"):
        validate_publication_metadata(document, stage="completed")

    document.update(
        publication_id="publication-1",
        published_at="2026-10-26T06:00:00Z",
        destination_id="default",
    )
    validate_publication_metadata(document, stage="completed")


def test_completed_transient_metadata_uses_the_same_schema_with_inapplicable_fields_null() -> None:
    document = _document()
    document.update(
        publication_id="publication-2",
        publication_type="transient",
        published_at="2026-10-26T06:00:00Z",
        destination_id="default",
        presentation=None,
        reconstruction=None,
        actions=[],
    )

    validate_publication_metadata(document, stage="completed")
