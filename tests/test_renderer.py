from __future__ import annotations

import math
from importlib.resources import files
from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont

from refrain import QuotationRegion, ResolvedFont
from refrain.renderer import QuotationRenderError, layout_quotation, render_quotation


@pytest.fixture
def resolved_font() -> ResolvedFont:
    font_path = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")
    with font_path.open("rb") as font_file:
        return ResolvedFont("lora", font_file.read())


def make_layout(
    text: str,
    font: ResolvedFont,
    *,
    size: tuple[int, int] = (800, 600),
    region: QuotationRegion = QuotationRegion(0.1, 0.1, 0.8, 0.8),
    sizes: tuple[int, int] = (20, 72),
):
    return layout_quotation(text, font, region, size, *sizes)


def test_short_quotation_uses_maximum_and_returns_background_copy(resolved_font: ResolvedFont) -> None:
    background = Image.new("RGB", (400, 300), "#f8f6f0")
    background.putpixel((5, 5), (15, 30, 45))
    original = background.copy()
    layout = make_layout("A pause.", resolved_font, size=background.size, sizes=(18, 42))

    rendered = render_quotation(background, resolved_font, layout)

    assert layout.font_size == 42
    assert layout.lines == ("A pause.",)
    assert rendered is not background
    assert background.tobytes() == original.tobytes()
    assert rendered.getpixel((5, 5)) == (15, 30, 45)
    assert rendered.getbbox() == (0, 0, 400, 300)
    assert layout.region[0] <= layout.text_bounds[0] < layout.text_bounds[2] <= layout.region[2]
    assert layout.region[1] <= layout.text_bounds[1] < layout.text_bounds[3] <= layout.region[3]

    for y in range(background.height):
        for x in range(background.width):
            if not (layout.region[0] <= x < layout.region[2] and layout.region[1] <= y < layout.region[3]):
                assert rendered.getpixel((x, y)) == original.getpixel((x, y))


def test_ordinary_paragraph_wraps_using_font_measurements(resolved_font: ResolvedFont) -> None:
    text = "Measured letters make a careful line; words move together without being cut."
    layout = make_layout(
        text,
        resolved_font,
        size=(500, 400),
        region=QuotationRegion(0.1, 0.1, 0.36, 0.8),
        sizes=(20, 42),
    )

    assert len(layout.lines) > 1
    assert " ".join(" ".join(line.split()) for line in layout.lines) == text
    assert layout.font_size < 42
    assert all(line for line in layout.lines)


def test_long_quotation_uses_smaller_font_size(resolved_font: ResolvedFont) -> None:
    text = (
        "A patient observer notices the changing light, the softened edges of the room, and the small details "
        "that become visible only when attention has time to settle."
    )
    layout = make_layout(
        text,
        resolved_font,
        size=(500, 300),
        region=QuotationRegion(0.08, 0.1, 0.84, 0.72),
        sizes=(18, 56),
    )

    assert layout.font_size < 56
    assert len(layout.lines) > 2
    assert " ".join(" ".join(line.split()) for line in layout.lines) == text


def test_explicit_line_breaks_and_blank_paragraph_lines_are_preserved(resolved_font: ResolvedFont) -> None:
    text = "A first line\nA second line\n\nA new paragraph."
    layout = make_layout(text, resolved_font, sizes=(20, 30))

    assert layout.lines == ("A first line", "A second line", "", "A new paragraph.")
    assert layout.positions[2][1] > layout.positions[1][1]


def test_unicode_punctuation_and_original_text_are_retained(resolved_font: ResolvedFont) -> None:
    text = "“Wait,” she said—then smiled: déjà vu?"
    layout = make_layout(text, resolved_font, sizes=(20, 32))

    assert layout.text == text
    assert "".join(layout.lines) == text


def test_long_unbroken_word_that_cannot_fit_fails_clearly(resolved_font: ResolvedFont) -> None:
    with pytest.raises(QuotationRenderError, match="does not fit.*minimum font size"):
        layout_quotation(
            "Supercalifragilisticexpialidocious",
            resolved_font,
            QuotationRegion(0.49, 0.1, 0.02, 0.8),
            (500, 300),
            20,
            40,
        )


def test_quotation_can_fit_exactly_at_minimum_font_size(resolved_font: ResolvedFont) -> None:
    pillow_font = ImageFont.truetype(BytesIO(resolved_font.data), size=18)
    exact_height = sum(pillow_font.getmetrics())
    layout = layout_quotation(
        "A",
        resolved_font,
        QuotationRegion(0, 0, 1, exact_height / exact_height),
        (400, exact_height),
        18,
        32,
    )

    assert layout.font_size == 18
    assert layout.region[3] - layout.region[1] == exact_height


def test_intermediate_size_selected_when_maximum_does_not_fit(resolved_font: ResolvedFont) -> None:
    layout = make_layout(
        "A modest line of text.",
        resolved_font,
        size=(260, 110),
        region=QuotationRegion(0.08, 0.08, 0.84, 0.84),
        sizes=(16, 90),
    )

    assert 16 < layout.font_size < 90


@pytest.mark.parametrize(
    ("size", "region"),
    [
        ((400, 300), QuotationRegion(0.0, 0.0, 0.2, 0.2)),
        ((1600, 1200), QuotationRegion(0.8, 0.85, 0.2, 0.15)),
        ((320, 240), QuotationRegion(0.2, 0.3, 0.5, 0.4)),
    ],
)
def test_normalized_regions_use_actual_image_dimensions(
    resolved_font: ResolvedFont, size: tuple[int, int], region: QuotationRegion
) -> None:
    layout = layout_quotation("Geometry.", resolved_font, region, size, 16, 30)
    expected = (
        math.floor(region.x * size[0]),
        math.floor(region.y * size[1]),
        math.ceil((region.x + region.width) * size[0]),
        math.ceil((region.y + region.height) * size[1]),
    )

    assert layout.image_size == size
    assert layout.region[0] == expected[0]
    assert layout.region[1] == expected[1]
    assert layout.region[2] <= size[0]
    assert layout.region[3] <= size[1]
    assert layout.region[0] <= layout.text_bounds[0] < layout.text_bounds[2] <= layout.region[2]
    assert layout.region[1] <= layout.text_bounds[1] < layout.text_bounds[3] <= layout.region[3]


def test_same_layout_renders_consistently_on_different_backgrounds(resolved_font: ResolvedFont) -> None:
    text = "The geometry is independent of the page beneath it."
    region = QuotationRegion(0.1, 0.2, 0.8, 0.6)
    first_layout = layout_quotation(text, resolved_font, region, (320, 240), 18, 44)
    second_layout = layout_quotation(text, resolved_font, region, (320, 240), 18, 44)
    first = render_quotation(Image.new("RGB", (320, 240), "white"), resolved_font, first_layout)
    second_background = Image.new("RGB", (320, 240), "#e8e1d2")
    ImageDraw.Draw(second_background).line((0, 30, 319, 30), fill="#aa5533", width=2)
    second = render_quotation(second_background, resolved_font, second_layout)

    assert first_layout == second_layout
    assert first_layout.lines == second_layout.lines
    assert first_layout.font_size == second_layout.font_size
    assert first_layout.text_bounds == second_layout.text_bounds
    assert second.getpixel((160, 30)) == (170, 85, 51)
    assert first.getpixel((160, 30)) == (255, 255, 255)


def test_grayscale_background_is_supported_and_preserved(resolved_font: ResolvedFont) -> None:
    background = Image.new("L", (200, 120), 240)
    background.putpixel((0, 0), 50)
    layout = layout_quotation(
        "A quiet page.",
        resolved_font,
        QuotationRegion(0.1, 0.1, 0.8, 0.8),
        background.size,
        16,
        30,
    )

    rendered = render_quotation(background, resolved_font, layout)

    assert rendered.mode == "L"
    assert rendered.getpixel((0, 0)) == 50
    assert background.getpixel((0, 0)) == 50


@pytest.mark.parametrize(
    ("region", "size_bounds", "image_size"),
    [
        (QuotationRegion(-0.1, 0, 0.5, 0.5), (10, 20), (100, 100)),
        (QuotationRegion(0.8, 0.8, 0.3, 0.3), (10, 20), (100, 100)),
        (QuotationRegion(0, 0, 1, 1), (0, 20), (100, 100)),
        (QuotationRegion(0, 0, 1, 1), (20, 10), (100, 100)),
        (QuotationRegion(0, 0, 1, 1), (10, 20), (100, 0)),
    ],
)
def test_invalid_rendering_inputs_are_rejected(
    resolved_font: ResolvedFont,
    region: QuotationRegion,
    size_bounds: tuple[int, int],
    image_size: tuple[int, int],
) -> None:
    with pytest.raises(QuotationRenderError):
        layout_quotation("A quotation.", resolved_font, region, image_size, *size_bounds)


def test_invalid_font_and_mismatched_background_are_rejected(resolved_font: ResolvedFont) -> None:
    bad_font = ResolvedFont("broken", b"not a font")
    with pytest.raises(QuotationRenderError, match="cannot be loaded"):
        make_layout("A quotation.", bad_font)

    layout = make_layout("A quotation.", resolved_font)
    with pytest.raises(QuotationRenderError, match="dimensions"):
        render_quotation(Image.new("RGB", (10, 10)), resolved_font, layout)


def test_empty_text_non_image_and_unsupported_mode_are_rejected(resolved_font: ResolvedFont) -> None:
    with pytest.raises(QuotationRenderError, match="nonempty"):
        make_layout("", resolved_font)

    layout = make_layout("A quotation.", resolved_font)
    with pytest.raises(QuotationRenderError, match="Pillow image"):
        render_quotation(object(), resolved_font, layout)  # type: ignore[arg-type]
    with pytest.raises(QuotationRenderError, match="mode"):
        render_quotation(Image.new("P", layout.image_size), resolved_font, layout)
