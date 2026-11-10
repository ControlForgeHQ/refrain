"""Shared construction of selected literary presentations."""

from __future__ import annotations

from datetime import date

from .config import ApplicationConfiguration
from .content import ContentEntry, Quotation
from .persistence import DailySnapshot, SchedulingContext
from .scheduling import resolve_reveal_stages


def build_presentation_snapshot(
    configuration: ApplicationConfiguration,
    entry: ContentEntry,
    quotation: Quotation,
    display_date: date,
) -> DailySnapshot:
    """Build the presentation data shared by scheduled runtime and explicit preview callers."""
    reveal = entry.reveal
    snapshot = DailySnapshot(
        entry_id=entry.id,
        quotation_text=quotation.text,
        quotation_identity=quotation.identity,
        source=entry.source,
        attribution=entry.attribution,
        presentation_style=entry.presentation_style,
        font=entry.font,
        font_faces=entry.font_faces,
        background=entry.background,
        decoration=entry.decoration,
        text_color=entry.text_color,
        decoration_color=entry.decoration_color,
        reveal_schedule={
            "quotation": configuration.day_start.strftime("%H:%M"),
            "source": (reveal.source or configuration.reveal.source).strftime("%H:%M"),
            "attribution": (reveal.attribution or configuration.reveal.attribution).strftime("%H:%M"),
        },
        scheduling=SchedulingContext(
            display_date,
            configuration.day_start.strftime("%H:%M"),
        ),
    )
    resolve_reveal_stages(snapshot)
    return snapshot


__all__ = ["build_presentation_snapshot"]
