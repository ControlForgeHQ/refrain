from __future__ import annotations

from datetime import date, time
from pathlib import Path
from random import Random
from types import SimpleNamespace

import pytest
from PIL import Image

import refrain.viewer as viewer
from refrain.checkpoint import build_content_checkpoint
from refrain.config import ApplicationConfiguration, FontResource, RevealSchedule, StorageConfiguration
from refrain.content import ContentEntry, ContentQRDeclaration, Quotation, normalize_quotation
from refrain.display.coordinator import PublicationResult, PublicationStatus
from refrain.geometry import PresentationInsets, ResolvedOutputSpecification
from refrain.persistence import DailySnapshot, PersistentState, SchedulingContext
from refrain.preparation import PresentationOverrides, prepare_daily_images, resolve_canonical_presentation
from refrain.publication_metadata import finalize_publication_metadata, serialize_publication_metadata
from refrain.renderer import CompositionVisibility


@pytest.mark.parametrize(
    "arguments",
    [
        ["--no-qr", "--qr-external", "payload"],
        ["--no-qr", "--qr-internal", "none"],
        ["--audience", "external", "--render-as", "screen"],
        ["--audience", "internal", "--push", "@all"],
        ["--publication", "publication.json", "--qr-internal", "payload"],
        ["--publication", "publication.json", "--audience", "external"],
        ["--image", "image.png", "--no-qr"],
        ["--list-destinations", "--qr-external", "payload"],
        ["--qr-external", ""],
        ["--qr-internal", "é" * 32],
        ["--qr"],
    ],
)
def test_invalid_qr_options_and_modes_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as result:
        viewer.main(arguments)
    assert result.value.code == 2


def test_qr_resolution_obeys_per_audience_precedence() -> None:
    quotation = Quotation("Example", normalize_quotation("Example"))
    entry = ContentEntry(
        id="entry",
        quotations=(quotation,),
        qr=(ContentQRDeclaration(visibility=("internal",), payload=None),),
    )
    configuration = SimpleNamespace(qr_defaults={"external": "default", "internal": "private"})
    assert viewer._selected_qr(configuration, entry, "internal", None) is None
    assert viewer._selected_qr(configuration, entry, "external", None) == {
        "visibility": ["external"],
        "payload": "default",
    }
    assert viewer._selected_qr(configuration, entry, "internal", {"internal": "override"}) == {
        "visibility": ["internal"],
        "payload": "override",
    }
    assert viewer._selected_qr(configuration, entry, "external", {"external": None}) is None


def test_push_groups_by_geometry_and_payload_and_preserves_audiences(monkeypatch: pytest.MonkeyPatch) -> None:
    specification = ResolvedOutputSpecification("16:10", (80, 50))
    destinations = [
        {"identifier": "a", "audience": "external", "output_specification": specification},
        {"identifier": "b", "audience": "internal", "output_specification": specification},
        {"identifier": "c", "audience": "external", "output_specification": specification},
    ]
    entry = ContentEntry(id="entry", quotations=(Quotation("Example", "Example"),))
    configuration = SimpleNamespace(qr_defaults={"external": "one", "internal": "two"})
    calls = []
    monkeypatch.setattr(viewer, "_select_entry", lambda *_args: (entry, entry.quotations[0]))
    monkeypatch.setattr(viewer, "build_presentation_snapshot", lambda *_args: object())
    monkeypatch.setattr(viewer, "resolve_reveal_stages", lambda _snapshot: (object(),))
    monkeypatch.setattr(viewer, "resolve_canonical_presentation", lambda *_args, **_kwargs: {"canonical": True})

    def prepare(_snapshot, _stages, _configuration, specs, **kwargs):
        calls.append(kwargs)
        return {specs[0]: (Image.new("RGB", specs[0].requested_output_size),)}

    monkeypatch.setattr(viewer, "prepare_daily_images", prepare)
    images = viewer._render_push_variants(
        configuration,
        ("entry", 1),
        destinations,
        overrides=PresentationOverrides(),
        qr_overrides=None,
        debug_layout=False,
    )
    try:
        assert images["a"] is images["c"]
        assert images["a"] is not images["b"]
        assert [call["qr_declaration"]["payload"] for call in calls] == ["one", "two"]
        assert all(call["canonical_presentation"] == {"canonical": True} for call in calls)
    finally:
        for image in {id(image): image for image in images.values()}.values():
            image.close()


@pytest.mark.parametrize("suppress", [False, True])
def test_push_compatible_qr_shares_pixels_between_audiences(monkeypatch: pytest.MonkeyPatch, suppress: bool) -> None:
    specification = ResolvedOutputSpecification("16:10", (80, 50))
    destinations = [
        {"identifier": "a", "audience": "external", "output_specification": specification},
        {"identifier": "b", "audience": "internal", "output_specification": specification},
    ]
    entry = ContentEntry(id="entry", quotations=(Quotation("Example", "Example"),))
    configuration = SimpleNamespace(qr_defaults={"external": "one", "internal": "one"})
    calls = []
    monkeypatch.setattr(viewer, "_select_entry", lambda *_args: (entry, entry.quotations[0]))
    monkeypatch.setattr(viewer, "build_presentation_snapshot", lambda *_args: object())
    monkeypatch.setattr(viewer, "resolve_reveal_stages", lambda _snapshot: (object(),))
    monkeypatch.setattr(viewer, "resolve_canonical_presentation", lambda *_args, **_kwargs: {})

    def prepare(_snapshot, _stages, _configuration, specs, **kwargs):
        calls.append(kwargs)
        return {specs[0]: (Image.new("RGB", specs[0].requested_output_size),)}

    monkeypatch.setattr(viewer, "prepare_daily_images", prepare)
    images = viewer._render_push_variants(
        configuration,
        ("entry", 1),
        destinations,
        overrides=PresentationOverrides(qr_enabled=False if suppress else None),
        qr_overrides=None,
        debug_layout=False,
    )
    try:
        assert images["a"] is images["b"]
        assert len(calls) == 1
        assert calls[0]["qr_declaration"] == (None if suppress else {"visibility": ["external"], "payload": "one"})
    finally:
        images["a"].close()


def test_push_passes_discovered_audiences_and_images_to_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("test", encoding="utf-8")
    specification = ResolvedOutputSpecification("16:10", (80, 50))
    destinations = [
        {
            "identifier": identifier,
            "audience": audience,
            "output_specification": specification,
            "participating": True,
            "withdrawn": False,
            "supports_transient": True,
        }
        for identifier, audience in (("a", "external"), ("b", "internal"))
    ]
    images = {"a": Image.new("RGB", (80, 50)), "b": Image.new("RGB", (80, 50))}
    captured = {}

    class Client:
        def __init__(self, _path):
            pass

        def discover(self):
            return destinations

        def publish_transient(self, target, specifications, variants, *, audiences, on_accepted):
            captured.update(target=target, specifications=specifications, images=variants.copy(), audiences=audiences)
            on_accepted()
            return PublicationResult(PublicationStatus.SUCCEEDED, {"a": (True, None), "b": (True, None)})

    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(
        viewer, "resolve_application_paths", lambda: SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    )
    monkeypatch.setattr(viewer, "load_application_config", lambda _path: object())
    monkeypatch.setattr(viewer, "_render_push_variants", lambda *_args, **_kwargs: images)
    assert (
        viewer._run_push(
            "@all", config_file=config, selector=("entry", 1), overrides=PresentationOverrides(), debug_layout=False
        )
        == 0
    )
    assert captured["target"] == "@all"
    assert captured["specifications"] == {"a": specification, "b": specification}
    assert captured["audiences"] == {"a": "external", "b": "internal"}
    assert captured["images"]["a"] is not captured["images"]["b"]


def test_discovery_reports_unknown_delivery_without_claiming_availability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    class Client:
        def __init__(self, _path):
            pass

        def discover(self):
            return [
                {
                    "identifier": "published",
                    "audience": "external",
                    "output_specification": ResolvedOutputSpecification("16:10", (80, 50)),
                    "supports_transient": True,
                    "participating": True,
                    "available": "unknown",
                    "publication_accepted": True,
                    "withdrawn": False,
                }
            ]

    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(
        viewer, "resolve_application_paths", lambda: SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    )
    assert viewer._run_destination_discovery() == 0
    result = capsys.readouterr().out
    assert "unknown" in result
    assert "unavailable/failed" not in result


def test_reconstructs_real_completed_publication_without_current_qr_defaults(tmp_path: Path) -> None:
    font = Path(__file__).parent / "fixtures" / "fonts" / "Lora-Regular.ttf"
    state = tmp_path / "custom-state"
    artifacts = tmp_path / "custom-artifacts"
    state.mkdir()
    artifacts.mkdir()
    for path in (state / "state.json", state / "publication.json", artifacts / "sentinel"):
        path.write_text("unchanged", encoding="utf-8")
    configuration = ApplicationConfiguration(
        file=tmp_path / "config.yaml",
        display_backends=(),
        day_start=time(6),
        content_directory=tmp_path / "missing-content",
        reveal=RevealSchedule(time(12), time(18)),
        presentation_insets=PresentationInsets(384, 384, 216, 216),
        fonts={"lora": FontResource("lora", font, False, faces={"regular": font})},
        default_fonts=("lora",),
        min_font_size=40,
        max_font_size=120,
        storage=StorageConfiguration(state=state, artifacts=artifacts, publish=tmp_path / "publish"),
    )
    snapshot = DailySnapshot(
        entry_id="test",
        quotation_text="A small thought.",
        quotation_identity="A small thought.",
        source="Source",
        attribution=None,
        presentation_style="centered",
        font="lora",
        font_faces={},
        background=None,
        decoration=None,
        text_color=None,
        decoration_color=None,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(date(2026, 10, 26), "06:00"),
    )
    qr = {"visibility": ["external"], "payload": "original QR"}
    checkpoint = build_content_checkpoint(
        PersistentState(1, snapshot, frozenset({snapshot.quotation_identity}), 0), [qr]
    )
    canonical = resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    checkpoint["presentation"] = canonical
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    associations = {}
    images = prepare_daily_images(
        snapshot,
        (CompositionVisibility(quotation=True, source=False),),
        configuration,
        (specification,),
        canonical_presentation=canonical,
        qr_declaration=qr,
        selection_revision=1,
        on_metadata=associations.__setitem__,
    )
    for image in images[specification]:
        image.close()
    prepared = associations[specification][0]
    publication = finalize_publication_metadata(
        checkpoint,
        publication_type="scheduled",
        publication_id="event",
        published_at="2026-10-26T06:00:00Z",
        destination_id="screen",
        output_specification=specification,
        audience="external",
        selection_revision=prepared["selection_revision"],
        visibility=prepared["visibility"],
        effective_presentation=prepared["effective_presentation"],
        rendered_qr=prepared["rendered_qr"],
        prepared_output_specification=prepared["output_specification"],
    )
    path = tmp_path / "completed.json"
    path.write_text(serialize_publication_metadata(publication, stage="scheduled", audience="external"))
    parsed = viewer._read_publication_metadata(path)
    assert parsed["content"]["qr"] == [qr]
    assert parsed["content"]["reveal_stage"]["source"] is False
    image = viewer.render_publication(configuration, parsed, specification)
    try:
        assert image.size == specification.requested_output_size
        assert not configuration.content_directory.exists()
    finally:
        image.close()
    suppressed = viewer.render_publication(
        configuration, parsed, specification, overrides=PresentationOverrides(qr_enabled=False)
    )
    suppressed.close()
    assert parsed["content"]["qr"] == [qr]
    missing_font = {
        **parsed,
        "presentation": {
            **parsed["presentation"],
            "fonts": {**parsed["presentation"]["fonts"], "bundle": "missing-font"},
        },
    }
    with pytest.raises(viewer.ViewerError, match="font"):
        viewer.render_publication(configuration, missing_font, specification)

    path.write_text(serialize_publication_metadata(checkpoint, stage="presentation"))
    with pytest.raises(viewer.ViewerError, match="invalid publication"):
        viewer._read_publication_metadata(path)
    assert all(
        path.read_text(encoding="utf-8") == "unchanged"
        for path in (state / "state.json", state / "publication.json", artifacts / "sentinel")
    )
    assert not (tmp_path / "publish").exists()
    path.write_text("[" * 2000 + "]" * 2000)
    with pytest.raises(viewer.ViewerError, match="invalid publication"):
        viewer._read_publication_metadata(path)
