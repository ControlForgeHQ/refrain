from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from refrain.geometry import ResolvedOutputSpecification
from refrain.publication_metadata import (
    PublicationMetadataError,
    finalize_publication_metadata,
    parse_publication_metadata,
    serialize_publication_metadata,
    validate_publication_metadata,
)

OUTPUT = ResolvedOutputSpecification("16:9", (1920, 1080))
TIME = datetime(2026, 11, 18, tzinfo=timezone.utc)


@pytest.fixture
def checkpoint():
    return {
        "schema_version": 1,
        "content": {
            "display_date": "2026-11-18",
            "selection_revision": 5,
            "reveal_schedule": {"quotation": "06:00", "source": "12:00", "attribution": "06:00"},
            "reveal_stage": {"quotation": True, "source": False, "attribution": True},
            "quotation": " 雪\ncafé ",
            "source": " Source ",
            "attribution": "Poet",
            "actions": [
                {"type": "x", "visibility": ["external"], "payload": "public"},
                {"type": "y", "visibility": ["internal"], "payload": "private"},
                {"type": "z", "visibility": ["internal", "external"], "payload": "both"},
                {"type": "x", "visibility": ["external"], "payload": "public"},
            ],
            "qr": [
                {"payload": "外", "visibility": ["external"]},
                {"payload": "內", "visibility": ["internal"]},
            ],
        },
        "presentation": {
            "style": "centered",
            "background": "paper",
            "decoration": "none",
            "fonts": {"bundle": "lora", "faces": {"quotation": "regular", "source": "italic", "attribution": "bold"}},
            "colors": {"text": "black", "decoration": None},
            "font_size_range": {"minimum": 56, "maximum": 200},
            "insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
        },
    }


def scheduled(checkpoint, *, audience="external", rendered_qr=True):
    return finalize_publication_metadata(
        checkpoint,
        publication_type="scheduled",
        publication_id="event-1",
        published_at=TIME,
        destination_id="dest",
        output_specification=OUTPUT,
        audience=audience,
        selection_revision=5,
        visibility={"quotation": True, "source": True, "attribution": True},
        effective_presentation={**checkpoint["presentation"], "background": "none"},
        rendered_qr=(
            next(q for q in checkpoint["content"]["qr"] if audience in q["visibility"]) if rendered_qr else None
        ),
        prepared_output_specification={"aspect_ratio": "16:9", "requested_output_size": [1920, 1080]},
    )


def transient():
    return finalize_publication_metadata(
        publication_type="transient",
        publication_id="push",
        published_at=TIME,
        destination_id="dest",
        output_specification=OUTPUT,
    )


def test_four_forms_round_trip_and_exact_shapes(checkpoint):
    content = {key: copy.deepcopy(value) for key, value in checkpoint.items() if key != "presentation"}
    documents = [
        ("content", content, {"schema_version", "content"}),
        ("presentation", checkpoint, {"schema_version", "content", "presentation"}),
        ("scheduled", scheduled(checkpoint), {"schema_version", "content", "presentation", "publication"}),
        ("transient", transient(), {"schema_version", "publication"}),
    ]
    for stage, document, keys in documents:
        assert set(document) == keys
        audience = "external" if stage == "scheduled" else None
        encoded = serialize_publication_metadata(document, stage=stage, audience=audience)
        assert parse_publication_metadata(encoded.encode(), stage=stage, audience=audience) == document
        assert encoded == json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        for wrong_stage, _, _ in documents:
            if wrong_stage != stage:
                with pytest.raises(PublicationMetadataError):
                    validate_publication_metadata(document, stage=wrong_stage)
    validate_publication_metadata(content, stage="checkpoint")
    validate_publication_metadata(checkpoint, stage="checkpoint")
    validate_publication_metadata(documents[2][1], stage="completed")
    validate_publication_metadata(documents[3][1], stage="completed")


def test_independent_finalization_filters_actions_and_copies_associations(checkpoint):
    original = copy.deepcopy(checkpoint)
    external = scheduled(checkpoint)
    internal = scheduled(checkpoint, audience="internal")
    assert [action["type"] for action in external["content"]["actions"]] == ["x", "z", "x"]
    assert [action["type"] for action in internal["content"]["actions"]] == ["y", "z"]
    assert external["content"]["actions"][1]["visibility"] == ["internal", "external"]
    assert external["content"]["qr"] == [original["content"]["qr"][0]]
    assert internal["content"]["qr"] == [original["content"]["qr"][1]]
    assert scheduled(checkpoint, rendered_qr=False)["content"]["qr"] == []
    assert external["content"]["reveal_stage"]["source"] is True
    assert external["presentation"]["background"] == "none"
    external["content"]["actions"][0]["payload"] = "changed"
    assert checkpoint == original
    assert internal["content"]["actions"][0]["payload"] == "private"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(schema_version=True),
        lambda d: d.update(audience="external"),
        lambda d: d["content"].update(display_date="2026-02-29"),
        lambda d: d["content"].update(selection_revision=True),
        lambda d: d["content"]["reveal_schedule"].update(source="05:59"),
        lambda d: d["content"]["reveal_stage"].update(quotation=False),
        lambda d: d["content"].update(quotation="  "),
        lambda d: d["content"].update(source=None),
        lambda d: (d["content"].pop("attribution"), d["content"]["reveal_stage"].update(attribution=True)),
        lambda d: d["content"]["actions"][0].update(visibility=["external", "external"]),
        lambda d: d["content"]["actions"][0].update(type="../path"),
        lambda d: d["content"]["actions"][0].update(payload="a" * 10_241),
        lambda d: d["content"]["qr"].append(copy.deepcopy(d["content"]["qr"][0])),
        lambda d: d["content"]["qr"][0].update(payload="é" * 32),
        lambda d: d["presentation"].update(style="justified"),
        lambda d: d["presentation"]["fonts"]["faces"].pop("source"),
        lambda d: d["presentation"]["colors"].update(text="#000000"),
        lambda d: d["presentation"]["font_size_range"].update(minimum=True),
        lambda d: d["presentation"]["insets"].update(left=-1),
    ],
)
def test_invalid_checkpoint_fields_rejected(checkpoint, mutation):
    mutation(checkpoint)
    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(checkpoint, stage="presentation")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["publication"].update(type="transient"),
        lambda d: d["publication"].update(id=" "),
        lambda d: d["publication"].update(timestamp="2026-11-18T00:00:00+00:00"),
        lambda d: d["publication"].update(timestamp="2026-02-29T00:00:00Z"),
        lambda d: d["publication"].update(destination_id="a" * 257),
        lambda d: d["publication"]["output_specification"].update(aspect_ratio="1:1"),
        lambda d: d["publication"]["output_specification"].update(requested_output_size=[True, 1]),
        lambda d: d["publication"]["output_specification"].update(requested_output_size=[3841, 1]),
        lambda d: d["content"]["actions"].append({"type": "z", "visibility": ["internal"], "payload": ""}),
        lambda d: d["content"]["qr"][0].update(visibility=["internal"]),
    ],
)
def test_invalid_completed_fields_rejected(checkpoint, mutation):
    document = scheduled(checkpoint)
    mutation(document)
    with pytest.raises(PublicationMetadataError):
        validate_publication_metadata(document, stage="scheduled", audience="external")


def test_scheduled_serialization_requires_audience_but_context_free_validation_does_not(checkpoint):
    document = scheduled(checkpoint)
    validate_publication_metadata(document, stage="completed")
    assert parse_publication_metadata(json.dumps(document), stage="completed") == document
    with pytest.raises(PublicationMetadataError, match="audience"):
        serialize_publication_metadata(document, stage="completed")
    with pytest.raises(PublicationMetadataError):
        serialize_publication_metadata(document, stage="completed", audience="internal")


def test_publication_limits_are_applied_after_audience_filtering(checkpoint):
    checkpoint["content"]["actions"] = [{"type": "x", "visibility": ["internal"], "payload": "é" * 3000}] * 30 + [
        {"type": "x", "visibility": ["external"], "payload": "ok"}
    ]
    assert len(scheduled(checkpoint)["content"]["actions"]) == 1
    with pytest.raises(PublicationMetadataError):
        scheduled(checkpoint, audience="internal")
    checkpoint["content"]["actions"] = [{"type": "x", "visibility": ["external"], "payload": "é" * 2040}]
    with pytest.raises(PublicationMetadataError, match="serialized action"):
        scheduled(checkpoint)
    checkpoint["content"]["actions"] = []
    checkpoint["content"]["quotation"] = "雪" * 22_000
    validate_publication_metadata(checkpoint, stage="presentation")
    with pytest.raises(PublicationMetadataError, match="65536"):
        scheduled(checkpoint)


def test_finalization_rejects_mismatched_associations(checkpoint):
    arguments = dict(
        publication_type="scheduled",
        publication_id="event",
        published_at=TIME,
        destination_id="dest",
        output_specification=OUTPUT,
        audience="external",
        selection_revision=5,
        visibility=checkpoint["content"]["reveal_stage"],
        effective_presentation=checkpoint["presentation"],
        rendered_qr=checkpoint["content"]["qr"][0],
        prepared_output_specification=OUTPUT,
    )
    for replacement in [
        {"selection_revision": 6},
        {"prepared_output_specification": ResolvedOutputSpecification("4:3", (1600, 1200))},
        {"rendered_qr": checkpoint["content"]["qr"][1]},
        {"rendered_qr": {"payload": "different", "visibility": ["external"]}},
        {"visibility": {"quotation": False, "source": False, "attribution": False}},
        {"effective_presentation": None},
    ]:
        with pytest.raises(PublicationMetadataError):
            finalize_publication_metadata(checkpoint, **(arguments | replacement))


@pytest.mark.parametrize(
    "contents",
    [
        b"\xff",
        '{"schema_version":1,"schema_version":1}',
        '{"schema_version":1,"content":{"a":1,"a":2}}',
        '{"schema_version":NaN}',
        '{"schema_version":Infinity}',
        '{"schema_version":1,"content":{"quotation":"\\ud800"}}',
        "[" * 2000 + "]" * 2000,
    ],
)
def test_parser_rejects_invalid_json_and_unicode(contents):
    with pytest.raises(PublicationMetadataError):
        parse_publication_metadata(contents, stage="checkpoint")
