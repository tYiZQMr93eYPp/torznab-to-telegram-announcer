import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .models import Release

SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    name TEXT PRIMARY KEY,
    seeded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed TEXT NOT NULL,
    item_key TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    size INTEGER,
    category_ids TEXT NOT NULL,
    tags TEXT NOT NULL,
    imdb_id TEXT,
    tvdb_id TEXT,
    tmdb_id TEXT,
    download_factor TEXT NOT NULL,
    upload_factor TEXT NOT NULL,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    notified_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    UNIQUE (feed, item_key)
);

CREATE INDEX IF NOT EXISTS releases_pending
    ON releases (feed) WHERE notified_at IS NULL;
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    """SQLite persistence for seen releases and their notification state."""

    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def is_seeded(self, feed: str) -> bool:
        row = self._db.execute("SELECT 1 FROM feeds WHERE name = ?", (feed,)).fetchone()
        return row is not None

    def record(self, feed: str, releases: list[Release]) -> int:
        """Store the releases of a poll and return how many were new.

        The first poll of a feed only seeds the database: everything already in
        the feed is marked as notified so that an empty database does not flood
        the channel. Later polls leave new releases pending for notification.
        """
        seeding = not self.is_seeded(feed)
        now = _now()
        new = 0
        with self._db:
            for release in releases:
                cursor = self._db.execute(
                    """
                    INSERT OR IGNORE INTO releases (
                        feed, item_key, title, url, size, category_ids, tags,
                        imdb_id, tvdb_id, tmdb_id, download_factor, upload_factor,
                        published_at, first_seen_at, notified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feed,
                        release.key,
                        release.title,
                        release.url,
                        release.size,
                        ",".join(map(str, release.category_ids)),
                        ",".join(release.tags),
                        release.imdb_id,
                        release.tvdb_id,
                        release.tmdb_id,
                        str(release.download_factor),
                        str(release.upload_factor),
                        release.published.isoformat(timespec="seconds") if release.published else None,
                        now,
                        now if seeding else None,
                    ),
                )
                new += cursor.rowcount
            if seeding:
                self._db.execute(
                    "INSERT INTO feeds (name, seeded_at) VALUES (?, ?)", (feed, now)
                )
        return new

    def pending(self, feed: str) -> list[tuple[int, Release]]:
        """Releases still to be announced, oldest first."""
        rows = self._db.execute(
            """
            SELECT * FROM releases
            WHERE feed = ? AND notified_at IS NULL
            ORDER BY COALESCE(published_at, first_seen_at), id
            """,
            (feed,),
        ).fetchall()
        return [(row["id"], _row_to_release(row)) for row in rows]

    def mark_notified(self, release_id: int) -> None:
        with self._db:
            self._db.execute(
                "UPDATE releases SET notified_at = ? WHERE id = ?", (_now(), release_id)
            )

    def mark_failed(self, release_id: int) -> None:
        with self._db:
            self._db.execute(
                "UPDATE releases SET attempts = attempts + 1 WHERE id = ?", (release_id,)
            )


def _row_to_release(row: sqlite3.Row) -> Release:
    return Release(
        key=row["item_key"],
        title=row["title"],
        url=row["url"],
        size=row["size"],
        category_ids=tuple(int(value) for value in row["category_ids"].split(",") if value),
        tags=tuple(value for value in row["tags"].split(",") if value),
        imdb_id=row["imdb_id"],
        tvdb_id=row["tvdb_id"],
        tmdb_id=row["tmdb_id"],
        download_factor=Decimal(row["download_factor"]),
        upload_factor=Decimal(row["upload_factor"]),
        published=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
    )
