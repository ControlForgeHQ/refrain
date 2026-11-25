"""Filesystem publication backend using the shared publication contract."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PIL import Image

from ..config import DisplayOutputConfiguration
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
        """Reject image-only calls that omit required completed publication metadata."""
        raise DisplayBackendUpdateError("filesystem publication requires application-finalized metadata")

    def publish_scheduled(
        self,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
        completed_metadata: dict[str, object],
    ) -> None:
        """Commit a scheduled image with already-finalized metadata."""
        self._commit(destination, image, completed_metadata, audience=destination.audience)

    def publish_transient(
        self,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
        completed_metadata: dict[str, object],
    ) -> None:
        """Commit a transient image with already-finalized metadata."""
        self._commit(destination, image, completed_metadata)

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
