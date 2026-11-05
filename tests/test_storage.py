from datetime import UTC, datetime
from decimal import Decimal

import pytest

from torznab_to_telegram_announcer.models import Release
from torznab_to_telegram_announcer.storage import Storage


def make_release(key: str, published_hour: int | None = 10, **overrides) -> Release:
    values = dict(
        key=key,
        title=f"Title {key}",
        url=f"https://x/{key}",
        size=1234,
        category_ids=(5000, 100002),
        tags=("internal", "freeleech"),
        imdb_id="0409591",
        tvdb_id=None,
        tmdb_id="46260",
        download_factor=Decimal("0.5"),
        upload_factor=Decimal(2),
        published=datetime(2026, 11, 5, published_hour, tzinfo=UTC) if published_hour is not None else None,
    )
    values.update(overrides)
    return Release(**values)


@pytest.fixture
def storage():
    db = Storage(":memory:")
    yield db
    db.close()


def test_first_record_seeds_without_pending(storage):
    assert not storage.is_seeded("feed")

    new = storage.record("feed", [make_release("a"), make_release("b")])

    assert new == 2
    assert storage.is_seeded("feed")
    assert storage.pending("feed") == []


def test_empty_first_poll_still_seeds(storage):
    storage.record("feed", [])

    assert storage.is_seeded("feed")
    storage.record("feed", [make_release("a")])
    assert len(storage.pending("feed")) == 1


def test_new_releases_after_seeding_are_pending_and_deduplicated(storage):
    storage.record("feed", [make_release("a")])

    assert storage.record("feed", [make_release("a"), make_release("b")]) == 1
    assert storage.record("feed", [make_release("a"), make_release("b")]) == 0

    assert [release.key for _, release in storage.pending("feed")] == ["b"]


def test_pending_is_oldest_first(storage):
    storage.record("feed", [])
    storage.record(
        "feed",
        [make_release("new", 12), make_release("old", 8), make_release("mid", 10)],
    )

    assert [release.key for _, release in storage.pending("feed")] == ["old", "mid", "new"]


def test_pending_round_trips_every_field(storage):
    storage.record("feed", [])
    original = make_release("a")
    storage.record("feed", [original])

    ((_, stored),) = storage.pending("feed")

    assert stored == original


def test_release_without_optional_fields_round_trips(storage):
    storage.record("feed", [])
    original = make_release(
        "a", published_hour=None, url=None, size=None, category_ids=(), tags=(), imdb_id=None, tmdb_id=None
    )
    storage.record("feed", [original])

    ((_, stored),) = storage.pending("feed")

    assert stored == original


def test_mark_notified_removes_from_pending(storage):
    storage.record("feed", [])
    storage.record("feed", [make_release("a"), make_release("b")])
    (first_id, _), _ = storage.pending("feed")

    storage.mark_notified(first_id)

    assert [release.key for _, release in storage.pending("feed")] == ["b"]


def test_failed_releases_stay_pending(storage):
    storage.record("feed", [])
    storage.record("feed", [make_release("a")])
    ((release_id, _),) = storage.pending("feed")

    storage.mark_failed(release_id)

    assert len(storage.pending("feed")) == 1


def test_feeds_are_independent(storage):
    storage.record("one", [make_release("a")])
    storage.record("two", [])
    storage.record("two", [make_release("a")])

    assert storage.pending("one") == []
    assert len(storage.pending("two")) == 1


def test_state_survives_reopening(tmp_path):
    path = tmp_path / "nested" / "db.sqlite3"
    first = Storage(path)
    first.record("feed", [])
    first.record("feed", [make_release("a")])
    first.close()

    second = Storage(path)

    assert second.is_seeded("feed")
    assert len(second.pending("feed")) == 1
    second.close()
