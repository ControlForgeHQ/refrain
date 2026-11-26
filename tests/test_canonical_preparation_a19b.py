from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import replace
from datetime import date, time
from pathlib import Path
from random import Random

import pytest
from PIL import Image

import refrain.preparation as preparation
from refrain.checkpoint import CheckpointStore, validate_checkpoint
from refrain.config import (
    ApplicationConfiguration,
    DecorationLayerResource,
    DecorationResource,
    DestinationPresentation,
    FontResource,
    PreparedImageVariantKey,
    RevealSchedule,
)
from refrain.geometry import PresentationInsets, ResolvedOutputSpecification
from refrain.persistence import DailySnapshot, PersistentState, SchedulingContext
from refrain.publication_metadata import finalize_publication_metadata
from refrain.renderer import CompositionVisibility


def _inputs():
    font = Path(__file__).parent / "fixtures" / "fonts" / "Lora-Regular.ttf"
    configuration = ApplicationConfiguration(
        file=Path("/config.yaml"),
        display_backends=(),
        day_start=time(6),
        content_directory=Path("/content"),
        reveal=RevealSchedule(time(12), time(18)),
        presentation_insets=PresentationInsets(384, 384, 216, 216),
        fonts={"lora": FontResource("lora", font, bundled=False)},
        default_fonts=("lora",),
        min_font_size=40,
        max_font_size=120,
    )
    snapshot = DailySnapshot(
        entry_id="test",
        quotation_text="A small thought.",
        quotation_identity="A small thought.",
        source=None,
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
    return snapshot, configuration


def test_canonical_is_independent_of_destination_and_preserved_on_fallback():
    snapshot, configuration = _inputs()
    canonical = preparation.resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    original = deepcopy(canonical)
    assert canonical["fonts"]["bundle"] == "lora"
    canonical["background"] = "missing-background"
    canonical["colors"]["text"] = "missing-color"
    changed = deepcopy(canonical)
    associations = {}
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    variants = preparation.prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        configuration,
        (specification,),
        canonical_presentation=canonical,
        selection_revision=1,
        on_metadata=associations.__setitem__,
    )
    try:
        effective = associations[specification][0]["effective_presentation"]
        assert effective["background"] == "none"
        assert effective["colors"]["text"] == "black"
        assert canonical == changed
        assert original["background"] == "none"
    finally:
        for images in variants.values():
            for image in images:
                image.close()


def test_rendered_qr_association_uses_exact_selected_payload(monkeypatch):
    snapshot, configuration = _inputs()
    canonical = preparation.resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    declaration = {"visibility": ["internal"], "payload": "  exact UTF-8 \N{SNOWMAN}  "}
    rendered = []
    real_render = preparation.render_qr_code

    def record(parameters, size, placement):
        rendered.append(parameters.url)
        return real_render(parameters, size, placement)

    monkeypatch.setattr(preparation, "render_qr_code", record)
    associations = {}
    variants = preparation.prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        replace(configuration, qr_enabled=False),
        (specification,),
        canonical_presentation=canonical,
        qr_declaration=declaration,
        selection_revision=3,
        on_metadata=associations.__setitem__,
    )
    try:
        assert rendered == [declaration["payload"]]
        association = associations[specification][0]
        assert association["rendered_qr"] == declaration
        assert association["selection_revision"] == 3
        assert "schema_version" not in association
    finally:
        for images in variants.values():
            for image in images:
                image.close()


def test_absent_qr_is_not_rendered_or_associated(monkeypatch):
    snapshot, configuration = _inputs()
    canonical = preparation.resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    monkeypatch.setattr(preparation, "render_qr_code", lambda *args: (_ for _ in ()).throw(AssertionError()))
    associations = {}
    variants = preparation.prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        configuration,
        (specification,),
        canonical_presentation=canonical,
        selection_revision=1,
        on_metadata=associations.__setitem__,
    )
    try:
        assert associations[specification][0]["rendered_qr"] is None
    finally:
        for images in variants.values():
            for image in images:
                image.close()


def test_dynamic_key_retains_payload_and_suppression(monkeypatch):
    snapshot, configuration = _inputs()
    canonical = preparation.resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    declaration = {"visibility": ["external"], "payload": "payload"}
    key = PreparedImageVariantKey(specification, DestinationPresentation(), "payload")
    associations = {}
    variants = preparation.prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        configuration,
        (key,),
        canonical_presentation=canonical,
        qr_declaration=declaration,
        overrides=preparation.PresentationOverrides(qr_enabled=False),
        selection_revision=1,
        on_metadata=associations.__setitem__,
    )
    try:
        assert list(variants) == [key]
        assert associations[key][0]["rendered_qr"] is None
    finally:
        for images in variants.values():
            for image in images:
                image.close()
    with pytest.raises(preparation.DailyImagePreparationError, match="payload does not match"):
        preparation.prepare_daily_images(
            snapshot,
            (CompositionVisibility(),),
            configuration,
            (key,),
            canonical_presentation=canonical,
            qr_declaration={"visibility": ["external"], "payload": "different"},
        )


def test_strict_published_missing_resource_does_not_fall_back():
    snapshot, configuration = _inputs()
    canonical = preparation.resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    canonical["background"] = "missing-background"
    with pytest.raises(preparation.DailyImagePreparationError, match="published background"):
        preparation.prepare_daily_images(
            snapshot,
            (CompositionVisibility(),),
            configuration,
            (ResolvedOutputSpecification("16:10", (800, 500)),),
            canonical_presentation=canonical,
            strict_published_presentation=True,
        )


def test_missing_canonical_font_uses_default_without_changing_checkpoint():
    snapshot, configuration = _inputs()
    canonical = preparation.resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    canonical["fonts"]["bundle"] = "missing-font"
    original = deepcopy(canonical)
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    associations = {}
    variants = preparation.prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        configuration,
        (specification,),
        canonical_presentation=canonical,
        selection_revision=1,
        on_metadata=associations.__setitem__,
    )
    try:
        assert associations[specification][0]["effective_presentation"]["fonts"]["bundle"] == "lora"
        assert canonical == original
    finally:
        for images in variants.values():
            for image in images:
                image.close()


@pytest.mark.parametrize("condition", ["tintable", "layer-untintable", "decoration-untintable", "failed"])
def test_unavailable_persisted_decoration_tint_preserves_checkpoint_and_effective_metadata(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, condition: str
) -> None:
    snapshot, configuration = _inputs()
    snapshot = replace(snapshot, decoration="frame", decoration_color=("retired",))
    layer_path = tmp_path / "frame.png"
    with Image.new("RGBA", (8, 8), (200, 30, 40, 128)) as layer_image:
        layer_image.save(layer_path)
    layer = DecorationLayerResource(layer_path, "cover")
    decoration = DecorationResource("frame", (layer,), False)
    configuration = replace(
        configuration,
        decorations={"frame": decoration},
        palette={"black": "#000000", "retired": "#ff0000", "alternative": "#00ff00"},
        default_decoration_colors=("alternative",),
    )
    state = PersistentState(1, snapshot, frozenset({snapshot.quotation_identity}), 0)
    store = CheckpointStore(tmp_path / "publication.json")
    store.initialize(state, [])
    checkpoint = store.complete(
        state, lambda selected, _content: preparation.resolve_canonical_presentation(selected, configuration)
    )
    assert checkpoint["presentation"]["decoration"] == "frame"
    assert checkpoint["presentation"]["colors"]["decoration"] == "retired"
    before = store.path.read_bytes()

    if condition == "layer-untintable":
        decoration = replace(decoration, layers=(replace(layer, tintable=False),))
    elif condition == "decoration-untintable":
        decoration = replace(decoration, tintable=False)
    elif condition == "failed":
        layer_path.unlink()
    configuration = replace(
        configuration,
        decorations={"frame": decoration},
        palette={"black": "#000000", "alternative": "#00ff00"},
    )
    checkpoint = store.complete(state, lambda *_: pytest.fail("canonical choices must not be reselected"))
    validate_checkpoint(checkpoint, state, require_presentation=True)

    class FontChoiceOnly:
        def choice(self, values):
            assert values == ["lora"], "preparation must not randomly select a replacement color"
            return values[0]

    specification = ResolvedOutputSpecification("16:10", (320, 200))
    associations = {}
    with caplog.at_level(logging.WARNING):
        variants = preparation.prepare_daily_images(
            snapshot,
            (CompositionVisibility(),),
            configuration,
            (specification,),
            chooser=FontChoiceOnly(),
            canonical_presentation=checkpoint["presentation"],
            selection_revision=state.revision,
            on_metadata=associations.__setitem__,
        )
    try:
        pixel = variants[specification][0].getpixel((5, 5))
        prepared = associations[specification][0]
        completed = finalize_publication_metadata(
            checkpoint,
            publication_type="scheduled",
            publication_id="event",
            published_at="2026-10-26T06:00:00Z",
            destination_id="screen",
            output_specification=specification,
            audience="internal",
            selection_revision=prepared["selection_revision"],
            visibility=prepared["visibility"],
            effective_presentation=prepared["effective_presentation"],
            rendered_qr=prepared["rendered_qr"],
            prepared_output_specification=prepared["output_specification"],
        )
        effective = completed["presentation"]
        if condition == "tintable":
            assert pixel == (127, 127, 127)
            assert effective["decoration"] == "frame"
            assert effective["colors"]["decoration"] == "black"
            assert "decoration color 'retired' is unavailable; using black" in caplog.text
        elif condition == "failed":
            assert pixel == (255, 255, 255)
            assert effective["decoration"] == "none"
            assert effective["colors"]["decoration"] is None
            assert "discard" in caplog.text
        else:
            assert pixel == (227, 142, 147)
            assert effective["decoration"] == "frame"
            assert effective["colors"]["decoration"] is None
            assert "decoration color 'retired' is unavailable" not in caplog.text
        assert store.path.read_bytes() == before
        assert store.complete(state, lambda *_: pytest.fail("canonical choices must remain persisted")) == checkpoint
        assert checkpoint["presentation"]["decoration"] == "frame"
        assert checkpoint["presentation"]["colors"]["decoration"] == "retired"
    finally:
        for images in variants.values():
            for image in images:
                image.close()


def test_suppressed_destination_key_accepts_selected_declaration():
    snapshot, configuration = _inputs()
    canonical = preparation.resolve_canonical_presentation(snapshot, configuration, chooser=Random(1))
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    key = PreparedImageVariantKey(specification, DestinationPresentation(qr_enabled=False))
    associations = {}
    variants = preparation.prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        configuration,
        (key,),
        canonical_presentation=canonical,
        qr_declaration={"visibility": ["internal"], "payload": "payload"},
        selection_revision=1,
        on_metadata=associations.__setitem__,
    )
    try:
        assert associations[key][0]["rendered_qr"] is None
    finally:
        for images in variants.values():
            for image in images:
                image.close()
