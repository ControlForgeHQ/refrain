from __future__ import annotations

from datetime import date
from importlib.resources import files

import pytest

import refrain.preparation as preparation
from refrain import (
    CompositionVisibility,
    DailyImagePreparationError,
    DailySnapshot,
    FontResource,
    SchedulingContext,
    prepare_daily_images,
    resolve_reveal_stages,
)

_IMAGE_SIZE = (320, 240)
_LAYOUT = {
    "image_size": _IMAGE_SIZE,
    "presentation_region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
    "min_font_size": 12,
    "max_font_size": 32,
}
_LORA = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")
_FONT_REGISTRY = {"lora": FontResource("lora", _LORA, bundled=True)}


@pytest.fixture
def embedded_font() -> str:
    return "lora"


def make_snapshot(
    font_identifier: str,
    *,
    source: str | None = "A Sample Collection",
    attribution: str | None = "An Example Author",
    style: str = "centered",
    metadata: dict[str, object] | None = None,
    layout: dict[str, object] | None = None,
) -> DailySnapshot:
    if metadata is None:
        metadata = {"presentation_style": style}
        if source is not None:
            metadata["source"] = source
        if attribution is not None:
            metadata["attribution"] = attribution
    return DailySnapshot(
        quotation_text="A small thought, carefully kept.",
        quotation_identity="A small thought, carefully kept.",
        font_identifier=font_identifier,
        presentation_metadata=metadata,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        layout=_LAYOUT if layout is None else layout,
        scheduling=SchedulingContext(date(2026, 10, 26), "Etc/UTC", "06:00"),
    )


@pytest.mark.parametrize(
    ("source", "attribution", "stages"),
    [
        (None, None, (CompositionVisibility(),)),
        ("A Sample Collection", None, (CompositionVisibility(), CompositionVisibility(source=True))),
        (None, "An Example Author", (CompositionVisibility(), CompositionVisibility(attribution=True))),
        (
            "A Sample Collection",
            "An Example Author",
            (
                CompositionVisibility(),
                CompositionVisibility(source=True),
                CompositionVisibility(source=True, attribution=True),
            ),
        ),
    ],
)
def test_prepares_all_optional_field_combinations_from_one_embedded_layout(
    embedded_font: str,
    monkeypatch: pytest.MonkeyPatch,
    source: str | None,
    attribution: str | None,
    stages: tuple[CompositionVisibility, ...],
) -> None:
    snapshot = make_snapshot(embedded_font, source=source, attribution=attribution)
    original_snapshot = snapshot
    original_layout = preparation.layout_composition
    resolved_layouts = []

    def capture_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        resolved_layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)

    images = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)

    assert len(resolved_layouts) == 1
    layout = resolved_layouts[0]
    assert layout.font_identifier == embedded_font
    assert (layout.quotation.text, layout.byline is not None) == (
        snapshot.quotation_text,
        source is not None or attribution is not None,
    )
    assert len(images) == len(stages)
    assert all(image.mode == "RGB" and image.size == _IMAGE_SIZE for image in images)
    assert all(image.getpixel((0, 0)) == (255, 255, 255) for image in images)
    assert len({id(image) for image in images}) == len(images)
    if len(images) > 1:
        assert images[0].tobytes() != images[-1].tobytes()
    assert snapshot == original_snapshot


def test_canonical_reveal_stages_can_be_passed_directly_to_preparation(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font, source="A Sample Collection", attribution="An Example Author")
    stages = resolve_reveal_stages(snapshot)

    images = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)

    assert stages == (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )
    assert len(images) == len(stages)
    for image in images:
        image.close()


def test_preparation_is_deterministic(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font)
    stages = (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )

    first = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)
    second = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)

    assert tuple(image.tobytes() for image in first) == tuple(image.tobytes() for image in second)


def test_uses_committed_presentation_style(embedded_font: str, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = make_snapshot(embedded_font, style="left-aligned")
    original_layout = preparation.layout_composition
    resolved_layouts = []

    def capture_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        resolved_layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)

    prepare_daily_images(snapshot, (CompositionVisibility(),), _FONT_REGISTRY)

    assert resolved_layouts[0].style == "left-aligned"


@pytest.mark.parametrize(
    ("metadata", "layout", "message"),
    [
        ({}, _LAYOUT, "presentation_style"),
        ({"presentation_style": "unknown"}, _LAYOUT, "presentation_style"),
        ({"presentation_style": "prose"}, _LAYOUT, "presentation_style"),
        ({"presentation_style": "centered", "source": ""}, _LAYOUT, "source"),
        ({"presentation_style": "centered"}, {**_LAYOUT, "image_size": (0, 240)}, "image_size"),
        (
            {"presentation_style": "centered"},
            {**_LAYOUT, "presentation_region": {"x": 0.1, "y": 0.1, "height": 0.8}},
            "presentation_region is missing width",
        ),
        (
            {"presentation_style": "centered"},
            {**_LAYOUT, "presentation_region": {"x": 0.9, "y": 0.1, "width": 0.2, "height": 0.8}},
            "normalized rectangle",
        ),
        ({"presentation_style": "centered"}, {**_LAYOUT, "min_font_size": 0}, "min_font_size"),
        ({"presentation_style": "centered"}, {**_LAYOUT, "max_font_size": 10}, "max_font_size"),
    ],
)
def test_invalid_snapshot_presentation_data_is_actionable(
    embedded_font: str,
    metadata: dict[str, object],
    layout: dict[str, object],
    message: str,
) -> None:
    snapshot = make_snapshot(embedded_font, metadata=metadata, layout=layout)

    with pytest.raises(DailyImagePreparationError, match=message):
        prepare_daily_images(snapshot, (CompositionVisibility(),), _FONT_REGISTRY)


def test_invalid_stage_sequence_is_rejected(embedded_font: str) -> None:
    with pytest.raises(DailyImagePreparationError, match="nonempty sequence"):
        prepare_daily_images(make_snapshot(embedded_font), (), _FONT_REGISTRY)


def test_non_cumulative_or_absent_field_reveal_fails_without_mutation(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font, source=None, attribution=None)
    original_snapshot = snapshot

    with pytest.raises(DailyImagePreparationError, match="cannot reveal a field that is absent"):
        prepare_daily_images(
            snapshot,
            (CompositionVisibility(), CompositionVisibility(source=True)),
            _FONT_REGISTRY,
        )

    assert snapshot == original_snapshot


def test_reveal_stages_must_remain_cumulative(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font)

    with pytest.raises(DailyImagePreparationError, match="reveal stages must be cumulative"):
        prepare_daily_images(
            snapshot,
            (
                CompositionVisibility(),
                CompositionVisibility(source=True),
                CompositionVisibility(),
            ),
            _FONT_REGISTRY,
        )


def test_missing_font_fails_clearly_without_bundled_fallback() -> None:
    snapshot = make_snapshot("missing-font")

    with pytest.raises(DailyImagePreparationError, match="no usable bundled fallback"):
        prepare_daily_images(snapshot, (CompositionVisibility(),), {})


def test_unusable_selected_font_uses_deterministic_bundled_fallback(tmp_path, caplog, monkeypatch) -> None:
    broken_path = tmp_path / "broken.ttf"
    broken_path.write_bytes(b"not a font")
    snapshot = make_snapshot("broken")
    registry = {
        "broken": FontResource("broken", broken_path, bundled=False),
        "a-fallback": FontResource("a-fallback", _LORA, bundled=True),
        "z-fallback": FontResource("z-fallback", _LORA, bundled=True),
    }
    original_layout = preparation.layout_composition
    layouts = []

    def capture_layout(*args, **kwargs):
        layout = original_layout(*args, **kwargs)
        layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)

    images = prepare_daily_images(snapshot, (CompositionVisibility(),), registry)

    assert images[0].size == _IMAGE_SIZE
    assert layouts[0].font_identifier == "a-fallback"
    assert "broken" in caplog.text


def test_composition_that_cannot_fit_fails_without_mutation(embedded_font: str) -> None:
    layout = {
        "image_size": (100, 100),
        "presentation_region": {"x": 0.49, "y": 0.49, "width": 0.02, "height": 0.02},
        "min_font_size": 24,
        "max_font_size": 28,
    }
    snapshot = make_snapshot(embedded_font, source=None, attribution=None, layout=layout)
    original_snapshot = snapshot

    with pytest.raises(DailyImagePreparationError, match="does not fit"):
        prepare_daily_images(snapshot, (CompositionVisibility(),), _FONT_REGISTRY)

    assert snapshot == original_snapshot


def test_non_snapshot_input_fails_clearly() -> None:
    with pytest.raises(DailyImagePreparationError, match="DailySnapshot"):
        prepare_daily_images(None, (CompositionVisibility(),), _FONT_REGISTRY)  # type: ignore[arg-type]
