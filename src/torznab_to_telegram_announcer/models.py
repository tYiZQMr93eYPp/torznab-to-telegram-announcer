from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Release:
    """A Torznab item reduced to the fields the announcer cares about."""

    key: str
    title: str
    url: str | None
    size: int | None
    category_ids: tuple[int, ...]
    tags: tuple[str, ...]
    imdb_id: str | None
    tvdb_id: str | None
    tmdb_id: str | None
    download_factor: Decimal
    upload_factor: Decimal
    published: datetime | None
