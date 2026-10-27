from __future__ import annotations

import math
from importlib.resources import files
from io import BytesIO

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont

from refrain import (
    CompositionVisibility,
    LiteraryComposition,
    PresentationRegion,
    ResolvedFont,
    layout_composition,
    render_reveal_stages,
)
from refrain.renderer import QuotationRenderError


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
    region: PresentationRegion = PresentationRegion(0.1, 0.1, 0.8, 0.8),
    sizes: tuple[int, int] = (20, 72),
    style: str = "centered",
):
    return layout_composition(LiteraryComposition(text), font, region, size, *sizes, style)


def render_layout(background: Image.Image, font: ResolvedFont, layout):
    return render_reveal_stages(background, font, layout, (CompositionVisibility(),))[0]


def test_short_quotation_uses_maximum_and_returns_background_copy(resolved_font: ResolvedFont) -> None:
    background = Image.new("RGB", (400, 300), "#f8f6f0")
    background.putpixel((5, 5), (15, 30, 45))
    original = background.copy()
    layout = make_layout("A pause.", resolved_font, size=background.size, sizes=(18, 42))

    rendered = render_layout(background, resolved_font, layout)

    assert layout.quotation.font_size == 42
    assert layout.quotation.lines == ("A pause.",)
    assert rendered is not background
    assert background.tobytes() == original.tobytes()
    assert rendered.getpixel((5, 5)) == (15, 30, 45)
    assert rendered.getbbox() == (0, 0, 400, 300)
    assert layout.region[0] <= layout.quotation.bounds[0] < layout.quotation.bounds[2] <= layout.region[2]
    assert layout.region[1] <= layout.quotation.bounds[1] < layout.quotation.bounds[3] <= layout.region[3]

    for y in range(background.height):
        for x in range(background.width):
            if not (layout.region[0] <= x < layout.region[2] and layout.region[1] <= y < layout.region[3]):
                assert rendered.getpixel((x, y)) == original.getpixel((x, y))


@pytest.mark.parametrize("style", ["centered", "prose"])
def test_ordinary_paragraph_wraps_using_font_measurements(resolved_font: ResolvedFont, style: str) -> None:
    text = "Measured letters make a careful line; words move together without being cut."
    layout = make_layout(
        text,
        resolved_font,
        size=(500, 400),
        region=PresentationRegion(0.1, 0.1, 0.36, 0.8),
        sizes=(20, 42),
        style=style,
    )

    assert len(layout.quotation.lines) > 1
    assert " ".join(" ".join(line.split()) for line in layout.quotation.lines) == text
    assert layout.quotation.font_size < 42
    assert all(line for line in layout.quotation.lines)
    with pytest.raises(QuotationRenderError, match="does not fit"):
        make_layout(
            text,
            resolved_font,
            size=(500, 400),
            region=PresentationRegion(0.1, 0.1, 0.36, 0.8),
            sizes=(layout.quotation.font_size + 1, layout.quotation.font_size + 1),
            style=style,
        )


def test_long_quotation_uses_smaller_font_size(resolved_font: ResolvedFont) -> None:
    text = (
        "A patient observer notices the changing light, the softened edges of the room, and the small details "
        "that become visible only when attention has time to settle."
    )
    layout = make_layout(
        text,
        resolved_font,
        size=(500, 300),
        region=PresentationRegion(0.08, 0.1, 0.84, 0.72),
        sizes=(18, 56),
    )

    assert layout.quotation.font_size < 56
    assert len(layout.quotation.lines) > 2
    assert " ".join(" ".join(line.split()) for line in layout.quotation.lines) == text


def test_explicit_line_breaks_and_blank_paragraph_lines_are_preserved(resolved_font: ResolvedFont) -> None:
    text = "A first line\nA second line\n\nA new paragraph."
    layout = make_layout(text, resolved_font, sizes=(20, 30))

    assert layout.quotation.lines == ("A first line", "A second line", "", "A new paragraph.")
    assert layout.quotation.positions[2][1] > layout.quotation.positions[1][1]


@pytest.mark.parametrize("style", ["centered", "prose"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("height", [180, 500])
def test_authored_lines_take_priority_over_larger_wrapped_text(
    resolved_font: ResolvedFont, style: str, newline: str, height: int
) -> None:
    lines = ("A deliberately long line", "and a shorter one.")
    composition = LiteraryComposition(
        newline.join(lines), source="Notes on Patient Reading", attribution="An Example Author"
    )
    region = PresentationRegion(0, 0, 1, 1)
    size = (480, height)
    layout = layout_composition(composition, resolved_font, region, size, 20, 50, style)

    assert layout.quotation.lines == lines
    assert 20 < layout.quotation.font_size < 50
    valid_sizes = []
    for font_size in range(20, 51):
        try:
            candidate = layout_composition(composition, resolved_font, region, size, font_size, font_size, style)
        except QuotationRenderError:
            continue
        if candidate.quotation.lines == lines:
            valid_sizes.append(font_size)
    assert layout.quotation.font_size == max(valid_sizes)
    assert layout.byline is not None
    assert layout.byline.source is not None
    assert layout.byline.attribution is not None
    for field in (layout.quotation, layout.byline.source, layout.byline.attribution):
        assert 0 <= field.bounds[0] < field.bounds[2] <= size[0]
        assert 0 <= field.bounds[1] < field.bounds[3] <= size[1]
    assert layout.byline.bounds[1] - layout.quotation.bounds[3] == layout.byline_gap


@pytest.mark.parametrize("style", ["centered", "prose"])
def test_authored_lines_wrap_when_they_cannot_be_preserved_at_minimum(resolved_font: ResolvedFont, style: str) -> None:
    text = "A deliberately long line\nand a shorter one."
    region = PresentationRegion(0, 0, 1, 1)
    minimum = make_layout(text, resolved_font, size=(180, 400), region=region, sizes=(20, 20), style=style)
    layout = make_layout(text, resolved_font, size=(180, 400), region=region, sizes=(20, 42), style=style)

    assert len(minimum.quotation.lines) > 2
    assert len(layout.quotation.lines) > 2
    assert layout.quotation.font_size > 20
    assert " ".join(layout.quotation.lines) == text.replace("\n", " ")
    assert any(
        " ".join(layout.quotation.lines[:index]) == text.split("\n")[0]
        for index in range(1, len(layout.quotation.lines))
    )
    with pytest.raises(QuotationRenderError, match="does not fit"):
        make_layout(
            text,
            resolved_font,
            size=(180, 400),
            region=region,
            sizes=(layout.quotation.font_size + 1, layout.quotation.font_size + 1),
            style=style,
        )


def test_unicode_punctuation_and_original_text_are_retained(resolved_font: ResolvedFont) -> None:
    text = "“Wait,” she said—then smiled: déjà vu?"
    layout = make_layout(text, resolved_font, sizes=(20, 32))

    assert layout.quotation.text == text
    assert "".join(layout.quotation.lines) == text


@pytest.mark.parametrize("style", ["centered", "prose"])
@pytest.mark.parametrize("text", ["Supercalifragilisticexpialidocious", "A line\nSupercalifragilisticexpialidocious"])
def test_long_unbroken_word_that_cannot_fit_fails_clearly(resolved_font: ResolvedFont, style: str, text: str) -> None:
    with pytest.raises(QuotationRenderError, match="does not fit.*minimum.*font size"):
        layout_composition(
            LiteraryComposition(text),
            resolved_font,
            PresentationRegion(0.49, 0.1, 0.02, 0.8),
            (500, 300),
            20,
            40,
            style,
        )


def test_quotation_can_fit_exactly_at_minimum_font_size(resolved_font: ResolvedFont) -> None:
    pillow_font = ImageFont.truetype(BytesIO(resolved_font.data), size=18)
    exact_height = sum(pillow_font.getmetrics())
    layout = layout_composition(
        LiteraryComposition("A"),
        resolved_font,
        PresentationRegion(0, 0, 1, exact_height / exact_height),
        (400, exact_height),
        18,
        32,
        "centered",
    )

    assert layout.quotation.font_size == 18
    assert layout.region[3] - layout.region[1] == exact_height


def test_intermediate_size_selected_when_maximum_does_not_fit(resolved_font: ResolvedFont) -> None:
    layout = make_layout(
        "A modest line of text.",
        resolved_font,
        size=(260, 110),
        region=PresentationRegion(0.08, 0.08, 0.84, 0.84),
        sizes=(16, 90),
    )

    assert 16 < layout.quotation.font_size < 90


@pytest.mark.parametrize(
    ("size", "region"),
    [
        ((400, 300), PresentationRegion(0.0, 0.0, 0.2, 0.2)),
        ((1600, 1200), PresentationRegion(0.8, 0.85, 0.2, 0.15)),
        ((320, 240), PresentationRegion(0.2, 0.3, 0.5, 0.4)),
    ],
)
def test_normalized_regions_use_actual_image_dimensions(
    resolved_font: ResolvedFont, size: tuple[int, int], region: PresentationRegion
) -> None:
    layout = layout_composition(LiteraryComposition("I"), resolved_font, region, size, 16, 30, "centered")
    expected = (
        math.floor(region.x * size[0]),
        math.floor(region.y * size[1]),
        math.ceil((region.x + region.width) * size[0]),
        math.ceil((region.y + region.height) * size[1]),
    )

    assert layout.image_size == size
    assert layout.region == expected
    assert layout.region[2] <= size[0]
    assert layout.region[3] <= size[1]
    assert layout.region[0] <= layout.quotation.bounds[0] < layout.quotation.bounds[2] <= layout.region[2]
    assert layout.region[1] <= layout.quotation.bounds[1] < layout.quotation.bounds[3] <= layout.region[3]


def test_same_layout_renders_consistently_on_different_backgrounds(resolved_font: ResolvedFont) -> None:
    text = "The geometry is independent of the page beneath it."
    region = PresentationRegion(0.1, 0.2, 0.8, 0.6)
    first_layout = layout_composition(LiteraryComposition(text), resolved_font, region, (320, 240), 18, 44, "centered")
    second_layout = layout_composition(LiteraryComposition(text), resolved_font, region, (320, 240), 18, 44, "centered")
    first = render_layout(Image.new("RGB", (320, 240), "white"), resolved_font, first_layout)
    second_background = Image.new("RGB", (320, 240), "#e8e1d2")
    ImageDraw.Draw(second_background).line((0, 30, 319, 30), fill="#aa5533", width=2)
    second = render_layout(second_background, resolved_font, second_layout)

    assert first_layout == second_layout
    assert first_layout.quotation.lines == second_layout.quotation.lines
    assert first_layout.quotation.font_size == second_layout.quotation.font_size
    assert first_layout.quotation.bounds == second_layout.quotation.bounds
    assert second.getpixel((160, 30)) == (170, 85, 51)
    assert first.getpixel((160, 30)) == (255, 255, 255)


def test_grayscale_background_is_supported_and_preserved(resolved_font: ResolvedFont) -> None:
    background = Image.new("L", (200, 120), 240)
    background.putpixel((0, 0), 50)
    layout = layout_composition(
        LiteraryComposition("A quiet page."),
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        background.size,
        16,
        30,
        "centered",
    )

    rendered = render_layout(background, resolved_font, layout)

    assert rendered.mode == "L"
    assert rendered.getpixel((0, 0)) == 50
    assert background.getpixel((0, 0)) == 50


@pytest.mark.parametrize("style", ["centered", "prose"])
@pytest.mark.parametrize(
    "text",
    [
        "A deliberately long line\nand a shorter one.\n\nA new paragraph.",
        "A deliberately long line\nand a shorter one.",
    ],
)
def test_complete_composition_reuses_geometry_across_cumulative_stages(
    resolved_font: ResolvedFont, style: str, text: str
) -> None:
    background = Image.new("RGB", (600, 500), "#f8f6f0")
    composition = LiteraryComposition(
        text,
        source="Notes on Patient Reading",
        attribution="An Example Author",
    )
    layout = layout_composition(
        composition,
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        background.size,
        20,
        50,
        style,
    )
    stages = (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )
    images = render_reveal_stages(background, resolved_font, layout, stages)

    assert layout.byline is not None
    assert layout.byline.source is not None
    assert layout.byline.attribution is not None
    assert layout.quotation.font_size > layout.byline.attribution.font_size
    assert layout.quotation.lines == tuple(text.split("\n"))
    assert layout.region[0] <= layout.quotation.bounds[0] < layout.quotation.bounds[2] <= layout.region[2]
    assert layout.region[0] <= layout.byline.bounds[0] < layout.byline.bounds[2] <= layout.region[2]
    assert layout.region[1] <= layout.byline.bounds[1] < layout.byline.bounds[3] <= layout.region[3]
    for field in (layout.quotation, layout.byline.source, layout.byline.attribution):
        assert layout.region[0] <= field.bounds[0] < field.bounds[2] <= layout.region[2]
        assert layout.region[1] <= field.bounds[1] < field.bounds[3] <= layout.region[3]
    assert layout.quotation.bounds[3] < layout.byline.bounds[1]
    assert layout.byline.bounds[1] - layout.quotation.bounds[3] == layout.byline_gap
    composition_center = (layout.quotation.bounds[1] + layout.byline.bounds[3]) / 2
    region_center = (layout.region[1] + layout.region[3]) / 2
    assert abs(composition_center - region_center) <= 1
    assert len(images) == len(stages)
    assert images[0].crop(layout.quotation.bounds).tobytes() == images[1].crop(layout.quotation.bounds).tobytes()
    assert images[1].crop(layout.quotation.bounds).tobytes() == images[2].crop(layout.quotation.bounds).tobytes()
    assert (
        images[0].crop(layout.byline.source.bounds).tobytes() != images[1].crop(layout.byline.source.bounds).tobytes()
    )
    assert (
        images[1].crop(layout.byline.source.bounds).tobytes() == images[2].crop(layout.byline.source.bounds).tobytes()
    )
    assert (
        images[1].crop(layout.byline.attribution.bounds).tobytes()
        != images[2].crop(layout.byline.attribution.bounds).tobytes()
    )
    assert (
        images[0].crop(layout.byline.prefix.bounds).tobytes() == images[1].crop(layout.byline.prefix.bounds).tobytes()
    )
    assert (
        images[1].crop(layout.byline.separator.bounds).tobytes()
        == images[2].crop(layout.byline.separator.bounds).tobytes()
    )

    quote_font = ImageFont.truetype(BytesIO(resolved_font.data), size=layout.quotation.font_size)
    line_bounds = tuple(
        (
            position[0] + quote_font.getbbox(line)[0],
            position[0] + quote_font.getbbox(line)[2],
        )
        for line, position in zip(layout.quotation.lines, layout.quotation.positions, strict=True)
        if line
    )
    if style == "centered":
        region_center = (layout.region[0] + layout.region[2]) / 2
        for ink_left, ink_right in line_bounds:
            assert abs((ink_left + ink_right) / 2 - region_center) <= 1
        assert abs((layout.byline.bounds[0] + layout.byline.bounds[2]) / 2 - region_center) <= 1
    else:
        assert len({bounds[0] for bounds in line_bounds}) == 1
        assert layout.byline.bounds[2] == layout.region[2]


@pytest.mark.parametrize(
    ("source", "attribution", "expected_prefix", "expected_separator", "style"),
    [
        ("A Source", "An Attribution", "— ", ", ", "centered"),
        ("A Source", None, "— ", None, "centered"),
        (None, "An Attribution", "— ", None, "centered"),
        (None, None, None, None, "centered"),
        ("A Source", "An Attribution", "— ", ", ", "prose"),
        ("A Source", None, "— ", None, "prose"),
        (None, "An Attribution", "— ", None, "prose"),
        (None, None, None, None, "prose"),
    ],
)
def test_optional_byline_fields_have_only_required_punctuation(
    resolved_font: ResolvedFont,
    source: str | None,
    attribution: str | None,
    expected_prefix: str | None,
    expected_separator: str | None,
    style: str,
) -> None:
    layout = layout_composition(
        LiteraryComposition("A quotation.", source=source, attribution=attribution),
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        (600, 400),
        20,
        48,
        style,
    )

    if source is None and attribution is None:
        assert layout.byline is None
        assert layout.quotation.bounds[1] > layout.region[1]
        quotation_center = (layout.quotation.bounds[1] + layout.quotation.bounds[3]) / 2
        region_center = (layout.region[1] + layout.region[3]) / 2
        assert abs(quotation_center - region_center) <= 1
        return

    assert layout.byline is not None
    assert layout.byline.prefix is not None
    assert layout.byline.prefix.text == expected_prefix
    assert (layout.byline.separator.text if layout.byline.separator is not None else None) == expected_separator
    assert (layout.byline.source.text if layout.byline.source is not None else None) == source
    assert (layout.byline.attribution.text if layout.byline.attribution is not None else None) == attribution
    fields_in_order = [
        field
        for field in (
            layout.byline.prefix,
            layout.byline.attribution,
            layout.byline.separator,
            layout.byline.source,
        )
        if field is not None
    ]
    assert [field.bounds[0] for field in fields_in_order] == sorted(field.bounds[0] for field in fields_in_order)
    assert layout.region[0] <= layout.byline.bounds[0] < layout.byline.bounds[2] <= layout.region[2]
    assert layout.region[1] <= layout.byline.bounds[1] < layout.byline.bounds[3] <= layout.region[3]
    composition_center = (layout.quotation.bounds[1] + layout.byline.bounds[3]) / 2
    region_center = (layout.region[1] + layout.region[3]) / 2
    assert abs(composition_center - region_center) <= 1
    if style == "centered":
        byline_center = (layout.byline.bounds[0] + layout.byline.bounds[2]) / 2
        region_horizontal_center = (layout.region[0] + layout.region[2]) / 2
        assert abs(byline_center - region_horizontal_center) <= 1
    else:
        assert layout.byline.bounds[2] == layout.region[2]


def test_unrevealed_byline_fields_use_deterministic_pixel_distortion(resolved_font: ResolvedFont) -> None:
    background = Image.new("RGB", (600, 400), "#f8f6f0")
    layout = layout_composition(
        LiteraryComposition("The quotation remains fixed.", source="A Clearly Readable Source", attribution="A Person"),
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        background.size,
        24,
        48,
        "centered",
    )
    assert layout.byline is not None
    assert layout.byline.source is not None
    assert layout.byline.attribution is not None
    stages = (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )
    images = render_reveal_stages(background, resolved_font, layout, stages)
    repeated_images = render_reveal_stages(
        background,
        resolved_font,
        layout,
        stages,
        concealment="pixel-distortion",
    )
    source_bounds = layout.byline.source.bounds
    attribution_bounds = layout.byline.attribution.bounds
    background_pixel = background.getpixel((0, 0))

    for field in (layout.byline.source, layout.byline.attribution):
        distorted = images[0].crop(field.bounds)
        assert distorted.getbbox() is not None
        assert distorted.getextrema()[0][0] < background_pixel[0]
        assert distorted.getextrema()[0][0] > 20
    assert images[0].crop(source_bounds).tobytes() != images[2].crop(source_bounds).tobytes()
    assert images[0].crop(attribution_bounds).tobytes() != images[2].crop(attribution_bounds).tobytes()
    assert all(first.tobytes() == second.tobytes() for first, second in zip(images, repeated_images, strict=True))

    for region in (layout.byline.prefix.bounds, layout.byline.separator.bounds):
        assert images[0].crop(region).tobytes() == images[1].crop(region).tobytes()
        assert images[1].crop(region).tobytes() == images[2].crop(region).tobytes()
    for bounds in (layout.quotation.bounds, layout.byline.prefix.bounds, layout.byline.separator.bounds):
        assert images[0].crop(bounds).tobytes() == images[1].crop(bounds).tobytes()
        assert images[1].crop(bounds).tobytes() == images[2].crop(bounds).tobytes()

    changed_0_to_1 = ImageChops.difference(images[0], images[1]).getbbox()
    changed_1_to_2 = ImageChops.difference(images[1], images[2]).getbbox()
    assert changed_0_to_1 is not None
    assert changed_1_to_2 is not None
    assert source_bounds[0] <= changed_0_to_1[0] < changed_0_to_1[2] <= source_bounds[2]
    assert source_bounds[1] <= changed_0_to_1[1] < changed_0_to_1[3] <= source_bounds[3]
    assert attribution_bounds[0] <= changed_1_to_2[0] < changed_1_to_2[2] <= attribution_bounds[2]
    assert attribution_bounds[1] <= changed_1_to_2[1] < changed_1_to_2[3] <= attribution_bounds[3]
    outside_bounds = (
        (0, 0, source_bounds[0], background.height),
        (source_bounds[2], 0, background.width, background.height),
        (source_bounds[0], 0, source_bounds[2], source_bounds[1]),
        (source_bounds[0], source_bounds[3], source_bounds[2], background.height),
    )
    for bounds in outside_bounds:
        assert ImageChops.difference(images[0], images[1]).crop(bounds).getbbox() is None


def test_byline_gap_default_and_explicit_factor_are_fitted_and_centered(resolved_font: ResolvedFont) -> None:
    composition = LiteraryComposition(
        "A long quotation whose paragraphs make the available vertical space matter.",
        source="A Source",
        attribution="An Author",
    )
    region = PresentationRegion(0.1, 0.1, 0.8, 0.50)
    image_size = (600, 400)
    default = layout_composition(composition, resolved_font, region, image_size, 14, 54, "centered")
    explicit = layout_composition(
        composition,
        resolved_font,
        region,
        image_size,
        14,
        54,
        "centered",
        byline_gap_factor=0.55,
    )

    assert default.byline is not None
    gap = default.byline.bounds[1] - default.quotation.bounds[3]
    assert default.byline_gap == round(default.quotation.font_size * 1.20)
    assert gap == default.byline_gap
    assert explicit.byline is not None
    assert explicit.byline_gap == round(explicit.quotation.font_size * 0.55)
    assert explicit.byline.bounds[1] - explicit.quotation.bounds[3] == explicit.byline_gap
    assert default.quotation.font_size < explicit.quotation.font_size
    for layout in (default, explicit):
        composition_center = (layout.quotation.bounds[1] + layout.byline.bounds[3]) / 2
        region_center = (layout.region[1] + layout.region[3]) / 2
        assert abs(composition_center - region_center) <= 1


@pytest.mark.parametrize("factor", [-1, float("nan"), float("inf"), float("-inf"), True, "1.2", None])
def test_invalid_byline_gap_factors_are_rejected(resolved_font: ResolvedFont, factor: object) -> None:
    with pytest.raises(QuotationRenderError, match="byline_gap_factor"):
        layout_composition(
            LiteraryComposition("A quotation.", source="A Book", attribution="An Author"),
            resolved_font,
            PresentationRegion(0.1, 0.1, 0.8, 0.8),
            (400, 300),
            16,
            42,
            "centered",
            byline_gap_factor=factor,  # type: ignore[arg-type]
        )


def test_zero_byline_gap_is_valid_and_no_byline_reserves_no_gap(resolved_font: ResolvedFont) -> None:
    region = PresentationRegion(0.1, 0.1, 0.8, 0.8)
    background_size = (400, 300)
    with_byline = layout_composition(
        LiteraryComposition("A quotation.", source="A Source"),
        resolved_font,
        region,
        background_size,
        18,
        42,
        "centered",
        byline_gap_factor=0,
    )
    without_byline = layout_composition(
        LiteraryComposition("A quotation."),
        resolved_font,
        region,
        background_size,
        18,
        42,
        "centered",
        byline_gap_factor=1.20,
    )
    assert with_byline.byline is not None and with_byline.byline_gap == 0
    assert with_byline.byline.bounds[1] - with_byline.quotation.bounds[3] == 0
    assert without_byline.byline is None
    assert without_byline.byline_gap == 0


@pytest.mark.parametrize("mode", ["1", "L", "RGB", "RGBA"])
def test_concealment_modes_preserve_attribution_tone_and_field_bounds(
    resolved_font: ResolvedFont,
    mode: str,
) -> None:
    background_color = 255 if mode in {"1", "L"} else ((248, 246, 240) if mode == "RGB" else (248, 246, 240, 255))
    background = Image.new(mode, (600, 400), background_color)
    layout = layout_composition(
        LiteraryComposition("A quotation.", attribution="An Author"),
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        background.size,
        20,
        48,
        "centered",
    )
    assert layout.byline is not None and layout.byline.attribution is not None
    field = layout.byline.attribution
    stages = (CompositionVisibility(), CompositionVisibility(attribution=True))

    images = render_reveal_stages(background, resolved_font, layout, stages)
    assert all(image.mode == mode for image in images)
    difference = ImageChops.difference(images[0], images[1]).convert("RGB").getbbox()
    assert difference is not None
    assert field.bounds[0] <= difference[0] < difference[2] <= field.bounds[2]
    assert field.bounds[1] <= difference[1] < difference[3] <= field.bounds[3]

    if mode in {"L", "RGB", "RGBA"}:
        revealed = images[1].crop(field.bounds).convert("RGB")
        minima = tuple(channel[0] for channel in revealed.getextrema())
        assert min(minima) >= 40
        assert max(minima) < 100


@pytest.mark.parametrize("concealment", ["glyph-blur", "", None, True])
def test_unsupported_concealment_is_rejected(resolved_font: ResolvedFont, concealment: object) -> None:
    layout = layout_composition(
        LiteraryComposition("A quotation.", source="A source"),
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        (400, 300),
        18,
        32,
        "centered",
    )
    with pytest.raises(QuotationRenderError, match="concealment must be 'pixel-distortion'"):
        render_reveal_stages(
            Image.new("RGB", layout.image_size, "white"),
            resolved_font,
            layout,
            (CompositionVisibility(),),
            concealment=concealment,  # type: ignore[arg-type]
        )


def test_pixel_distortion_adds_spatial_noise_and_breaks_glyph_cells(resolved_font: ResolvedFont) -> None:
    background = Image.new("RGB", (600, 400), "white")
    layout = layout_composition(
        LiteraryComposition("A quotation.", attribution="An Author"),
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        background.size,
        20,
        48,
        "centered",
    )
    assert layout.byline is not None and layout.byline.attribution is not None
    field = layout.byline.attribution
    concealed = render_reveal_stages(background, resolved_font, layout, (CompositionVisibility(),))[0]
    concealed_crop = concealed.crop(field.bounds).convert("L")

    original_glyphs = Image.new("L", concealed_crop.size, 0)
    draw = ImageDraw.Draw(original_glyphs)
    pillow_font = ImageFont.truetype(BytesIO(resolved_font.data), size=field.font_size)
    x, y = field.positions[0]
    left, top, _, _ = field.bounds
    draw.text((x - left, y - top), field.text, font=pillow_font, fill=255)

    original_values = original_glyphs.get_flattened_data()
    concealed_values = concealed_crop.get_flattened_data()
    added_cells = sum(
        original < 16 and concealed < 200 for original, concealed in zip(original_values, concealed_values)
    )
    disrupted_cells = sum(
        original > 128 and concealed > 200 for original, concealed in zip(original_values, concealed_values)
    )
    assert added_cells > 0
    assert disrupted_cells > 0


def test_reveal_stage_inputs_must_be_cumulative_and_present(resolved_font: ResolvedFont) -> None:
    layout = layout_composition(
        LiteraryComposition("A quotation.", source="A source"),
        resolved_font,
        PresentationRegion(0.1, 0.1, 0.8, 0.8),
        (400, 300),
        18,
        32,
        "centered",
    )
    background = Image.new("RGB", layout.image_size, "white")

    with pytest.raises(QuotationRenderError, match="cumulative"):
        render_reveal_stages(
            background,
            resolved_font,
            layout,
            (CompositionVisibility(source=True), CompositionVisibility()),
        )
    with pytest.raises(QuotationRenderError, match="absent"):
        render_reveal_stages(
            background,
            resolved_font,
            layout,
            (CompositionVisibility(source=True, attribution=True),),
        )
    with pytest.raises(QuotationRenderError, match="quotation must be visible"):
        render_reveal_stages(
            background,
            resolved_font,
            layout,
            (CompositionVisibility(quotation=False),),
        )


def test_secondary_fields_remain_subordinate_at_smallest_supported_size(resolved_font: ResolvedFont) -> None:
    with pytest.raises(QuotationRenderError, match="minimum quotation font size 1"):
        layout_composition(
            LiteraryComposition("Q", source="Source"),
            resolved_font,
            PresentationRegion(0, 0, 1, 1),
            (100, 100),
            1,
            1,
            "centered",
        )


@pytest.mark.parametrize(
    ("region", "size_bounds", "image_size"),
    [
        (PresentationRegion(-0.1, 0, 0.5, 0.5), (10, 20), (100, 100)),
        (PresentationRegion(0.8, 0.8, 0.3, 0.3), (10, 20), (100, 100)),
        (PresentationRegion(0, 0, 1, 1), (0, 20), (100, 100)),
        (PresentationRegion(0, 0, 1, 1), (20, 10), (100, 100)),
        (PresentationRegion(0, 0, 1, 1), (10, 20), (100, 0)),
    ],
)
def test_invalid_rendering_inputs_are_rejected(
    resolved_font: ResolvedFont,
    region: PresentationRegion,
    size_bounds: tuple[int, int],
    image_size: tuple[int, int],
) -> None:
    with pytest.raises(QuotationRenderError):
        layout_composition(
            LiteraryComposition("A quotation."), resolved_font, region, image_size, *size_bounds, "centered"
        )


def test_invalid_font_and_mismatched_background_are_rejected(resolved_font: ResolvedFont) -> None:
    bad_font = ResolvedFont("broken", b"not a font")
    with pytest.raises(QuotationRenderError, match="cannot be loaded"):
        make_layout("A quotation.", bad_font)

    layout = make_layout("A quotation.", resolved_font)
    with pytest.raises(QuotationRenderError, match="dimensions"):
        render_reveal_stages(Image.new("RGB", (10, 10)), resolved_font, layout, (CompositionVisibility(),))


def test_empty_text_non_image_and_unsupported_mode_are_rejected(resolved_font: ResolvedFont) -> None:
    with pytest.raises(QuotationRenderError, match="nonempty"):
        make_layout("", resolved_font)

    layout = make_layout("A quotation.", resolved_font)
    with pytest.raises(QuotationRenderError, match="Pillow image"):
        render_reveal_stages(object(), resolved_font, layout, (CompositionVisibility(),))  # type: ignore[arg-type]
    with pytest.raises(QuotationRenderError, match="mode"):
        render_reveal_stages(Image.new("P", layout.image_size), resolved_font, layout, (CompositionVisibility(),))
