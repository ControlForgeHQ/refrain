from __future__ import annotations

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


def test_loads_multiple_files_and_nested_directories(tmp_path: Path) -> None:
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

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["a-entry", "z-entry"]
    assert entries[0].source is None
    assert entries[0].attribution is None
    assert entries[0].priority == 0
    assert entries[0].font is None
    assert entries[0].presentation_style == "centered"
    assert entries[0].eligibility == (EligibilityRule(ordinary=True),)
    assert entries[0].reveal == RevealOverrides()
    assert entries[1].priority == -3
    assert [quotation.text for quotation in entries[1].quotations] == ["First candidate.", "Second candidate."]
    assert all(entry.file is not None for entry in entries)


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
        ("source", 12),
        ("attribution", ""),
        ("font", ""),
        ("font", False),
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


def test_nonempty_optional_text_is_preserved_verbatim(tmp_path: Path) -> None:
    write_entry(tmp_path / "entry.yaml", entry_data(source=" ", attribution="\t", font=" "))

    entry = load_content_library(tmp_path)[0]

    assert entry.source == " "
    assert entry.attribution == "\t"
    assert entry.font == " "


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


def test_malformed_yaml_file_does_not_prevent_valid_content(tmp_path: Path, caplog) -> None:
    write_entry(tmp_path / "valid.yaml", entry_data(id="valid-entry"))
    malformed = tmp_path / "broken.yaml"
    malformed.write_text("id: [", encoding="utf-8")

    entries = load_content_library(tmp_path)

    assert [entry.id for entry in entries] == ["valid-entry"]
    assert str(malformed) in caplog.text
    assert "this file is excluded" in caplog.text


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


def test_invalid_content_directory_is_reported(tmp_path: Path) -> None:
    diagnostics = diagnostics_for(tmp_path / "missing")

    assert len(diagnostics) == 1
    assert diagnostics[0].endswith("$: content directory does not exist or is not a directory")
