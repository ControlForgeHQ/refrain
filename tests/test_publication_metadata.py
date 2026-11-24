from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from refrain.content import load_content_library
from refrain.geometry import ResolvedOutputSpecification
from refrain.publication_metadata import (
    PUBLICATION_METADATA_VERSION,
    PublicationMetadataError,
    finalize_publication_metadata,
    parse_publication_metadata,
    serialize_publication_metadata,
    validate_publication_metadata,
)

_OUTPUT = ResolvedOutputSpecification("16:9", (1920, 1080))


def _document():
    return {
        "schema_version": PUBLICATION_METADATA_VERSION,
        "content": {
            "display_date": "2026-10-26",
            "selection_revision": 4,
            "reveal_schedule": {"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
            "reveal_stage": {"quotation": True, "source": False, "attribution": False},
            "quotation": "A thought worth keeping.",
            "actions": [],
            "qr": [],
        },
        "presentation": {
            "style": "centered",
            "background": "none",
            "decoration": "none",
            "fonts": {
                "bundle": "lora",
                "faces": {"quotation": "regular", "source": "regular", "attribution": "regular"},
            },
            "colors": {"text": "black", "decoration": None},
            "font_size_range": {"minimum": 12, "maximum": 32},
            "insets": {"left": 384, "right": 384, "top": 216, "bottom": 216},
        },
    }


def _finalized(document=None, *, audience="external", destination_id="default", publication_id="publication-1"):
    checkpoint = _document() if document is None else document
    return finalize_publication_metadata(
        checkpoint,
        publication_type="scheduled",
        publication_id=publication_id,
        published_at=datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc),
        destination_id=destination_id,
        output_specification=_OUTPUT,
        audience=audience,
        selection_revision=checkpoint["content"]["selection_revision"],
        visibility=checkpoint["content"]["reveal_stage"],
        effective_presentation=checkpoint["presentation"],
        prepared_output_specification=_OUTPUT,
    )


def test_checkpoint_forms_omit_publication_fields() -> None:
    document = _document()
    content = {key: copy.deepcopy(value) for key, value in document.items() if key != "presentation"}
    validate_publication_metadata(content, stage="content")
    validate_publication_metadata(document, stage="presentation")
    assert set(content) == {"schema_version", "content"}
    assert set(document) == {"schema_version", "content", "presentation"}
    assert document["content"]["actions"] == []
    assert document["content"]["reveal_schedule"] == {
        "quotation": "06:00",
        "source": "12:00",
        "attribution": "18:00",
    }


def test_content_entry_is_accepted_by_authoritative_content_loader(tmp_path) -> None:
    entry = {
        "id": "entry",
        "quotations": ["A thought worth keeping."],
        "presentation_style": "centered",
        "reveal": {"source": "12:00", "attribution": "18:00"},
    }
    (tmp_path / "entry.yaml").write_text(yaml.safe_dump(entry), encoding="utf-8")
    (loaded,) = load_content_library(tmp_path)
    assert loaded.id == "entry"
    assert len(loaded.quotations) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("content"),
        lambda value: value.update(publication={}),
        lambda value: value.update(schema_version=99),
        lambda value: value["content"].update(selection_revision=None),
        lambda value: value["presentation"]["fonts"]["faces"].pop("source"),
        lambda value: value["presentation"]["colors"].update(text=None),
        lambda value: value["content"].update(eligibility=[{"bogus": True}]),
        lambda value: value["content"]["reveal_schedule"].update(quotation="invalid"),
        lambda value: value["presentation"].update(background="/absolute/path"),
        lambda value: value["presentation"]["colors"].update(text="#FFFFFF"),
    ],
)
def test_checkpoint_validation_rejects_missing_or_inappropriate_values(mutation) -> None:
    document = _document()
    mutation(document)
    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="presentation")


def test_completed_validation_requires_publication_owned_fields() -> None:
    document = _document()
    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="completed")
    validate_publication_metadata(_finalized(document), stage="completed")


def test_scheduled_finalization_preserves_content_and_effective_presentation() -> None:
    checkpoint = _document()
    checkpoint["content"].update(source="A source", attribution="A poet")
    checkpoint["presentation"].update(background="aged-paper", decoration="simple-border")
    checkpoint["presentation"]["fonts"]["faces"].update(source="italic", attribution="italic")
    checkpoint["presentation"]["colors"] = {"text": "slate", "decoration": "sage"}
    original = copy.deepcopy(checkpoint)
    completed = _finalized(checkpoint)
    assert completed["publication"] == {
        "id": "publication-1",
        "type": "scheduled",
        "timestamp": "2026-10-26T06:00:00Z",
        "destination_id": "default",
        "output_specification": {"aspect_ratio": "16:9", "requested_output_size": [1920, 1080]},
    }
    assert completed["content"] == original["content"]
    assert completed["presentation"] == original["presentation"]
    assert checkpoint == original


def test_scheduled_finalization_uses_image_visibility_and_effective_presentation() -> None:
    checkpoint = _document()
    checkpoint["content"]["source"] = "A source"
    presentation = copy.deepcopy(checkpoint["presentation"])
    presentation["background"] = "paper"
    visibility = {"quotation": True, "source": True, "attribution": False}
    original = copy.deepcopy(checkpoint)
    completed = finalize_publication_metadata(
        checkpoint,
        publication_type="scheduled",
        publication_id="publication-1",
        published_at="2026-10-26T06:00:00Z",
        destination_id="default",
        output_specification=_OUTPUT,
        audience="external",
        selection_revision=4,
        visibility=visibility,
        effective_presentation=presentation,
        prepared_output_specification=_OUTPUT,
    )
    assert completed["content"]["reveal_stage"] == visibility
    assert completed["presentation"] == presentation
    assert checkpoint == original


def test_publication_identifier_is_distinct_from_selection_identity_and_reveal_stage() -> None:
    first = _finalized(publication_id="publication-1")
    second = _finalized(publication_id="publication-2")
    assert first["publication"]["id"] != second["publication"]["id"]
    assert first["content"] == second["content"]


def test_publication_timestamp_requires_timezone_and_normalizes_to_utc() -> None:
    arguments = {
        "publication_type": "transient",
        "publication_id": "publication-1",
        "destination_id": "default",
        "output_specification": _OUTPUT,
    }
    completed = finalize_publication_metadata(published_at="2026-10-26T08:00:00-02:00", **arguments)
    assert completed["publication"]["timestamp"] == "2026-10-26T10:00:00Z"
    with pytest.raises(PublicationMetadataError):
        finalize_publication_metadata(published_at="2026-10-26T08:00:00", **arguments)


def test_actions_are_filtered_by_audience_without_reordering_or_deduplication() -> None:
    checkpoint = _document()
    checkpoint["content"]["actions"] = [
        {"type": "external", "visibility": ["external"], "payload": "1"},
        {"type": "internal", "visibility": ["internal"], "payload": "2"},
        {"type": "both", "visibility": ["external", "internal"], "payload": "3"},
        {"type": "external", "visibility": ["external"], "payload": "1"},
    ]
    validate_publication_metadata(checkpoint, stage="presentation")
    original = copy.deepcopy(checkpoint)
    external = _finalized(checkpoint)
    internal = _finalized(checkpoint, audience="internal", destination_id="internal-display")
    assert [action["type"] for action in external["content"]["actions"]] == ["external", "both", "external"]
    assert [action["type"] for action in internal["content"]["actions"]] == ["internal", "both"]
    assert external["content"]["actions"][0] == external["content"]["actions"][2]
    assert external["content"]["actions"][1]["visibility"] == ["external", "internal"]
    assert external["publication"]["destination_id"] != internal["publication"]["destination_id"]
    assert checkpoint == original
    external["content"]["actions"].append(checkpoint["content"]["actions"][1])
    with pytest.raises(PublicationMetadataError, match="not visible to the external"):
        validate_publication_metadata(external, stage="completed", audience="external")
    with pytest.raises(PublicationMetadataError, match="not visible to the external"):
        serialize_publication_metadata(external, stage="completed", audience="external")


def test_checkpoint_rejects_legacy_reconstruction_with_unfiltered_actions() -> None:
    checkpoint = _document()
    checkpoint["reconstruction"] = {
        "content_entry": {"actions": [{"type": "internal", "visibility": ["internal"], "payload": "secret"}]}
    }
    with pytest.raises(PublicationMetadataError):
        _finalized(checkpoint)


@pytest.mark.parametrize("origin", ["image", "viewer-preview", "information-view"])
def test_transient_publication_uses_minimal_metadata_without_checkpoint(origin) -> None:
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
        "publication": {
            "id": "transient-1",
            "type": "transient",
            "timestamp": "2026-10-25T22:00:00Z",
            "destination_id": "default",
            "output_specification": {"aspect_ratio": "16:9", "requested_output_size": [1920, 1080]},
        },
    }
    serialize_publication_metadata(document, stage="completed")


@pytest.mark.parametrize("field", ["content", "presentation", "actions"])
def test_transient_validation_rejects_scheduled_payload(field) -> None:
    document = finalize_publication_metadata(
        publication_type="transient",
        publication_id="transient-1",
        published_at="2026-10-26T06:00:00Z",
        destination_id="default",
        output_specification=_OUTPUT,
    )
    document[field] = {}
    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="transient")


def test_finalization_rejects_checkpoint_for_completed_serialization_and_mismatched_images() -> None:
    checkpoint = _document()
    with pytest.raises(PublicationMetadataError):
        serialize_publication_metadata(checkpoint, stage="completed")
    with pytest.raises(PublicationMetadataError, match="does not match"):
        finalize_publication_metadata(
            checkpoint,
            publication_type="scheduled",
            publication_id="publication-1",
            published_at="2026-10-26T06:00:00Z",
            destination_id="default",
            output_specification=ResolvedOutputSpecification("4:3", (1600, 1200)),
            audience="external",
            selection_revision=4,
            visibility=checkpoint["content"]["reveal_stage"],
            effective_presentation=checkpoint["presentation"],
            prepared_output_specification=_OUTPUT,
        )


def test_scheduled_serialization_requires_audience_and_metadata_never_contains_it() -> None:
    completed = _finalized()
    assert "audience" not in completed
    assert "audience" not in completed["content"]
    with pytest.raises(PublicationMetadataError, match="requires a destination audience"):
        serialize_publication_metadata(completed, stage="completed")
    for location in (completed, completed["content"]):
        document = copy.deepcopy(completed)
        target = document if location is completed else document["content"]
        target["audience"] = "external"
        with pytest.raises(PublicationMetadataError):
            validate_publication_metadata(document, stage="completed", audience="external")


@pytest.mark.parametrize("publication_id", ["", " ", "\t\n"])
def test_completed_publication_id_must_be_nonblank_everywhere(publication_id: str) -> None:
    with pytest.raises(PublicationMetadataError, match="publication.id"):
        _finalized(publication_id=publication_id)
    document = _finalized()
    document["publication"]["id"] = publication_id
    with pytest.raises(PublicationMetadataError, match="publication.id"):
        validate_publication_metadata(document, stage="completed")
    with pytest.raises(PublicationMetadataError, match="publication.id"):
        parse_publication_metadata(json.dumps(document), stage="completed", audience="external")
    with pytest.raises(PublicationMetadataError, match="publication.id"):
        serialize_publication_metadata(document, stage="completed", audience="external")


def test_unicode_metadata_round_trips_as_deterministic_json() -> None:
    checkpoint = _document()
    checkpoint["content"]["quotation"] = "雪と café — “thought”"
    checkpoint["content"]["actions"] = [{"type": "note", "visibility": ["external"], "payload": "こんにちは 🌿"}]
    completed = _finalized(checkpoint)
    encoded = serialize_publication_metadata(completed, stage="completed", audience="external")
    parsed = parse_publication_metadata(encoded.encode("utf-8"), stage="completed", audience="external")
    assert "こんにちは 🌿" in encoded
    assert parsed == completed
    assert serialize_publication_metadata(parsed, stage="completed", audience="external") == encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version=99),
        lambda value: value["publication"].pop("destination_id"),
        lambda value: value["publication"].update(id=None),
        lambda value: value.update(audience="external"),
        lambda value: value["publication"].update(timestamp="2026-10-26T06:00:00"),
        lambda value: value["content"].update(quotation=None),
        lambda value: value["content"].update(reveal_schedule={"quotation": None}),
        lambda value: value["publication"]["output_specification"].update(requested_output_size=[True, 1080]),
        lambda value: value["content"].update(quotation=["one", "two"]),
    ],
)
def test_completed_validation_rejects_unsupported_or_malformed_documents(mutation) -> None:
    document = _finalized()
    mutation(document)
    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="completed")


def test_parser_rejects_duplicate_fields_and_invalid_json_values() -> None:
    with pytest.raises(PublicationMetadataError, match="duplicate JSON field"):
        parse_publication_metadata('{"schema_version": 1, "schema_version": 1}', stage="checkpoint")
    with pytest.raises(PublicationMetadataError, match="invalid JSON number"):
        parse_publication_metadata('{"value": NaN}', stage="checkpoint")


def test_parser_rejects_invalid_unicode_strings() -> None:
    document = _finalized()
    document["content"]["actions"] = [{"type": "note", "visibility": ["external"], "payload": "\ud800"}]
    with pytest.raises(PublicationMetadataError, match="Unicode"):
        parse_publication_metadata(json.dumps(document, ensure_ascii=True), stage="completed", audience="external")


def test_parser_rejects_json_bytes_encoded_outside_utf8() -> None:
    encoded = serialize_publication_metadata(_document(), stage="presentation")
    with pytest.raises(PublicationMetadataError, match="UTF-8"):
        parse_publication_metadata(encoded.encode("utf-16"), stage="presentation")
