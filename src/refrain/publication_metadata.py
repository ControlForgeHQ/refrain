"""Versioned metadata shared by prepared images and completed publications."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

from .content import normalize_quotation
from .geometry import PresentationGeometryError, ResolvedOutputSpecification
from .renderer import CompositionVisibility

PUBLICATION_METADATA_VERSION = 1
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "publication_id",
    "publication_type",
    "published_at",
    "destination_id",
    "output_specification",
    "presentation",
    "reconstruction",
    "actions",
}
_ROLES = {"quotation", "source", "attribution"}
_VISIBILITY_FIELDS = {"quotation", "source", "attribution"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z\Z")
_RFC3339_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class PublicationMetadataError(ValueError):
    """Raised when shared publication metadata is incomplete or inconsistent."""


def content_entry(snapshot: Any) -> dict[str, object]:
    """Return a valid single-quotation content entry for the committed snapshot."""
    entry: dict[str, object] = {
        "id": snapshot.entry_id,
        "quotations": [snapshot.quotation_text],
        "presentation_style": snapshot.presentation_style,
        "reveal": {field: snapshot.reveal_schedule[field] for field in ("source", "attribution")},
    }
    for field in ("source", "attribution"):
        value = getattr(snapshot, field)
        if value is not None:
            entry[field] = value
    for field in ("font", "background", "decoration"):
        value = getattr(snapshot, field)
        if value is not None and _valid_content_resource_preference(value, allow_none=field != "font"):
            entry[field] = value
    for field in ("font_faces",):
        value = dict(getattr(snapshot, field))
        if value:
            entry[field] = value
    for field in ("text_color", "decoration_color"):
        value = getattr(snapshot, field)
        if value is not None and all(_valid_palette_reference(item) for item in value):
            entry[field] = list(value)
    return entry


def action_declarations(snapshot: Any) -> list[dict[str, object]]:
    """Return all committed action declarations without audience filtering."""
    return [
        {"type": action.type, "visibility": list(action.visibility), "payload": action.payload}
        for action in snapshot.actions
    ]


def build_prepared_metadata(
    *,
    selection_revision: int,
    snapshot: Any,
    output_specification: ResolvedOutputSpecification,
    stage_index: int,
    visibility: CompositionVisibility,
    reconstruction: Mapping[str, object],
) -> dict[str, object]:
    """Build the publication-schema document for one prepared output image."""
    document: dict[str, object] = {
        "schema_version": PUBLICATION_METADATA_VERSION,
        "publication_id": None,
        "publication_type": "scheduled",
        "published_at": None,
        "destination_id": None,
        "output_specification": {
            "aspect_ratio": output_specification.aspect_ratio,
            "requested_output_size": list(output_specification.requested_output_size),
        },
        "presentation": {
            "display_date": snapshot.display_date.isoformat(),
            "quotation_identity": snapshot.quotation_identity,
            "selection_revision": selection_revision,
            "reveal_stage_index": stage_index,
            "reveal_schedule": dict(snapshot.reveal_schedule),
            "reveal_stage": {
                "quotation": visibility.quotation,
                "source": visibility.source,
                "attribution": visibility.attribution,
            },
        },
        "reconstruction": dict(reconstruction),
        "actions": action_declarations(snapshot),
    }
    validate_publication_metadata(document, stage="preparation")
    return document


def validate_publication_metadata(document: object, *, stage: str, audience: str | None = None) -> None:
    """Validate the shared metadata shape at preparation or completed-publication stage."""
    if not isinstance(stage, str) or stage not in {"preparation", "completed"}:
        raise ValueError("stage must be 'preparation' or 'completed'")
    if audience is not None and (not isinstance(audience, str) or audience not in {"external", "internal"}):
        raise ValueError("audience must be 'external' or 'internal'")
    if not isinstance(document, dict) or set(document) != _TOP_LEVEL_FIELDS:
        raise PublicationMetadataError("metadata must contain every supported publication field")
    _validate_utf8_strings(document)
    if type(document["schema_version"]) is not int or document["schema_version"] != PUBLICATION_METADATA_VERSION:
        raise PublicationMetadataError("unsupported publication metadata schema version")
    publication_type = document["publication_type"]
    if not isinstance(publication_type, str) or publication_type not in {"scheduled", "transient"}:
        raise PublicationMetadataError("publication_type must be 'scheduled' or 'transient'")
    if stage == "preparation" and publication_type != "scheduled":
        raise PublicationMetadataError("prepared metadata must have publication_type 'scheduled'")
    if stage == "preparation":
        if any(document[field] is not None for field in ("publication_id", "published_at", "destination_id")):
            raise PublicationMetadataError(
                "publication identity, timestamp, and destination must be null at preparation"
            )
    else:
        if not isinstance(document["publication_id"], str) or not document["publication_id"].strip():
            raise PublicationMetadataError("completed metadata requires a publication_id")
        if not isinstance(document["destination_id"], str) or not _IDENTIFIER.fullmatch(document["destination_id"]):
            raise PublicationMetadataError("completed metadata requires a destination_id")
        published_at = document["published_at"]
        if not isinstance(published_at, str):
            raise PublicationMetadataError("completed metadata requires a publication timestamp")
        if not _UTC_TIMESTAMP.fullmatch(published_at):
            raise PublicationMetadataError("published_at must be a UTC RFC-3339 timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(published_at[:-1] + "+00:00")
        except ValueError as error:
            raise PublicationMetadataError("published_at must be a valid UTC RFC-3339 timestamp") from error
        if parsed_timestamp.utcoffset() is None:
            raise PublicationMetadataError("published_at must include a timezone")

    output = document["output_specification"]
    if not isinstance(output, dict) or set(output) != {"aspect_ratio", "requested_output_size"}:
        raise PublicationMetadataError("output_specification is required and must be complete")
    if (
        not isinstance(output["aspect_ratio"], str)
        or not isinstance(output["requested_output_size"], list)
        or len(output["requested_output_size"]) != 2
        or any(type(value) is not int or value <= 0 for value in output["requested_output_size"])
    ):
        raise PublicationMetadataError("output_specification has invalid values")
    try:
        ResolvedOutputSpecification(output["aspect_ratio"], tuple(output["requested_output_size"]))
    except PresentationGeometryError as error:
        raise PublicationMetadataError("output_specification is unsupported") from error

    presentation = document["presentation"]
    reconstruction = document["reconstruction"]
    if stage == "completed" and publication_type == "transient":
        if presentation is not None or reconstruction is not None or document["actions"] != []:
            raise PublicationMetadataError(
                "transient metadata requires null presentation and reconstruction and no actions"
            )
        return
    if not isinstance(presentation, dict) or set(presentation) != {
        "display_date",
        "quotation_identity",
        "selection_revision",
        "reveal_stage_index",
        "reveal_schedule",
        "reveal_stage",
    }:
        raise PublicationMetadataError("scheduled presentation context is required and must be complete")
    if not isinstance(presentation["display_date"], str) or not _DATE.fullmatch(presentation["display_date"]):
        raise PublicationMetadataError("display_date must be an ISO date")
    try:
        date.fromisoformat(presentation["display_date"])
    except ValueError as error:
        raise PublicationMetadataError("display_date must be an ISO date") from error
    if not isinstance(presentation["quotation_identity"], str) or not presentation["quotation_identity"].strip():
        raise PublicationMetadataError("quotation_identity must identify the committed quotation")
    if type(presentation["selection_revision"]) is not int or presentation["selection_revision"] <= 0:
        raise PublicationMetadataError("selection_revision must be a positive integer")
    if type(presentation["reveal_stage_index"]) is not int or presentation["reveal_stage_index"] < 0:
        raise PublicationMetadataError("reveal_stage_index must be a nonnegative integer")
    reveal_schedule = presentation["reveal_schedule"]
    if (
        not isinstance(reveal_schedule, dict)
        or set(reveal_schedule) != _VISIBILITY_FIELDS
        or any(not isinstance(value, str) or not _TIME.fullmatch(value) for value in reveal_schedule.values())
    ):
        raise PublicationMetadataError("reveal_schedule must contain all effective reveal times")
    reveal = presentation["reveal_stage"]
    if (
        not isinstance(reveal, dict)
        or set(reveal) != _VISIBILITY_FIELDS
        or any(type(value) is not bool for value in reveal.values())
    ):
        raise PublicationMetadataError("reveal_stage must contain all visibility flags")
    if not isinstance(reconstruction, dict) or set(reconstruction) != {
        "content_entry",
        "presentation_style",
        "background",
        "decoration",
        "fonts",
        "colors",
        "qr",
        "font_size_range",
        "insets",
    }:
        raise PublicationMetadataError("reconstruction data is missing required fields")
    entry = reconstruction["content_entry"]
    entry_fields = {
        "id",
        "quotations",
        "source",
        "attribution",
        "priority",
        "font",
        "font_faces",
        "background",
        "decoration",
        "text_color",
        "decoration_color",
        "presentation_style",
        "eligibility",
        "reveal",
    }
    if (
        not isinstance(entry, dict)
        or not {"id", "quotations", "presentation_style", "reveal"} <= set(entry)
        or set(entry) - entry_fields
        or not isinstance(entry.get("id"), str)
        or not _IDENTIFIER.fullmatch(entry["id"])
    ):
        raise PublicationMetadataError("reconstruction requires a valid single-quotation content entry")
    if (
        not isinstance(entry.get("quotations"), list)
        or len(entry["quotations"]) != 1
        or not isinstance(entry["quotations"][0], str)
        or not entry["quotations"][0].strip()
    ):
        raise PublicationMetadataError("reconstruction content_entry must contain exactly one quotation")
    if presentation["quotation_identity"] != normalize_quotation(entry["quotations"][0]):
        raise PublicationMetadataError("quotation_identity must match the committed quotation")
    if (
        not isinstance(reconstruction["presentation_style"], str)
        or reconstruction["presentation_style"] not in {"centered", "left-aligned"}
        or entry["presentation_style"] != reconstruction["presentation_style"]
    ):
        raise PublicationMetadataError("presentation_style is invalid")
    for field in ("source", "attribution", "font", "background", "decoration"):
        if field in entry and (not isinstance(entry[field], str) or not entry[field].strip()):
            raise PublicationMetadataError(f"content_entry.{field} must be a nonempty string when present")
    if "font" in entry and not _valid_content_resource_preference(entry["font"], allow_none=False):
        raise PublicationMetadataError("content_entry.font must use a stable identifier or pool reference")
    for field in ("background", "decoration"):
        if field in entry and not _valid_content_resource_preference(entry[field], allow_none=True):
            raise PublicationMetadataError(f"content_entry.{field} must use a stable identifier or pool reference")
    reveal_schedule = entry["reveal"]
    if (
        not isinstance(reveal_schedule, dict)
        or set(reveal_schedule) != {"source", "attribution"}
        or any(not isinstance(value, str) or not _TIME.fullmatch(value) for value in reveal_schedule.values())
    ):
        raise PublicationMetadataError("content_entry.reveal is invalid")
    if any(reveal_schedule[field] != presentation["reveal_schedule"][field] for field in ("source", "attribution")):
        raise PublicationMetadataError("content_entry.reveal must match the effective reveal schedule")
    if "priority" in entry and (type(entry["priority"]) is not int):
        raise PublicationMetadataError("content_entry.priority must be an integer")
    if "eligibility" in entry and (
        not isinstance(entry["eligibility"], list)
        or not entry["eligibility"]
        or any(not _valid_eligibility_rule(rule) for rule in entry["eligibility"])
    ):
        raise PublicationMetadataError("content_entry.eligibility is invalid")
    if "font_faces" in entry and (
        not isinstance(entry["font_faces"], dict)
        or set(entry["font_faces"]) - _ROLES
        or any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) for value in entry["font_faces"].values())
    ):
        raise PublicationMetadataError("content_entry.font_faces is invalid")
    for field in ("text_color", "decoration_color"):
        if field in entry:
            values = entry[field] if isinstance(entry[field], list) else [entry[field]]
            if not values or any(not _valid_palette_reference(value) for value in values):
                raise PublicationMetadataError(f"content_entry.{field} is invalid")
    for field in ("background", "decoration"):
        if (
            not isinstance(reconstruction[field], str)
            or not reconstruction[field]
            or (reconstruction[field] != "none" and not _IDENTIFIER.fullmatch(reconstruction[field]))
        ):
            raise PublicationMetadataError(f"{field} must contain the actual resolved resource identifier")
    fonts = reconstruction["fonts"]
    if (
        not isinstance(fonts, dict)
        or set(fonts) != {"bundle", "faces"}
        or not isinstance(fonts["bundle"], str)
        or not _IDENTIFIER.fullmatch(fonts["bundle"])
        or not isinstance(fonts["faces"], dict)
        or set(fonts["faces"]) != _ROLES
        or any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) for value in fonts["faces"].values())
    ):
        raise PublicationMetadataError("resolved font bundle and role-specific faces are required")
    colors = reconstruction["colors"]
    if (
        not isinstance(colors, dict)
        or set(colors) != {"text", "decoration"}
        or not isinstance(colors["text"], str)
        or not _IDENTIFIER.fullmatch(colors["text"])
        or (
            colors["decoration"] is not None
            and (not isinstance(colors["decoration"], str) or not _IDENTIFIER.fullmatch(colors["decoration"]))
        )
    ):
        raise PublicationMetadataError("resolved palette identifiers are invalid")
    qr = reconstruction["qr"]
    if (
        not isinstance(qr, dict)
        or set(qr) != {"enabled", "available"}
        or any(type(value) is not bool for value in qr.values())
    ):
        raise PublicationMetadataError("effective QR configuration and availability are required")
    font_range = reconstruction["font_size_range"]
    if (
        not isinstance(font_range, dict)
        or set(font_range) != {"minimum", "maximum"}
        or any(type(value) is not int or value <= 0 for value in font_range.values())
        or font_range["minimum"] > font_range["maximum"]
    ):
        raise PublicationMetadataError("font_size_range is invalid")
    insets = reconstruction["insets"]
    if (
        not isinstance(insets, dict)
        or set(insets) != {"left", "right", "top", "bottom"}
        or any(type(value) is not int or value < 0 for value in insets.values())
    ):
        raise PublicationMetadataError("effective insets are invalid")

    actions = document["actions"]
    if not isinstance(actions, list):
        raise PublicationMetadataError("actions must be an ordered sequence")
    if len(actions) > 100:
        raise PublicationMetadataError("actions must not exceed the content-entry limit")
    for action in actions:
        if not isinstance(action, dict) or set(action) != {"type", "visibility", "payload"}:
            raise PublicationMetadataError("each action must preserve its complete content-entry declaration")
        if not isinstance(action["type"], str) or not _IDENTIFIER.fullmatch(action["type"]):
            raise PublicationMetadataError("action type must be a nonempty string")
        visibility = action["visibility"]
        payload = action["payload"]
        if (
            not isinstance(visibility, list)
            or not visibility
            or any(not isinstance(value, str) or value not in {"external", "internal"} for value in visibility)
            or len(set(visibility)) != len(visibility)
            or not isinstance(payload, str)
            or len(payload.encode("utf-8")) > 10_240
        ):
            raise PublicationMetadataError("action visibility and payload are invalid")
        if stage == "completed" and audience is not None and audience not in visibility:
            raise PublicationMetadataError(f"actions contain an item not visible to the {audience} audience")


def finalize_publication_metadata(
    prepared_metadata: Mapping[str, object] | None = None,
    *,
    publication_type: str,
    publication_id: str,
    published_at: datetime | str,
    destination_id: str,
    output_specification: ResolvedOutputSpecification,
    audience: str | None = None,
    reveal_stage_index: int | None = None,
) -> dict[str, object]:
    """Return validated, destination-specific metadata for one publication event."""
    if not isinstance(publication_type, str) or publication_type not in {"scheduled", "transient"}:
        raise PublicationMetadataError("publication_type must be 'scheduled' or 'transient'")
    if not isinstance(publication_id, str) or not publication_id.strip():
        raise PublicationMetadataError("publication_id must be a nonempty publication-event identifier")
    if not isinstance(destination_id, str) or not _IDENTIFIER.fullmatch(destination_id):
        raise PublicationMetadataError("destination_id must be a valid destination identifier")
    if not isinstance(output_specification, ResolvedOutputSpecification):
        raise PublicationMetadataError("output_specification must be the actual resolved output")
    timestamp = _publication_timestamp(published_at)
    output = {
        "aspect_ratio": output_specification.aspect_ratio,
        "requested_output_size": list(output_specification.requested_output_size),
    }

    if publication_type == "transient":
        if prepared_metadata is not None or audience is not None or reveal_stage_index is not None:
            raise PublicationMetadataError("transient publication must not use scheduled preparation or audience data")
        document: dict[str, object] = {
            "schema_version": PUBLICATION_METADATA_VERSION,
            "publication_id": publication_id,
            "publication_type": "transient",
            "published_at": timestamp,
            "destination_id": destination_id,
            "output_specification": output,
            "presentation": None,
            "reconstruction": None,
            "actions": [],
        }
    else:
        if prepared_metadata is None:
            raise PublicationMetadataError("scheduled publication requires prepared metadata")
        if not isinstance(audience, str) or audience not in {"external", "internal"}:
            raise PublicationMetadataError("scheduled publication requires an external or internal audience")
        validate_publication_metadata(prepared_metadata, stage="preparation")
        prepared_output = prepared_metadata["output_specification"]
        if prepared_output != output:
            raise PublicationMetadataError("prepared metadata output does not match the published image")
        prepared_presentation = prepared_metadata["presentation"]
        assert isinstance(prepared_presentation, dict)
        if type(reveal_stage_index) is not int or reveal_stage_index != prepared_presentation["reveal_stage_index"]:
            raise PublicationMetadataError("reveal_stage_index must match the prepared image")
        document = copy.deepcopy(dict(prepared_metadata))
        document.update(
            publication_id=publication_id,
            publication_type="scheduled",
            published_at=timestamp,
            destination_id=destination_id,
            output_specification=output,
            actions=[
                copy.deepcopy(action) for action in prepared_metadata["actions"] if audience in action["visibility"]
            ],
        )

    validate_publication_metadata(document, stage="completed", audience=audience)
    return document


def serialize_publication_metadata(
    document: object,
    *,
    stage: str,
    audience: str | None = None,
) -> str:
    """Serialize validated publication metadata as deterministic UTF-8 JSON text."""
    if stage == "completed" and isinstance(document, dict) and document.get("publication_type") == "scheduled":
        if not isinstance(audience, str) or audience not in {"external", "internal"}:
            raise PublicationMetadataError("scheduled publication serialization requires a destination audience")
    validate_publication_metadata(document, stage=stage, audience=audience)
    try:
        return json.dumps(document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise PublicationMetadataError(f"metadata cannot be represented as JSON: {error}") from error


def parse_publication_metadata(
    contents: str | bytes,
    *,
    stage: str,
    audience: str | None = None,
) -> dict[str, object]:
    """Parse and validate prepared or completed metadata without runtime dependencies."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PublicationMetadataError(f"duplicate JSON field {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise PublicationMetadataError(f"invalid JSON number {value}")

    if isinstance(contents, bytes):
        try:
            contents = contents.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PublicationMetadataError("publication metadata JSON must be UTF-8") from error
    elif not isinstance(contents, str):
        raise PublicationMetadataError("publication metadata JSON must be text or UTF-8 bytes")
    try:
        document = json.loads(contents, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PublicationMetadataError(f"invalid publication metadata JSON: {error}") from error
    try:
        validate_publication_metadata(document, stage=stage, audience=audience)
    except RecursionError as error:
        raise PublicationMetadataError("publication metadata JSON is nested too deeply") from error
    return document


def _publication_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str) and _RFC3339_TIMESTAMP.fullmatch(value):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PublicationMetadataError(
                "published_at must be a valid timezone-qualified RFC-3339 timestamp"
            ) from error
    else:
        raise PublicationMetadataError("published_at must be a timezone-aware datetime or RFC-3339 timestamp")
    if timestamp.utcoffset() is None:
        raise PublicationMetadataError("published_at must include a timezone")
    timestamp = timestamp.astimezone(timezone.utc)
    timespec = "microseconds" if timestamp.microsecond else "seconds"
    return timestamp.isoformat(timespec=timespec).replace("+00:00", "Z")


def _validate_utf8_strings(document: dict[object, object]) -> None:
    pending: list[object] = [document]
    visited: set[int] = set()
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise PublicationMetadataError("metadata strings must contain valid Unicode") from error
        elif isinstance(value, (dict, list)):
            identity = id(value)
            if identity in visited:
                continue
            visited.add(identity)
            pending.extend(value.keys() if isinstance(value, dict) else value)
            if isinstance(value, dict):
                pending.extend(value.values())


def _valid_content_resource_preference(value: object, *, allow_none: bool) -> bool:
    return isinstance(value, str) and ((value == "none" and allow_none) or _valid_identifier_reference(value))


def _valid_palette_reference(value: object) -> bool:
    return _valid_identifier_reference(value)


def _valid_identifier_reference(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value[1:] if value.startswith("@") else value) is not None


def _valid_eligibility_rule(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    fields = set(value)
    if fields == {"ordinary"}:
        return value["ordinary"] is True
    if fields not in ({"year", "month", "day"}, {"month", "day"}, {"day"}, {"month"}):
        return False
    for field, member in value.items():
        if type(member) is not int:
            return False
        if field == "year" and member < 1:
            return False
        if field == "month" and not 1 <= member <= 12:
            return False
        if field == "day" and not 1 <= member <= 31:
            return False
    month = value.get("month")
    day = value.get("day")
    if month is not None and day is not None:
        maximum_day = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]
        year = value.get("year")
        if month == 2 and year is not None and (year % 4 != 0 or (year % 100 == 0 and year % 400 != 0)):
            maximum_day = 28
        if day > maximum_day:
            return False
    return True
