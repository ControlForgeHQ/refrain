from __future__ import annotations

import logging
import os
from datetime import date, time
from pathlib import Path

import pytest
import yaml

from refrain import (
    ContentLibraryError,
    EligibilityRule,
    RevealOverrides,
    build_eligible_quotation_pool,
    load_content_library,
    normalize_quotation,
)
from refrain import content as content_module


def entry_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {"id": "example-entry", "quotations": ["A sample quotation."]}
    data.update(overrides)
    return data


def write_entry(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def diagnostics_for(directory: Path) -> tuple[str, ...]:
    with pytest.raises(ContentLibraryError) as error:
        load_content_library(directory)
    return tuple(str(diagnostic) for diagnostic in error.value.diagnostics)


def test_loads_multiple_files_and_nested_directories(tmp_path: Path, caplog) -> None:
    write_entry(
        tmp_path / "z-entry.yaml",
        entry_data(
            id="z-entry",
            quotations=["First candidate.", "Second candidate."],
            source="A source",
            attribution="An author",
            priority=-3,
        ),
    )
    write_entry(tmp_path / "nested" / "a-entry.yml", entry_data(id="a-entry"))

    with caplog.at_level(logging.INFO):
        entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["a-entry", "z-entry"]
    assert entries[0].source is None
    assert entries[0].attribution is None
    assert entries[0].priority == 0
    assert entries[0].font is None
    assert entries[0].background is None
    assert entries[0].decoration is None
    assert entries[0].presentation_style == "centered"
    assert entries[0].eligibility == (EligibilityRule(ordinary=True),)
    assert entries[0].reveal == RevealOverrides()
    assert entries[0].font_faces == {}
    assert entries[0].text_color is None
    assert entries[0].decoration_color is None
    assert entries[0].actions == ()
    assert entries[1].priority == -3
    assert [quotation.text for quotation in entries[1].quotations] == ["First candidate.", "Second candidate."]
    assert all(entry.file is not None for entry in entries)
    assert not [record for record in caplog.records if record.levelno >= logging.INFO]


def test_actions_default_to_empty_and_preserve_order_duplicates_and_opaque_payloads(tmp_path: Path, caplog) -> None:
    payloads = (
        "",
        "  leading whitespace\n\ntrailing whitespace \n",
        '{"opaque": ["json", 1]}',
        "key: [yaml, opaque]",
        "<opaque>xml</opaque>",
        "AAEC/w==",
    )
    actions = [
        {"type": "future-Action_2", "visibility": ["private"], "payload": payloads[0]},
        {"type": "same", "visibility": ["public", "private"], "payload": payloads[1]},
        {"type": "same", "visibility": ["public", "private"], "payload": payloads[1]},
        *(
            {"type": f"opaque-{index}", "visibility": ["public"], "payload": payload}
            for index, payload in enumerate(payloads[2:], start=2)
        ),
    ]
    write_entry(tmp_path / "empty.yaml", entry_data(id="empty"))
    write_entry(tmp_path / "actions.yaml", entry_data(id="actions", actions=actions))

    entries = load_content_library(tmp_path)
    empty = next(item for item in entries if item.id == "empty")
    entry = next(item for item in entries if item.id == "actions")

    assert empty.actions == ()
    assert isinstance(entry.actions, tuple)
    assert [(action.type, action.visibility, action.payload) for action in entry.actions] == [
        (action["type"], tuple(action["visibility"]), action["payload"]) for action in actions
    ]
    assert entry.actions[1] == entry.actions[2]
    assert entry.actions[1].payload == payloads[1]
    with pytest.raises(AttributeError):
        entry.actions[0].payload = "changed"
    assert "actions" not in caplog.text


@pytest.mark.parametrize("visibility", [["public"], ["private"], ["public", "private"], ["private", "public"]])
def test_actions_accept_explicit_visibility_audiences(tmp_path: Path, visibility: list[str]) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(actions=[{"type": "unknown-but-valid", "visibility": visibility}]),
    )

    action = load_content_library(tmp_path)[0].actions[0]

    assert action.type == "unknown-but-valid"
    assert action.visibility == tuple(visibility)
    assert action.payload == ""


@pytest.mark.parametrize(
    "action",
    [
        None,
        [],
        {"visibility": ["public"]},
        {"type": "play"},
        {"type": "", "visibility": ["private"]},
        {"type": "bad type", "visibility": ["private"]},
        {"type": "é", "visibility": ["private"]},
        {"type": "play", "visibility": []},
        {"type": "play", "visibility": "private"},
        {"type": "play", "visibility": None},
        {"type": "play", "visibility": ["public", "public"]},
        {"type": "play", "visibility": ["private", "private"]},
        {"type": "play", "visibility": ["public", "unknown"]},
        {"type": "play", "visibility": ["unknown"]},
        {"type": "play", "visibility": ["public"], "payload": None},
        {"type": "play", "visibility": ["public"], "payload": {"opaque": "mapping"}},
        {"type": "play", "visibility": ["public"], "payload": ["opaque", "sequence"]},
        {"type": "play", "visibility": ["public"], "extra": "unsupported"},
    ],
)
def test_malformed_actions_are_dropped_without_rejecting_entry(tmp_path: Path, caplog, action: object) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(actions=[action, {"type": "retained", "visibility": ["private"]}]),
    )

    entries = load_content_library(tmp_path)

    assert len(entries) == 1
    assert [item.type for item in entries[0].actions] == ["retained"]
    pool = build_eligible_quotation_pool(entries, date(2026, 11, 5))
    assert len(pool.candidates) == 1
    assert "entry.yaml: actions[0]" in caplog.text
    assert "entry is excluded" not in caplog.text


@pytest.mark.parametrize("actions", [None, "not a sequence", {"type": "play", "visibility": ["private"]}])
def test_malformed_action_collection_warns_and_keeps_entry_without_actions(
    tmp_path: Path, caplog, actions: object
) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(actions=actions))

    entry = load_content_library(tmp_path)[0]

    assert entry.actions == ()
    assert "entry.yaml: actions:" in caplog.text


@pytest.mark.parametrize("payload", ["a" * 10_240, "a" * 10_238 + "é"])
def test_action_payload_at_utf8_byte_limit_is_preserved(tmp_path: Path, payload: str) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(actions=[{"type": "within-limit", "visibility": ["public"], "payload": payload}]),
    )

    action = load_content_library(tmp_path)[0].actions[0]

    assert len(action.payload.encode("utf-8")) == 10_240
    assert action.payload == payload


@pytest.mark.parametrize("payload", ["a" * 10_241, "a" * 10_239 + "é"])
def test_action_payload_over_utf8_byte_limit_is_dropped(tmp_path: Path, payload: str, caplog) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(actions=[{"type": "too-large", "visibility": ["public"], "payload": payload}]),
    )

    entry = load_content_library(tmp_path)[0]

    assert entry.actions == ()
    assert "10,240 UTF-8 bytes" in caplog.text


def test_action_limit_counts_valid_items_and_warns_after_first_100(tmp_path: Path, caplog) -> None:
    actions = [{"type": f"action-{index}", "visibility": ["private"]} for index in range(99)]
    actions.extend(
        [
            {"type": "", "visibility": ["private"]},
            {"type": "action-99", "visibility": ["private"]},
            {"type": "ignored", "visibility": ["private"]},
        ]
    )
    write_entry(tmp_path / "entry.yaml", entry_data(actions=actions))

    entry = load_content_library(tmp_path)[0]

    assert len(entry.actions) == 100
    assert entry.actions[-1].type == "action-99"
    assert "first 100 valid actions are ignored" in caplog.text
    assert "actions[99]" in caplog.text


def test_exactly_100_valid_actions_do_not_warn(tmp_path: Path, caplog) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(actions=[{"type": f"action-{index}", "visibility": ["public"]} for index in range(100)]),
    )

    entry = load_content_library(tmp_path)[0]

    assert len(entry.actions) == 100
    assert "actions after" not in caplog.text


def test_role_face_preferences_are_preserved_without_bundle_lookup(tmp_path: Path) -> None:
    preferences = {"quotation": "handwritten", "source": "regular", "attribution": "italic"}
    write_entry(tmp_path / "entry.yaml", entry_data(font_faces=preferences))

    entry = load_content_library(tmp_path)[0]

    assert dict(entry.font_faces) == preferences


@pytest.mark.parametrize(
    ("preference", "expected"),
    [
        ("burnt-orange", ("burnt-orange",)),
        (["black", "unknown", "black"], ("black", "unknown", "black")),
    ],
)
def test_text_color_preferences_are_preserved_without_palette_lookup(
    tmp_path: Path, preference: object, expected: tuple[str, ...]
) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(text_color=preference))

    entry = load_content_library(tmp_path)[0]

    assert entry.text_color == expected


@pytest.mark.parametrize(
    ("preference", "expected"),
    [
        ("burnt-orange", ("burnt-orange",)),
        (["black", "unknown", "black"], ("black", "unknown", "black")),
    ],
)
def test_decoration_color_preferences_are_preserved_without_palette_lookup(
    tmp_path: Path, preference: object, expected: tuple[str, ...]
) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(decoration_color=preference))

    entry = load_content_library(tmp_path)[0]

    assert entry.decoration_color == expected


@pytest.mark.parametrize("field", ["text_color", "decoration_color"])
@pytest.mark.parametrize("preference", [None, [], 1, True, 1.5, {}, {"color": "black"}])
def test_invalid_color_declarations_reject_only_the_affected_entry(
    tmp_path: Path, caplog, field: str, preference: object
) -> None:
    write_entry(tmp_path / "invalid.yaml", entry_data(id="invalid", **{field: preference}))
    write_entry(tmp_path / "valid.yaml", entry_data(id="valid"))

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["valid"]
    assert f"{field}: must be a string or a nonempty sequence" in caplog.text
    assert "this entry is excluded" in caplog.text


@pytest.mark.parametrize("field", ["text_color", "decoration_color"])
@pytest.mark.parametrize("preference", ["", " ", "_black", "bad color", "@", "@bad/pool", "@@pool", "#123456"])
def test_invalid_scalar_color_candidate_is_excluded_without_rejecting_entry(
    tmp_path: Path, caplog, field: str, preference: str
) -> None:
    path = write_entry(tmp_path / "entry.yaml", entry_data(**{field: preference}))

    entry = load_content_library(tmp_path)[0]

    assert getattr(entry, field) == ()
    assert f"{path}: {field}: invalid color candidate {preference!r}; this candidate is excluded" in caplog.text
    assert "entry is excluded" not in caplog.text


@pytest.mark.parametrize("field", ["text_color", "decoration_color"])
@pytest.mark.parametrize(
    ("preference", "expected", "invalid_indices"),
    [
        ([None, "black", "@missing", "#abcdef", "black", 42], ("black", "@missing", "black"), (0, 3, 5)),
        (["valid", False, "@valid", {}, ""], ("valid", "@valid"), (1, 3, 4)),
        ([None, "#000000", "@", []], (), (0, 1, 2, 3)),
    ],
)
def test_color_sequence_recovers_individual_candidates(
    tmp_path: Path,
    caplog,
    field: str,
    preference: list[object],
    expected: tuple[str, ...],
    invalid_indices: tuple[int, ...],
) -> None:
    path = write_entry(tmp_path / "entry.yaml", entry_data(**{field: preference}))
    write_entry(tmp_path / "other.yaml", entry_data(id="other"))

    entry, other = load_content_library(tmp_path)

    assert getattr(entry, field) == expected
    assert getattr(other, field) is None
    assert len(caplog.records) == len(invalid_indices)
    for index in invalid_indices:
        assert f"{path}: {field}[{index}]: invalid color candidate {preference[index]!r}" in caplog.text
    assert "entry is excluded" not in caplog.text


def test_mixed_color_library_reports_candidate_and_entry_exclusions(tmp_path: Path, caplog) -> None:
    invalid = write_entry(tmp_path / "invalid.yaml", entry_data(id="invalid", text_color=[]))
    recoverable = write_entry(
        tmp_path / "recoverable.yaml",
        entry_data(id="recoverable", text_color=["bad color", "black"], decoration_color=["@bad/pool", "@missing"]),
    )
    untouched = write_entry(tmp_path / "untouched.yaml", entry_data(id="untouched"))
    original = {path: path.read_bytes() for path in (invalid, recoverable, untouched)}

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["recoverable", "untouched"]
    assert entries[0].text_color == ("black",)
    assert entries[0].decoration_color == ("@missing",)
    assert entries[1].text_color is None and entries[1].decoration_color is None
    assert f"{invalid}: text_color:" in caplog.text and "this entry is excluded" in caplog.text
    assert f"{recoverable}: text_color[0]:" in caplog.text
    assert f"{recoverable}: decoration_color[0]:" in caplog.text
    assert all(
        "entry is excluded" not in record.message for record in caplog.records if str(recoverable) in record.message
    )
    assert all(path.read_bytes() == contents for path, contents in original.items())


@pytest.mark.parametrize(
    "preferences",
    [
        None,
        [],
        "bad",
        {"byline": "italic"},
        {"quotation": None},
        {"source": ""},
        {"attribution": "bad face"},
        {"quotation": "_italic"},
    ],
)
def test_invalid_role_face_preferences_reject_only_the_affected_entry(
    tmp_path: Path, preferences: object, caplog
) -> None:
    write_entry(tmp_path / "invalid.yaml", entry_data(id="invalid", font_faces=preferences))
    write_entry(tmp_path / "valid.yaml", entry_data(id="valid"))

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["valid"]
    assert any("invalid.yaml: font_faces" in record.message for record in caplog.records)


@pytest.mark.parametrize("background", ["paper-a", "none", "unknown-resource", "Custom background", "Paper-a"])
def test_background_preferences_preserved_without_resource_lookup(tmp_path: Path, background: str, caplog) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(background=background, quotations=["First quotation.", "Second quotation."]),
    )

    entry = load_content_library(tmp_path)[0]
    pool = build_eligible_quotation_pool((entry,), date(2026, 11, 5))

    assert entry.background == background
    assert len(pool.candidates) == 2
    assert all(candidate.entry.background == background for candidate in pool.candidates)
    assert "background" not in caplog.text


@pytest.mark.parametrize("decoration", ["frame-a", "none", "unknown-decoration", "Custom Decoration"])
def test_decoration_preferences_are_preserved_for_every_quotation(tmp_path: Path, decoration: str) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(decoration=decoration, quotations=["First quotation.", "Second quotation."]),
    )

    entry = load_content_library(tmp_path)[0]
    pool = build_eligible_quotation_pool((entry,), date(2026, 11, 5))

    assert entry.decoration == decoration
    assert len(pool.candidates) == 2
    assert all(candidate.entry.decoration == decoration for candidate in pool.candidates)


@pytest.mark.parametrize("decoration", ["", " ", "\t\n", None, 1, False, [], {}])
def test_invalid_decoration_preferences_are_rejected(tmp_path: Path, decoration: object) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(decoration=decoration))

    diagnostics = diagnostics_for(tmp_path)

    assert any(": decoration:" in diagnostic for diagnostic in diagnostics)
    assert any("nonempty, nonblank string" in diagnostic for diagnostic in diagnostics)


@pytest.mark.parametrize("background", ["", " ", "\t\n", None, 1, False, [], {}])
def test_invalid_background_preferences_rejected(tmp_path: Path, background: object) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(background=background))

    diagnostics = diagnostics_for(tmp_path)

    assert any(": background:" in diagnostic for diagnostic in diagnostics)
    assert any("nonempty, nonblank string" in diagnostic for diagnostic in diagnostics)


def test_invalid_background_entry_does_not_exclude_valid_entries(tmp_path: Path, caplog) -> None:
    write_entry(tmp_path / "bad.yaml", entry_data(id="bad", background=None))
    write_entry(tmp_path / "good.yaml", entry_data(id="good", background="unregistered"))

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["good"]
    assert entries[0].background == "unregistered"
    assert "background" in caplog.text


@pytest.mark.parametrize("style", ["centered", "left-aligned"])
def test_explicit_presentation_styles_are_preserved(tmp_path: Path, style: str) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(presentation_style=style))

    entry = load_content_library(tmp_path)[0]

    assert entry.presentation_style == style


def test_presentation_style_is_shared_by_all_quotation_candidates(tmp_path: Path) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(presentation_style="left-aligned", quotations=["First quotation.", "Second quotation."]),
    )

    entry = load_content_library(tmp_path)[0]
    pool = build_eligible_quotation_pool((entry,), date(2026, 10, 26))

    assert len(pool.candidates) == 2
    assert all(candidate.entry is entry for candidate in pool.candidates)
    assert all(candidate.entry.presentation_style == "left-aligned" for candidate in pool.candidates)


@pytest.mark.parametrize("style", ["prose", "unknown", "Centered", "", None, 1, False])
def test_invalid_presentation_styles_are_rejected(tmp_path: Path, style: object) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(presentation_style=style))

    diagnostics = diagnostics_for(tmp_path)

    assert any(": presentation_style:" in diagnostic for diagnostic in diagnostics)
    assert any("centered" in diagnostic and "left-aligned" in diagnostic for diagnostic in diagnostics)


def test_entry_identity_does_not_depend_on_file_path(tmp_path: Path) -> None:
    entry_file = write_entry(tmp_path / "first" / "entry.yaml", entry_data(id="stable-entry"))
    first = load_content_library(tmp_path)[0]
    entry_file.rename(tmp_path / "second.yaml")
    second = load_content_library(tmp_path)[0]

    assert first.id == second.id == "stable-entry"


def test_duplicate_identifiers_exclude_all_conflicting_entries(tmp_path: Path) -> None:
    first = write_entry(tmp_path / "first.yaml", entry_data())
    second = write_entry(tmp_path / "nested" / "second.yaml", entry_data())

    diagnostics = diagnostics_for(tmp_path)

    duplicate_diagnostics = [diagnostic for diagnostic in diagnostics if "conflicting duplicate" in diagnostic]
    assert len(duplicate_diagnostics) == 2
    assert any(str(first) in diagnostic and str(second) in diagnostic for diagnostic in duplicate_diagnostics)
    assert all("id" in diagnostic and "excluded" in diagnostic for diagnostic in duplicate_diagnostics)


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"quotations": ["A quotation."]}, "id"),
        ({"id": "bad id", "quotations": ["A quotation."]}, "id"),
        ({"id": "valid-id"}, "quotations"),
        ({"id": "valid-id", "quotations": []}, "quotations"),
        ({"id": "valid-id", "quotations": ["A quotation."], "unexpected": 1}, "unexpected"),
    ],
)
def test_required_identifier_and_unknown_fields_are_validated(
    tmp_path: Path, data: dict[str, object], field: str
) -> None:
    write_entry(tmp_path / "entry.yaml", data)

    diagnostics = diagnostics_for(tmp_path)

    assert any(f": {field}:" in diagnostic for diagnostic in diagnostics)
    assert any("entry.yaml" in diagnostic for diagnostic in diagnostics)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", ""),
        ("source", " \t\n"),
        ("source", 12),
        ("source", None),
        ("attribution", ""),
        ("attribution", "\t "),
        ("attribution", None),
        ("attribution", 12),
        ("font", ""),
        ("font", " \t\n"),
        ("font", None),
        ("font", False),
        ("font", []),
        ("font", "bad font"),
        ("font", "font/path"),
        ("font", "@"),
        ("font", "@bad pool"),
        ("font", "none"),
        ("priority", True),
        ("priority", 1.5),
        ("quotations", "not a sequence"),
        ("quotations", [None]),
        ("quotations", [[]]),
    ],
)
def test_invalid_field_types_and_empty_values_are_rejected(tmp_path: Path, field: str, value: object) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(**{field: value}))

    diagnostics = diagnostics_for(tmp_path)

    assert any(f": {field}" in diagnostic for diagnostic in diagnostics)


def test_signed_integer_priority_and_unregistered_font_are_preserved(tmp_path: Path) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(priority=-(2**80), font="not-installed-here"))

    entry = load_content_library(tmp_path)[0]

    assert entry.priority == -(2**80)
    assert entry.font == "not-installed-here"


@pytest.mark.parametrize("font", ["test-font", "@literary", "@default", "@builtin"])
def test_syntactically_valid_font_preferences_are_preserved(tmp_path: Path, font: str) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(font=font))

    entry = load_content_library(tmp_path)[0]

    assert entry.font == font


def test_nonblank_optional_text_is_preserved_verbatim(tmp_path: Path) -> None:
    source = "  A source \t with internal whitespace.  "
    attribution = "\n  An author\t "
    write_entry(tmp_path / "entry.yaml", entry_data(source=source, attribution=attribution, font="missing-font"))

    entry = load_content_library(tmp_path)[0]

    assert entry.source == source
    assert entry.attribution == attribution
    assert entry.font == "missing-font"


def test_invalid_metadata_and_font_entries_are_excluded_independently(tmp_path: Path, caplog) -> None:
    source = "  A valid source \t "
    attribution = "\nA valid author "
    write_entry(
        tmp_path / "valid.yaml",
        entry_data(id="valid", source=source, attribution=attribution, font="unavailable-font"),
    )
    write_entry(tmp_path / "blank-source.yaml", entry_data(id="blank-source", source=" \t "))
    write_entry(tmp_path / "null-attribution.yaml", entry_data(id="null-attribution", attribution=None))
    write_entry(tmp_path / "reserved-font.yaml", entry_data(id="reserved-font", font="none"))
    write_entry(tmp_path / "malformed-font.yaml", entry_data(id="malformed-font", font="@invalid pool"))

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["valid"]
    assert entries[0].source == source
    assert entries[0].attribution == attribution
    assert entries[0].font == "unavailable-font"
    for filename, field in (
        ("blank-source.yaml", "source"),
        ("null-attribution.yaml", "attribution"),
        ("reserved-font.yaml", "font"),
        ("malformed-font.yaml", "font"),
    ):
        assert f"{filename}: {field}:" in caplog.text


def test_valid_eligibility_forms_and_leap_dates_are_preserved(tmp_path: Path) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(
            eligibility=[
                {"year": 2024, "month": 2, "day": 29},
                {"month": 2, "day": 29},
                {"day": 31},
                {"month": 12},
                {"ordinary": True},
                {"year": 12000, "month": 2, "day": 29},
            ]
        ),
    )

    entry = load_content_library(tmp_path)[0]

    assert entry.eligibility == (
        EligibilityRule(year=2024, month=2, day=29),
        EligibilityRule(month=2, day=29),
        EligibilityRule(day=31),
        EligibilityRule(month=12),
        EligibilityRule(ordinary=True),
        EligibilityRule(year=12000, month=2, day=29),
    )


@pytest.mark.parametrize(
    "rule",
    [
        {"year": 2024},
        {"year": 2024, "month": 2},
        {"ordinary": True, "month": 2},
        {"month": 2, "day": 30},
        {"year": 2025, "month": 2, "day": 29},
        {"year": 2024, "month": 4, "day": 31},
        {"month": 13},
        {"day": 0},
        {"year": True, "month": 1, "day": 1},
        {"ordinary": False},
        {"week": 1},
    ],
)
def test_invalid_eligibility_rules_are_rejected(tmp_path: Path, rule: dict[str, object]) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(eligibility=[rule]))

    diagnostics = diagnostics_for(tmp_path)

    assert any("eligibility[0]" in diagnostic for diagnostic in diagnostics)


def test_empty_eligibility_sequence_is_rejected(tmp_path: Path) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(eligibility=[]))

    diagnostics = diagnostics_for(tmp_path)

    assert any(": eligibility:" in diagnostic and "at least one rule" in diagnostic for diagnostic in diagnostics)


def test_reveal_overrides_are_preserved_without_configuration_resolution(tmp_path: Path) -> None:
    write_entry(
        tmp_path / "entry.yaml",
        entry_data(reveal={"source": "09:00", "attribution": "23:59"}),
    )

    entry = load_content_library(tmp_path)[0]

    assert entry.reveal == RevealOverrides(source=time.fromisoformat("09:00"), attribution=time.fromisoformat("23:59"))


@pytest.mark.parametrize(
    "reveal",
    [
        "09:00",
        {"source": "9:00"},
        {"source": "24:00"},
        {"attribution": 900},
        {"quotation": "09:00"},
    ],
)
def test_invalid_reveal_override_syntax_is_rejected(tmp_path: Path, reveal: object) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(reveal=reveal))

    diagnostics = diagnostics_for(tmp_path)

    assert any(": reveal" in diagnostic for diagnostic in diagnostics)


@pytest.mark.parametrize("quotation", ["", " \t\r\n"])
def test_empty_and_whitespace_only_quotations_are_rejected(tmp_path: Path, quotation: str) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(quotations=[quotation]))

    diagnostics = diagnostics_for(tmp_path)

    assert any("quotations[0]" in diagnostic and "meaningful text" in diagnostic for diagnostic in diagnostics)


def test_unicode_and_original_multiline_text_are_preserved(tmp_path: Path) -> None:
    original = "Cafe\u0301\tat dawn.\nSecond line."
    write_entry(tmp_path / "entry.yaml", entry_data(quotations=[original]))

    quotation = load_content_library(tmp_path)[0].quotations[0]

    assert quotation.text == original
    assert quotation.identity == "Café at dawn. Second line."
    assert normalize_quotation(" Cafe\u0301\tat dawn.\nSecond line. ") == quotation.identity


@pytest.mark.parametrize(
    "contents",
    [
        "id: [\n",
        "id: one\nid: two\nquotations: ['A quotation.']\n",
        "id: one\nquotations: ['A quotation.']\n---\nid: two\nquotations: ['Another.']\n",
        "id: one\nquotations: !custom ['A quotation.']\n",
        "defaults: &defaults\n  priority: 1\n",
        "id: one\nquotations: ['A quotation.']\nextra: *missing\n",
        "id: one\nquotations: ['A quotation.']\nextra: {<<: {priority: 1}}\n",
        "1: not a string key\n",
        "- not a top-level mapping\n",
    ],
)
def test_malformed_or_unsupported_yaml_is_rejected(tmp_path: Path, contents: str) -> None:
    (tmp_path / "entry.yaml").write_text(contents, encoding="utf-8")

    diagnostics = diagnostics_for(tmp_path)

    assert any("entry.yaml: $" in diagnostic for diagnostic in diagnostics)
    assert any("no valid quotations" in diagnostic for diagnostic in diagnostics)


@pytest.mark.parametrize(
    "scalar",
    [
        "source: 2026-02-30",
        "priority: !!int nope",
        "priority: !!bool nope",
    ],
)
def test_yaml_scalar_constructor_failures_are_reported_and_other_files_validated(tmp_path: Path, scalar: str) -> None:
    (tmp_path / "a-invalid.yaml").write_text(
        f"id: invalid-entry\nquotations:\n  - A quotation.\n{scalar}\n",
        encoding="utf-8",
    )
    (tmp_path / "z-invalid.yaml").write_text("id: invalid id\nquotations: [A quotation.]\n", encoding="utf-8")

    diagnostics = diagnostics_for(tmp_path)

    assert len(diagnostics) == 3
    assert any("a-invalid.yaml: $" in diagnostic and "invalid YAML scalar" in diagnostic for diagnostic in diagnostics)
    assert any("z-invalid.yaml: id:" in diagnostic for diagnostic in diagnostics)


def test_yaml_syntax_diagnostic_includes_line_and_column(tmp_path: Path) -> None:
    (tmp_path / "entry.yaml").write_text("id: valid\nquotations:\n  - [\n", encoding="utf-8")

    diagnostics = diagnostics_for(tmp_path)

    assert any("entry.yaml: $" in diagnostic and "line 4, column 1" in diagnostic for diagnostic in diagnostics)


def test_unreadable_content_file_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry_file = tmp_path / "entry.yaml"
    write_entry(entry_file, entry_data())
    original_read_text = Path.read_text

    def fail_for_entry(path: Path, *args: object, **kwargs: object) -> str:
        if path == entry_file:
            raise PermissionError("access denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_for_entry)

    diagnostics = diagnostics_for(tmp_path)

    assert any("entry.yaml: $" in diagnostic and "access denied" in diagnostic for diagnostic in diagnostics)


def test_inaccessible_directory_during_traversal_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_entry(tmp_path / "available.yaml", entry_data(id="available"))
    blocked_directory = tmp_path / "blocked"

    def walk_with_inaccessible_directory(root: Path, onerror=None):
        yield str(root), ["blocked"], ["available.yaml"]
        if onerror is not None:
            onerror(PermissionError(13, "permission denied", str(blocked_directory)))

    monkeypatch.setattr(content_module.os, "walk", walk_with_inaccessible_directory)

    diagnostics = diagnostics_for(tmp_path)

    assert len(diagnostics) == 1
    assert str(blocked_directory) in diagnostics[0]
    assert ": $: cannot enumerate content directory:" in diagnostics[0]
    assert "permission denied" in diagnostics[0]


def test_directory_enumeration_exception_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked_directory = tmp_path / "blocked"

    def walk_that_raises(root: Path, onerror=None):
        yield str(root), [], []
        raise OSError(5, "enumeration failed", str(blocked_directory))

    monkeypatch.setattr(content_module.os, "walk", walk_that_raises)

    diagnostics = diagnostics_for(tmp_path)

    assert len(diagnostics) == 1
    assert str(blocked_directory) in diagnostics[0]
    assert ": $: cannot enumerate content directory:" in diagnostics[0]
    assert "enumeration failed" in diagnostics[0]


def test_initial_directory_check_exception_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked_directory = tmp_path / "blocked"

    def is_dir_that_raises(path: Path) -> bool:
        if path == blocked_directory:
            raise PermissionError("access denied")
        return False

    monkeypatch.setattr(Path, "is_dir", is_dir_that_raises)

    diagnostics = diagnostics_for(blocked_directory)

    assert len(diagnostics) == 1
    assert f"{blocked_directory}: $: cannot access content directory:" in diagnostics[0]
    assert "access denied" in diagnostics[0]


def test_non_utf8_content_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "entry.yaml").write_bytes(b"id: \xff\n")

    diagnostics = diagnostics_for(tmp_path)

    assert any("entry.yaml: $" in diagnostic and "UTF-8" in diagnostic for diagnostic in diagnostics)


def test_invalid_entries_are_excluded_while_valid_entries_are_retained(tmp_path: Path, caplog) -> None:
    write_entry(tmp_path / "valid.yaml", entry_data(id="valid-entry"))
    nested_invalid_file = tmp_path / "nested" / "invalid.yaml"
    other_invalid_file = tmp_path / "other.yaml"
    write_entry(nested_invalid_file, entry_data(id="invalid id"))
    write_entry(other_invalid_file, entry_data(id="also-invalid", quotations=[""]))

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["valid-entry"]
    assert f"{nested_invalid_file}: id:" in caplog.text
    assert f"{other_invalid_file}: quotations[0]:" in caplog.text
    assert "this entry is excluded" in caplog.text
    assert any(
        record.levelno == logging.WARNING
        and str(other_invalid_file) in record.getMessage()
        and "quotations[0]" in record.getMessage()
        and "excluded" in record.getMessage()
        for record in caplog.records
    )


def test_malformed_yaml_file_does_not_prevent_valid_content(tmp_path: Path, caplog) -> None:
    write_entry(tmp_path / "valid.yaml", entry_data(id="valid-entry"))
    malformed = tmp_path / "broken.yaml"
    malformed.write_text("id: [", encoding="utf-8")

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["valid-entry"]
    assert str(malformed) in caplog.text
    assert "this file is excluded" in caplog.text


def test_unchanged_content_warning_is_repeated_after_file_changes_and_is_rejected_again(tmp_path: Path, caplog) -> None:
    write_entry(tmp_path / "valid.yaml", entry_data(id="valid-entry"))
    broken = tmp_path / "broken.yaml"
    broken_contents = yaml.safe_dump(entry_data(unknown=True), sort_keys=False)
    broken.write_text(broken_contents, encoding="utf-8")
    initial_mtime = broken.stat().st_mtime_ns

    load_content_library(tmp_path)
    first_warning_count = caplog.text.count(str(broken))
    assert first_warning_count == 1

    caplog.clear()
    write_entry(broken, entry_data(id="corrected-entry"))
    load_content_library(tmp_path)
    assert str(broken) not in caplog.text

    caplog.clear()
    broken.write_text(broken_contents, encoding="utf-8")
    broken_stat = broken.stat()
    broken_mtime = max(broken_stat.st_mtime_ns, initial_mtime + 1_000_000_000)
    os.utime(broken, ns=(broken_stat.st_atime_ns, broken_mtime))
    load_content_library(tmp_path)

    assert caplog.text.count(str(broken)) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_identifier_exclusion_is_independent_of_enumeration_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    first = write_entry(tmp_path / "first.yaml", entry_data(id="duplicate"))
    second = write_entry(tmp_path / "second.yaml", entry_data(id="duplicate"))
    unique = write_entry(tmp_path / "unique.yaml", entry_data(id="unique"))
    original_walk = content_module.os.walk

    def reordered_walk(root: Path, onerror=None):
        for directory, directories, filenames in original_walk(root, onerror=onerror):
            yield directory, directories, list(reversed(filenames)) if reverse else filenames

    monkeypatch.setattr(content_module.os, "walk", reordered_walk)

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["unique"]
    assert entries[0].file == unique
    assert first != second


def test_invalid_content_directory_is_reported(tmp_path: Path, caplog) -> None:
    diagnostics = diagnostics_for(tmp_path / "missing")

    assert len(diagnostics) == 1
    assert diagnostics[0].endswith("$: content directory does not exist or is not a directory")
    assert any(
        record.levelno == logging.ERROR
        and str(tmp_path / "missing") in record.getMessage()
        and "content directory" in record.getMessage()
        for record in caplog.records
    )
