"""Filesystem publication backend using the shared publication contract."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PIL import Image

from ..config import DisplayOutputConfiguration
from ..publication_metadata import finalize_publication_metadata
from ..publication_storage import PublicationStorageError
from . import DisplayBackendUpdateError

if TYPE_CHECKING:
    from ..publication_storage import PublicationStore

_LOGGER = logging.getLogger(__name__)


class FilesystemPublicationDisplayBackend:
    """Commit destination-specific complete publications to the configured store."""

    def __init__(self, store: PublicationStore) -> None:
        self._store = store

    def publish(self, destination: DisplayOutputConfiguration, image: Image.Image) -> None:
        """Treat a context-free complete image as a transient publication."""
        self.publish_transient(destination, image)

    def publish_scheduled(
        self,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
        prepared_metadata: dict[str, object],
    ) -> None:
        """Finalize cached preparation data independently for this destination."""
        presentation = prepared_metadata.get("presentation")
        if not isinstance(presentation, dict):
            raise DisplayBackendUpdateError("prepared publication metadata has no presentation")
        try:
            metadata = finalize_publication_metadata(
                prepared_metadata,
                publication_type="scheduled",
                publication_id=uuid.uuid4().hex,
                published_at=datetime.now(timezone.utc),
                destination_id=destination.identifier,
                output_specification=destination.output_specification,
                audience=destination.audience,
                reveal_stage_index=presentation.get("reveal_stage_index"),
            )
        except (TypeError, ValueError) as error:
            raise DisplayBackendUpdateError(f"cannot finalize scheduled publication: {error}") from error
        self._commit(destination, image, metadata, audience=destination.audience)

    def publish_transient(self, destination: DisplayOutputConfiguration, image: Image.Image) -> None:
        """Commit a complete image with minimal transient metadata."""
        try:
            metadata = finalize_publication_metadata(
                publication_type="transient",
                publication_id=uuid.uuid4().hex,
                published_at=datetime.now(timezone.utc),
                destination_id=destination.identifier,
                output_specification=destination.output_specification,
            )
        except (TypeError, ValueError) as error:
            raise DisplayBackendUpdateError(f"cannot finalize transient publication: {error}") from error
        self._commit(destination, image, metadata)

    def _commit(
        self,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
        metadata: dict[str, object],
        *,
        audience: str | None = None,
    ) -> None:
        try:
            self._store.publish(destination.identifier, image, metadata, audience=audience)
        except PublicationStorageError as error:
            if error.published:
                try:
                    current = self._store.read_current(destination.identifier)
                except PublicationStorageError:
                    current = None
                if current is not None and current.manifest.publication_id == metadata["publication_id"]:
                    _LOGGER.warning(
                        "Publication %s committed but cleanup was incomplete: %s",
                        metadata["publication_id"],
                        error,
                    )
                    return
            raise DisplayBackendUpdateError(f"cannot commit publication: {error}") from error

    def close(self) -> None:
        """Release backend resources; the shared publication store has no open handles."""
