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
        """Finalize a checkpoint and its cached image associations for this destination."""
        try:
            checkpoint = prepared_metadata["checkpoint"]
            rendered_qr = prepared_metadata["rendered_qr"]
            if rendered_qr is not None:
                declarations = checkpoint["content"]["qr"]
                if rendered_qr not in declarations:
                    raise ValueError("rendered QR declaration does not match the checkpoint")
                rendered_qr = next(
                    (
                        declaration
                        for declaration in declarations
                        if declaration["payload"] == rendered_qr["payload"]
                        and declaration["visibility"] == [destination.audience]
                    ),
                    None,
                )
                if rendered_qr is None:
                    raise ValueError("rendered QR payload does not match the destination audience")
            metadata = finalize_publication_metadata(
                checkpoint,
                publication_type="scheduled",
                publication_id=uuid.uuid4().hex,
                published_at=datetime.now(timezone.utc),
                destination_id=destination.identifier,
                output_specification=destination.output_specification,
                audience=destination.audience,
                selection_revision=prepared_metadata["selection_revision"],
                visibility=prepared_metadata["visibility"],
                effective_presentation=prepared_metadata["effective_presentation"],
                rendered_qr=rendered_qr,
                prepared_output_specification=prepared_metadata["output_specification"],
            )
        except (KeyError, TypeError, ValueError) as error:
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
                publication = metadata.get("publication")
                if (
                    current is not None
                    and isinstance(publication, dict)
                    and current.manifest.publication_id == publication.get("id")
                    and current.metadata == metadata
                ):
                    _LOGGER.warning(
                        "Publication %s committed but cleanup was incomplete: %s",
                        publication["id"],
                        error,
                    )
                    return
            raise DisplayBackendUpdateError(f"cannot commit publication: {error}") from error

    def close(self) -> None:
        """Release backend resources; the shared publication store has no open handles."""
