"""Validation and finalization of the four version-1 publication metadata forms."""

from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime, timezone
from typing import Any

from .geometry import ResolvedOutputSpecification

PUBLICATION_METADATA_VERSION = 1
MAX_COMPLETED_METADATA_BYTES = 65_536
MAX_COMPLETED_ACTION_BYTES = 4_096
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z\Z")
_RFC3339_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
_ROLES = {"quotation", "source", "attribution"}
_AUDIENCES = {"external", "internal"}
_SHAPES = {
    "content": frozenset({"schema_version", "content"}),
    "presentation": frozenset({"schema_version", "content", "presentation"}),
    "scheduled": frozenset({"schema_version", "content", "presentation", "publication"}),
    "transient": frozenset({"schema_version", "publication"}),
}
_STAGES = {*_SHAPES, "checkpoint", "completed"}


class PublicationMetadataError(ValueError):
    """Publication metadata is invalid or does not match its event."""


def _object(value: object, fields: set[str], label: str, *, optional: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict) or not fields <= value.keys() or value.keys() - fields - optional:
        raise PublicationMetadataError(f"{label} must contain exactly its required and optional fields")
    return value


def _unicode(value: object) -> None:
    pending = [value]
    seen: set[int] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError as error:
                raise PublicationMetadataError("metadata strings must contain valid Unicode") from error
        elif isinstance(item, (dict, list)):
            if id(item) in seen:
                continue
            seen.add(id(item))
            if isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            else:
                pending.extend(item)


def _text(value: object, label: str, *, nonblank: bool = True) -> str:
    if not isinstance(value, str) or (nonblank and not value.strip()):
        raise PublicationMetadataError(f"{label} must be a {'nonblank ' if nonblank else ''}string")
    return value


def _identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PublicationMetadataError(f"{label} must be a stable ASCII identifier")


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise PublicationMetadataError(f"metadata cannot be represented as JSON: {error}") from error


def _validate_content(value: object, *, completed: bool, audience: str | None) -> None:
    content = _object(
        value,
        {"display_date", "selection_revision", "reveal_schedule", "reveal_stage", "quotation", "actions", "qr"},
        "content",
        optional={"source", "attribution"},
    )
    display_date = content["display_date"]
    if not isinstance(display_date, str) or not _DATE.fullmatch(display_date):
        raise PublicationMetadataError("content.display_date must be a valid YYYY-MM-DD date")
    try:
        date.fromisoformat(display_date)
    except ValueError as error:
        raise PublicationMetadataError("content.display_date must be a valid YYYY-MM-DD date") from error
    if type(content["selection_revision"]) is not int or content["selection_revision"] <= 0:
        raise PublicationMetadataError("content.selection_revision must be a positive integer")
    schedule = _object(content["reveal_schedule"], _ROLES, "content.reveal_schedule")
    if any(not isinstance(item, str) or not _TIME.fullmatch(item) for item in schedule.values()):
        raise PublicationMetadataError("content.reveal_schedule requires valid HH:MM times")
    if any(schedule[role] < schedule["quotation"] for role in ("source", "attribution")):
        raise PublicationMetadataError("source and attribution reveal times must not precede quotation")
    visibility = _object(content["reveal_stage"], _ROLES, "content.reveal_stage")
    if any(type(item) is not bool for item in visibility.values()) or not visibility["quotation"]:
        raise PublicationMetadataError("content.reveal_stage requires Boolean flags and a visible quotation")
    _text(content["quotation"], "content.quotation")
    for role in ("source", "attribution"):
        if role in content:
            _text(content[role], f"content.{role}")
        elif visibility[role]:
            raise PublicationMetadataError(f"absent content.{role} cannot be visible")

    actions = content["actions"]
    if not isinstance(actions, list) or len(actions) > (16 if completed else 100):
        raise PublicationMetadataError("content.actions exceeds its applicable count limit or is not an array")
    for action in actions:
        action = _object(action, {"type", "visibility", "payload"}, "action")
        _identifier(action["type"], "action.type")
        action_visibility = action["visibility"]
        if (
            not isinstance(action_visibility, list)
            or not action_visibility
            or any(not isinstance(item, str) or item not in _AUDIENCES for item in action_visibility)
            or len(set(action_visibility)) != len(action_visibility)
        ):
            raise PublicationMetadataError("action.visibility must contain distinct supported audiences")
        payload = _text(action["payload"], "action.payload", nonblank=False)
        if len(payload.encode("utf-8")) > 10_240:
            raise PublicationMetadataError("action.payload exceeds 10240 UTF-8 bytes")
        if audience is not None and completed and audience not in action_visibility:
            raise PublicationMetadataError(f"action is not visible to the {audience} audience")
        if completed and len(_json(action).encode("utf-8")) > MAX_COMPLETED_ACTION_BYTES:
            raise PublicationMetadataError("serialized action exceeds 4096 UTF-8 bytes")

    declarations = content["qr"]
    if not isinstance(declarations, list) or len(declarations) > (1 if completed else 2):
        raise PublicationMetadataError("content.qr exceeds its applicable count limit or is not an array")
    seen: set[str] = set()
    for declaration in declarations:
        declaration = _object(declaration, {"payload", "visibility"}, "QR declaration")
        payload = _text(declaration["payload"], "QR payload", nonblank=False)
        if not payload or len(payload.encode("utf-8")) > 62:
            raise PublicationMetadataError("QR payload must contain 1 to 62 UTF-8 bytes")
        qr_visibility = declaration["visibility"]
        if (
            not isinstance(qr_visibility, list)
            or len(qr_visibility) != 1
            or not isinstance(qr_visibility[0], str)
            or qr_visibility[0] not in _AUDIENCES
            or qr_visibility[0] in seen
        ):
            raise PublicationMetadataError("QR visibility must identify one distinct supported audience")
        seen.add(qr_visibility[0])
        if completed and audience is not None and qr_visibility[0] != audience:
            raise PublicationMetadataError("rendered QR visibility does not match destination audience")


def _validate_presentation(value: object) -> None:
    presentation = _object(
        value, {"style", "background", "decoration", "fonts", "colors", "font_size_range", "insets"}, "presentation"
    )
    if presentation["style"] not in ("centered", "left-aligned"):
        raise PublicationMetadataError("presentation.style is invalid")
    for name in ("background", "decoration"):
        _identifier(presentation[name], f"presentation.{name}")
    fonts = _object(presentation["fonts"], {"bundle", "faces"}, "presentation.fonts")
    _identifier(fonts["bundle"], "presentation.fonts.bundle")
    faces = _object(fonts["faces"], _ROLES, "presentation.fonts.faces")
    for role, face in faces.items():
        _identifier(face, f"presentation.fonts.faces.{role}")
    colors = _object(presentation["colors"], {"text", "decoration"}, "presentation.colors")
    _identifier(colors["text"], "presentation.colors.text")
    if colors["decoration"] is not None:
        _identifier(colors["decoration"], "presentation.colors.decoration")
    bounds = _object(presentation["font_size_range"], {"minimum", "maximum"}, "presentation.font_size_range")
    if any(type(item) is not int or item <= 0 for item in bounds.values()) or bounds["maximum"] < bounds["minimum"]:
        raise PublicationMetadataError("presentation.font_size_range requires positive ordered integer bounds")
    insets = _object(presentation["insets"], {"left", "right", "top", "bottom"}, "presentation.insets")
    if any(type(item) is not int or item < 0 for item in insets.values()):
        raise PublicationMetadataError("presentation.insets requires nonnegative integers")


def _validate_output(value: object) -> None:
    output = _object(value, {"aspect_ratio", "requested_output_size"}, "publication.output_specification")
    if output["aspect_ratio"] not in ("4:3", "5:3", "16:9", "16:10"):
        raise PublicationMetadataError("output aspect_ratio is invalid")
    size = output["requested_output_size"]
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(type(item) is not int for item in size)
        or not 1 <= size[0] <= 3840
        or not 1 <= size[1] <= 2400
    ):
        raise PublicationMetadataError("requested_output_size is invalid")


def _validate_publication(value: object, shape: str) -> None:
    publication = _object(value, {"id", "type", "timestamp", "destination_id", "output_specification"}, "publication")
    _text(publication["id"], "publication.id")
    if publication["type"] != shape:
        raise PublicationMetadataError("publication.type does not match the document form")
    timestamp = publication["timestamp"]
    if not isinstance(timestamp, str) or not _UTC_TIMESTAMP.fullmatch(timestamp):
        raise PublicationMetadataError("publication.timestamp must be a UTC RFC-3339 timestamp ending in Z")
    try:
        datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as error:
        raise PublicationMetadataError("publication.timestamp is invalid") from error
    destination = publication["destination_id"]
    _identifier(destination, "publication.destination_id")
    if len(destination) > 256:
        raise PublicationMetadataError("publication.destination_id exceeds 256 characters")
    _validate_output(publication["output_specification"])


def validate_publication_metadata(document: object, *, stage: str, audience: str | None = None) -> None:
    """Validate an exact form, or either checkpoint/completed form, without modifying it."""
    if not isinstance(stage, str) or stage not in _STAGES:
        raise ValueError(f"stage must be one of {sorted(_STAGES)}")
    if audience is not None and (not isinstance(audience, str) or audience not in _AUDIENCES):
        raise ValueError("audience must be 'external' or 'internal'")
    if not isinstance(document, dict):
        raise PublicationMetadataError("metadata must be an object")
    _unicode(document)
    shape = next((name for name, keys in _SHAPES.items() if document.keys() == keys), None)
    allowed = {"checkpoint": {"content", "presentation"}, "completed": {"scheduled", "transient"}}.get(stage, {stage})
    if shape not in allowed:
        raise PublicationMetadataError(f"metadata does not match the {stage} form")
    if type(document["schema_version"]) is not int or document["schema_version"] != PUBLICATION_METADATA_VERSION:
        raise PublicationMetadataError("unsupported publication metadata schema version")
    if shape in {"content", "presentation", "scheduled"}:
        _validate_content(document["content"], completed=shape == "scheduled", audience=audience)
    if shape in {"presentation", "scheduled"}:
        _validate_presentation(document["presentation"])
    if shape in {"scheduled", "transient"}:
        _validate_publication(document["publication"], shape)
        if len(_json(document).encode("utf-8")) > MAX_COMPLETED_METADATA_BYTES:
            raise PublicationMetadataError("completed metadata exceeds 65536 UTF-8 bytes")


def _output_document(value: ResolvedOutputSpecification | dict[str, object] | None) -> dict[str, object]:
    if isinstance(value, dict):
        _validate_output(value)
        return copy.deepcopy(value)
    if not isinstance(value, ResolvedOutputSpecification):
        raise PublicationMetadataError("output_specification must be a resolved output specification")
    result: dict[str, object] = {
        "aspect_ratio": value.aspect_ratio,
        "requested_output_size": list(value.requested_output_size),
    }
    _validate_output(result)
    return result


def _publication_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str) and _RFC3339_TIMESTAMP.fullmatch(value):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PublicationMetadataError("published_at must be a valid RFC-3339 timestamp") from error
    else:
        raise PublicationMetadataError("published_at must be a timezone-aware datetime or RFC-3339 timestamp")
    if timestamp.utcoffset() is None:
        raise PublicationMetadataError("published_at must include a timezone")
    timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.isoformat(timespec="microseconds" if timestamp.microsecond else "seconds").replace("+00:00", "Z")


def finalize_publication_metadata(
    checkpoint: dict[str, object] | None = None,
    *,
    publication_type: str,
    publication_id: str,
    published_at: datetime | str,
    destination_id: str,
    output_specification: ResolvedOutputSpecification,
    audience: str | None = None,
    selection_revision: int | None = None,
    visibility: object = None,
    effective_presentation: dict[str, object] | None = None,
    rendered_qr: dict[str, object] | None = None,
    prepared_output_specification: ResolvedOutputSpecification | dict[str, object] | None = None,
) -> dict[str, object]:
    """Finalize an event from its checkpoint and explicit prepared-image associations."""
    if publication_type not in ("scheduled", "transient"):
        raise PublicationMetadataError("publication_type must be 'scheduled' or 'transient'")
    output = _output_document(output_specification)
    publication = {
        "id": publication_id,
        "type": publication_type,
        "timestamp": _publication_timestamp(published_at),
        "destination_id": destination_id,
        "output_specification": output,
    }
    if publication_type == "transient":
        if any(
            item is not None
            for item in (
                checkpoint,
                audience,
                selection_revision,
                visibility,
                effective_presentation,
                rendered_qr,
                prepared_output_specification,
            )
        ):
            raise PublicationMetadataError("transient publication cannot contain scheduled associations")
        document: dict[str, object] = {"schema_version": PUBLICATION_METADATA_VERSION, "publication": publication}
    else:
        if not isinstance(audience, str) or audience not in _AUDIENCES:
            raise PublicationMetadataError("scheduled publication requires a destination audience")
        validate_publication_metadata(checkpoint, stage="presentation")
        assert checkpoint is not None
        content = copy.deepcopy(checkpoint["content"])
        if type(selection_revision) is not int or selection_revision != content["selection_revision"]:
            raise PublicationMetadataError("selection_revision does not match the prepared image")
        if _output_document(prepared_output_specification) != output:
            raise PublicationMetadataError("output_specification does not match the prepared image")
        if isinstance(visibility, dict):
            content["reveal_stage"] = copy.deepcopy(visibility)
        else:
            try:
                content["reveal_stage"] = {role: getattr(visibility, role) for role in _ROLES}
            except AttributeError as error:
                raise PublicationMetadataError("prepared image visibility is required") from error
        content["actions"] = [action for action in content["actions"] if audience in action["visibility"]]
        if rendered_qr is not None and rendered_qr not in content["qr"]:
            raise PublicationMetadataError("rendered QR declaration does not match the checkpoint")
        content["qr"] = [] if rendered_qr is None else [copy.deepcopy(rendered_qr)]
        document = {
            "schema_version": PUBLICATION_METADATA_VERSION,
            "content": content,
            "presentation": copy.deepcopy(effective_presentation),
            "publication": publication,
        }
    validate_publication_metadata(document, stage=publication_type, audience=audience)
    return document


def serialize_publication_metadata(document: object, *, stage: str, audience: str | None = None) -> str:
    """Return canonical compact JSON text; scheduled serialization requires an audience."""
    validate_publication_metadata(document, stage=stage, audience=audience)
    if isinstance(document, dict) and document.keys() == _SHAPES["scheduled"] and audience is None:
        raise PublicationMetadataError("scheduled serialization requires a destination audience")
    return _json(document)


def parse_publication_metadata(contents: str | bytes, *, stage: str, audience: str | None = None) -> dict[str, object]:
    """Parse UTF-8 JSON with duplicate-key and nonstandard-number rejection."""

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
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, PublicationMetadataError):
            raise
        raise PublicationMetadataError(f"invalid publication metadata JSON: {error}") from error
    validate_publication_metadata(document, stage=stage, audience=audience)
    return document
