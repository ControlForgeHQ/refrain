"""Versioned metadata shared by prepared images and completed publications."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

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


class PublicationMetadataError(ValueError):
    """Raised when shared publication metadata is incomplete or inconsistent."""


def content_entry(snapshot: Any) -> dict[str, object]:
    """Return a valid single-quotation content entry for the committed snapshot."""
    entry: dict[str, object] = {
        "id": snapshot.entry_id,
        "quotations": [snapshot.quotation_text],
        "presentation_style": snapshot.presentation_style,
        "reveal": dict(snapshot.reveal_schedule),
        "eligibility": [{"ordinary": True}],
    }
    for field in ("source", "attribution", "font", "background", "decoration"):
        value = getattr(snapshot, field)
        if value is not None:
            entry[field] = value
    for field in ("font_faces",):
        value = dict(getattr(snapshot, field))
        if value:
            entry[field] = value
    for field in ("text_color", "decoration_color"):
        value = getattr(snapshot, field)
        if value is not None:
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
            "selection_revision": selection_revision,
            "reveal_stage_index": stage_index,
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


def validate_publication_metadata(document: object, *, stage: str) -> None:
    """Validate the shared metadata shape at preparation or completed-publication stage."""
    if stage not in {"preparation", "completed"}:
        raise ValueError("stage must be 'preparation' or 'completed'")
    if not isinstance(document, dict) or set(document) != _TOP_LEVEL_FIELDS:
        raise PublicationMetadataError("metadata must contain every supported publication field")
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
        if not isinstance(document["publication_id"], str) or not document["publication_id"]:
            raise PublicationMetadataError("completed metadata requires a publication_id")
        if not isinstance(document["destination_id"], str) or not _IDENTIFIER.fullmatch(document["destination_id"]):
            raise PublicationMetadataError("completed metadata requires a destination_id")
        published_at = document["published_at"]
        if not isinstance(published_at, str):
            raise PublicationMetadataError("completed metadata requires a publication timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise PublicationMetadataError("published_at must be an ISO-8601 timestamp") from error
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
        "selection_revision",
        "reveal_stage_index",
        "reveal_stage",
    }:
        raise PublicationMetadataError("scheduled presentation context is required and must be complete")
    try:
        date.fromisoformat(presentation["display_date"])
    except (TypeError, ValueError) as error:
        raise PublicationMetadataError("display_date must be an ISO date") from error
    if type(presentation["selection_revision"]) is not int or presentation["selection_revision"] <= 0:
        raise PublicationMetadataError("selection_revision must be a positive integer")
    if type(presentation["reveal_stage_index"]) is not int or presentation["reveal_stage_index"] < 0:
        raise PublicationMetadataError("reveal_stage_index must be a nonnegative integer")
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
        or not {"id", "quotations", "presentation_style", "reveal", "eligibility"} <= set(entry)
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
    if (
        not isinstance(reconstruction["presentation_style"], str)
        or reconstruction["presentation_style"] not in {"centered", "left-aligned"}
        or entry["presentation_style"] != reconstruction["presentation_style"]
    ):
        raise PublicationMetadataError("presentation_style is invalid")
    for field in ("source", "attribution", "font", "background", "decoration"):
        if field in entry and (not isinstance(entry[field], str) or not entry[field].strip()):
            raise PublicationMetadataError(f"content_entry.{field} must be a nonempty string when present")
    reveal_schedule = entry["reveal"]
    if (
        not isinstance(reveal_schedule, dict)
        or set(reveal_schedule) != _ROLES
        or any(not isinstance(value, str) or not _TIME.fullmatch(value) for value in reveal_schedule.values())
    ):
        raise PublicationMetadataError("content_entry.reveal is invalid")
    if (
        not isinstance(entry["eligibility"], list)
        or not entry["eligibility"]
        or any(not isinstance(rule, dict) or not rule for rule in entry["eligibility"])
    ):
        raise PublicationMetadataError("content_entry.eligibility is invalid")
    if "font_faces" in entry and (
        not isinstance(entry["font_faces"], dict)
        or set(entry["font_faces"]) - _ROLES
        or any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) for value in entry["font_faces"].values())
    ):
        raise PublicationMetadataError("content_entry.font_faces is invalid")
    for field in ("text_color", "decoration_color"):
        if field in entry and (
            not isinstance(entry[field], list)
            or not entry[field]
            or any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.lstrip("@")) for value in entry[field])
        ):
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
        or any(not isinstance(value, str) or not value for value in fonts["faces"].values())
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
    for action in actions:
        if not isinstance(action, dict) or set(action) != {"type", "visibility", "payload"}:
            raise PublicationMetadataError("each action must preserve its complete content-entry declaration")
        if not isinstance(action["type"], str) or not _IDENTIFIER.fullmatch(action["type"]):
            raise PublicationMetadataError("action type must be a nonempty string")
        visibility = action["visibility"]
        if (
            not isinstance(visibility, list)
            or not visibility
            or any(not isinstance(value, str) or value not in {"public", "private"} for value in visibility)
            or len(set(visibility)) != len(visibility)
            or not isinstance(action["payload"], str)
        ):
            raise PublicationMetadataError("action visibility and payload are invalid")
