from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import yaml

from refrain.content import load_content_library
from refrain.geometry import ResolvedOutputSpecification
from refrain.publication_metadata import (
    PUBLICATION_METADATA_VERSION,
    PublicationMetadataError,
    build_prepared_metadata,
    content_entry,
    finalize_publication_metadata,
    parse_publication_metadata,
    serialize_publication_metadata,
    validate_publication_metadata,
)
from refrain.renderer import CompositionVisibility

_OUTPUT = ResolvedOutputSpecification("16:9", (1920, 1080))


def _document():
    snapshot = SimpleNamespace(
        entry_id="entry",
        quotation_text="A thought worth keeping.",
        quotation_identity="A thought worth keeping.",
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
            "reveal": {"source": "12:00", "attribution": "18:00"},
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
        output_specification=_OUTPUT,
        stage_index=0,
        visibility=CompositionVisibility(),
        reconstruction=reconstruction,
    )


def _finalized(document=None, *, audience="external", destination_id="default", publication_id="publication-1"):
    prepared = _document() if document is None else document
    return finalize_publication_metadata(
        prepared,
        publication_type="scheduled",
        publication_id=publication_id,
        published_at=datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc),
        destination_id=destination_id,
        output_specification=_OUTPUT,
        audience=audience,
        reveal_stage_index=prepared["presentation"]["reveal_stage_index"],
    )


def test_preparation_metadata_uses_explicit_nulls_for_publication_fields() -> None:
    document = _document()

    validate_publication_metadata(document, stage="preparation")

    assert document["schema_version"] == PUBLICATION_METADATA_VERSION
    assert document["publication_id"] is None
    assert document["published_at"] is None
    assert document["destination_id"] is None
    assert document["actions"] == []
    assert "quotation" not in document["reconstruction"]["content_entry"]["reveal"]
    assert document["presentation"]["quotation_identity"] == "A thought worth keeping."
    assert document["presentation"]["reveal_schedule"] == {
        "quotation": "06:00",
        "source": "12:00",
        "attribution": "18:00",
    }


def test_generated_content_entry_is_accepted_by_authoritative_content_loader(tmp_path) -> None:
    entry = _document()["reconstruction"]["content_entry"]
    content_file = tmp_path / "entry.yaml"
    content_file.write_text(yaml.safe_dump(entry), encoding="utf-8")

    (loaded,) = load_content_library(tmp_path)

    assert loaded.id == "entry"
    assert len(loaded.quotations) == 1


def test_generated_content_entry_preserves_only_stable_resource_and_palette_references() -> None:
    snapshot = SimpleNamespace(
        entry_id="entry",
        quotation_text="A thought worth keeping.",
        presentation_style="centered",
        reveal_schedule={"source": "12:00", "attribution": "18:00"},
        source=None,
        attribution=None,
        font="@literary",
        background="/internal/assets/paper.png",
        decoration="none",
        font_faces={"quotation": "regular"},
        text_color=("#FFFFFF",),
        decoration_color=("sage",),
    )

    entry = content_entry(snapshot)

    assert entry["font"] == "@literary"
    assert entry["decoration"] == "none"
    assert entry["decoration_color"] == ["sage"]
    assert "background" not in entry
    assert "text_color" not in entry


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
        lambda value: value["reconstruction"]["content_entry"].update(eligibility=[{"bogus": True}]),
        lambda value: value["reconstruction"]["content_entry"].update(eligibility=[{"year": True}]),
        lambda value: value["reconstruction"]["content_entry"].update(reveal={"quotation": "06:00"}),
        lambda value: value["reconstruction"]["content_entry"].update(background="/absolute/path"),
        lambda value: value["reconstruction"]["content_entry"].update(text_color=["#FFFFFF"]),
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


def test_scheduled_finalization_preserves_identity_stage_and_complete_reconstruction() -> None:
    prepared = _document()
    prepared["reconstruction"]["content_entry"].update(
        source="A source",
        attribution="A poet",
        font="lora",
        background="aged-paper",
        decoration="simple-border",
        font_faces={"quotation": "regular", "source": "italic", "attribution": "italic"},
    )
    prepared["reconstruction"]["background"] = "aged-paper"
    prepared["reconstruction"]["decoration"] = "simple-border"
    prepared["reconstruction"]["fonts"]["faces"] = {
        "quotation": "regular",
        "source": "italic",
        "attribution": "italic",
    }
    prepared["reconstruction"]["colors"] = {"text": "slate", "decoration": "sage"}
    original = copy.deepcopy(prepared)

    completed = _finalized(prepared)

    assert completed["publication_id"] == "publication-1"
    assert completed["publication_type"] == "scheduled"
    assert completed["published_at"] == "2026-10-26T06:00:00Z"
    assert completed["destination_id"] == "default"
    assert completed["output_specification"] == {
        "aspect_ratio": "16:9",
        "requested_output_size": [1920, 1080],
    }
    assert completed["presentation"] == original["presentation"]
    assert completed["reconstruction"] == original["reconstruction"]
    assert completed["reconstruction"]["content_entry"]["quotations"] == ["A thought worth keeping."]
    assert completed["reconstruction"]["fonts"]["faces"]["source"] == "italic"
    assert completed["reconstruction"]["colors"] == {"text": "slate", "decoration": "sage"}
    assert prepared == original


def test_publication_identifier_is_distinct_from_selection_identity_and_reveal_stage() -> None:
    first = _finalized(_document(), publication_id="publication-1")
    second = _finalized(_document(), publication_id="publication-2")

    assert first["publication_id"] != second["publication_id"]
    assert first["presentation"]["quotation_identity"] == second["presentation"]["quotation_identity"]
    assert first["presentation"]["selection_revision"] == second["presentation"]["selection_revision"]
    assert first["presentation"]["reveal_stage_index"] == second["presentation"]["reveal_stage_index"]


def test_publication_timestamp_requires_timezone_and_normalizes_to_utc() -> None:
    document = _document()
    completed = finalize_publication_metadata(
        document,
        publication_type="scheduled",
        publication_id="publication-1",
        published_at="2026-10-26T08:00:00-02:00",
        destination_id="default",
        output_specification=_OUTPUT,
        audience="external",
        reveal_stage_index=0,
    )

    assert completed["published_at"] == "2026-10-26T10:00:00Z"
    with pytest.raises(PublicationMetadataError, match="timezone-aware"):
        finalize_publication_metadata(
            document,
            publication_type="scheduled",
            publication_id="publication-1",
            published_at="2026-10-26T08:00:00",
            destination_id="default",
            output_specification=_OUTPUT,
            audience="external",
            reveal_stage_index=0,
        )


def test_actions_are_filtered_by_audience_without_reordering_or_deduplication() -> None:
    prepared = _document()
    prepared["actions"] = [
        {"type": "external", "visibility": ["external"], "payload": "1"},
        {"type": "internal", "visibility": ["internal"], "payload": "2"},
        {"type": "both", "visibility": ["external", "internal"], "payload": "3"},
        {"type": "external", "visibility": ["external"], "payload": "1"},
    ]
    validate_publication_metadata(prepared, stage="preparation")

    external = _finalized(prepared)
    internal = _finalized(prepared, audience="internal", destination_id="internal-display")

    assert [action["type"] for action in external["actions"]] == ["external", "both", "external"]
    assert [action["type"] for action in internal["actions"]] == ["internal", "both"]
    assert external["actions"][0] == external["actions"][2]
    assert external["actions"][1]["visibility"] == ["external", "internal"]
    assert internal["actions"][1]["visibility"] == ["external", "internal"]
    with pytest.raises(PublicationMetadataError, match="not visible to the external"):
        validate_publication_metadata(
            {**external, "actions": [prepared["actions"][1]]},
            stage="completed",
            audience="external",
        )
    with pytest.raises(PublicationMetadataError, match="not visible to the external"):
        serialize_publication_metadata(
            {**external, "actions": [prepared["actions"][1]]},
            stage="completed",
            audience="external",
        )


def test_reconstruction_content_cannot_leak_unfiltered_actions() -> None:
    prepared = _document()
    prepared["reconstruction"]["content_entry"]["actions"] = [
        {"type": "internal", "visibility": ["internal"], "payload": "secret"}
    ]

    with pytest.raises(PublicationMetadataError):
        _finalized(prepared)


def test_destinations_finalize_independently_without_mutating_shared_preparation() -> None:
    prepared = _document()
    prepared["actions"] = [
        {"type": "external", "visibility": ["external"], "payload": ""},
        {"type": "internal", "visibility": ["internal"], "payload": ""},
    ]
    original = copy.deepcopy(prepared)
    left = _finalized(prepared, destination_id="external-display")
    right = _finalized(prepared, audience="internal", destination_id="internal-display")

    assert left["destination_id"] != right["destination_id"]
    assert [action["type"] for action in left["actions"]] == ["external"]
    assert [action["type"] for action in right["actions"]] == ["internal"]
    assert prepared == original


@pytest.mark.parametrize("origin", ["image", "viewer-preview", "information-view"])
def test_transient_publication_uses_minimal_metadata_without_preparation(origin) -> None:
    del origin
    document = finalize_publication_metadata(
        publication_type="transient",
        publication_id="transient-1",
        published_at=datetime(2026, 10, 26, tzinfo=timezone(timedelta(hours=2))),
        destination_id="default",
        output_specification=_OUTPUT,
    )

    assert document == {
        "schema_version": PUBLICATION_METADATA_VERSION,
        "publication_id": "transient-1",
        "publication_type": "transient",
        "published_at": "2026-10-25T22:00:00Z",
        "destination_id": "default",
        "output_specification": {"aspect_ratio": "16:9", "requested_output_size": [1920, 1080]},
        "presentation": None,
        "reconstruction": None,
        "actions": [],
    }
    assert "audience" not in document
    serialize_publication_metadata(document, stage="completed")


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(presentation={"display_date": "2026-10-26"}),
        lambda value: value.update(reconstruction={}),
        lambda value: value.update(actions=[{"type": "internal", "visibility": ["internal"], "payload": ""}]),
    ],
)
def test_transient_validation_rejects_scheduled_payload(change) -> None:
    document = finalize_publication_metadata(
        None,
        publication_type="transient",
        publication_id="transient-1",
        published_at="2026-10-26T06:00:00Z",
        destination_id="default",
        output_specification=_OUTPUT,
    )
    change(document)

    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="completed")


def test_finalization_rejects_prepared_metadata_for_completed_serialization_and_mismatched_images() -> None:
    with pytest.raises(PublicationMetadataError):
        serialize_publication_metadata(_document(), stage="completed")
    with pytest.raises(PublicationMetadataError, match="does not match"):
        finalize_publication_metadata(
            _document(),
            publication_type="scheduled",
            publication_id="publication-1",
            published_at="2026-10-26T06:00:00Z",
            destination_id="default",
            output_specification=ResolvedOutputSpecification("4:3", (1600, 1200)),
            audience="external",
            reveal_stage_index=0,
        )


def test_scheduled_serialization_requires_audience_and_metadata_never_contains_it() -> None:
    completed = _finalized()

    assert "audience" not in _document()
    assert "audience" not in completed
    assert "audience" not in completed["reconstruction"]["content_entry"]
    with pytest.raises(PublicationMetadataError, match="requires a destination audience"):
        serialize_publication_metadata(completed, stage="completed")
    for location in ("top-level", "reconstruction"):
        document = copy.deepcopy(completed)
        if location == "top-level":
            document["audience"] = "external"
        else:
            document["reconstruction"]["content_entry"]["audience"] = "external"
        with pytest.raises(PublicationMetadataError):
            validate_publication_metadata(document, stage="completed", audience="external")


@pytest.mark.parametrize("publication_id", ["", " ", "\t\n"])
def test_completed_publication_id_must_be_nonblank_everywhere(publication_id: str) -> None:
    with pytest.raises(PublicationMetadataError, match="publication_id"):
        _finalized(publication_id=publication_id)
    document = _finalized()
    document["publication_id"] = publication_id

    with pytest.raises(PublicationMetadataError, match="publication_id"):
        validate_publication_metadata(document, stage="completed")
    with pytest.raises(PublicationMetadataError, match="publication_id"):
        parse_publication_metadata(json.dumps(document), stage="completed", audience="external")
    with pytest.raises(PublicationMetadataError, match="publication_id"):
        serialize_publication_metadata(document, stage="completed", audience="external")


def test_unicode_metadata_round_trips_as_deterministic_json() -> None:
    prepared = _document()
    prepared["reconstruction"]["content_entry"]["quotations"] = ["雪と café — “thought”"]
    prepared["presentation"]["quotation_identity"] = "雪と café — “thought”"
    prepared["actions"] = [{"type": "note", "visibility": ["external"], "payload": "こんにちは 🌿"}]
    completed = _finalized(prepared)

    encoded = serialize_publication_metadata(completed, stage="completed", audience="external")
    parsed = parse_publication_metadata(encoded.encode("utf-8"), stage="completed", audience="external")

    assert "こんにちは 🌿" in encoded
    assert parsed == completed
    assert serialize_publication_metadata(parsed, stage="completed", audience="external") == encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version=99),
        lambda value: value.pop("destination_id"),
        lambda value: value.update(publication_id=None),
        lambda value: value.update(audience="external"),
        lambda value: value.update(published_at="2026-10-26T06:00:00"),
        lambda value: value["presentation"].update(quotation_identity=None),
        lambda value: value["presentation"].update(reveal_schedule={"quotation": None}),
        lambda value: value["output_specification"].update(requested_output_size=[True, 1080]),
        lambda value: value["reconstruction"]["content_entry"].update(quotations=["one", "two"]),
    ],
)
def test_completed_validation_rejects_unsupported_or_malformed_documents(mutation) -> None:
    document = _finalized()
    mutation(document)

    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="completed")


def test_parser_rejects_duplicate_fields_and_invalid_json_values() -> None:
    with pytest.raises(PublicationMetadataError, match="duplicate JSON field"):
        parse_publication_metadata('{"schema_version": 1, "schema_version": 1}', stage="preparation")
    with pytest.raises(PublicationMetadataError, match="invalid JSON number"):
        parse_publication_metadata('{"value": NaN}', stage="preparation")


def test_parser_rejects_invalid_unicode_strings() -> None:
    document = _finalized()
    document["actions"] = [{"type": "note", "visibility": ["external"], "payload": "\ud800"}]

    with pytest.raises(PublicationMetadataError, match="valid Unicode"):
        parse_publication_metadata(json.dumps(document, ensure_ascii=True), stage="completed", audience="external")


def test_parser_rejects_json_bytes_encoded_outside_utf8() -> None:
    encoded = serialize_publication_metadata(_document(), stage="preparation")

    with pytest.raises(PublicationMetadataError, match="must be UTF-8"):
        parse_publication_metadata(encoded.encode("utf-16"), stage="preparation")
