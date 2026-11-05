import asyncio
import re

import httpx
import pytest
import respx

from torznab_to_telegram_announcer.categories import DEFAULT_CATEGORY_RANGES
from torznab_to_telegram_announcer.config import FeedConfig
from torznab_to_telegram_announcer.runner import FeedRunner, next_delay
from torznab_to_telegram_announcer.storage import Storage
from torznab_to_telegram_announcer.torznab import TorznabClient

FEED_URL = "https://indexer.example.com/1/api?apikey=SECRET&t=search"


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, list[str], str]] = []
        self.fail = False

    async def send(self, config_id, tags, body):
        if self.fail:
            return False
        self.sent.append((config_id, tags, body))
        return True


def feed_xml(*ids: int) -> bytes:
    items = "".join(
        f"""<item>
          <title>Release {i}</title>
          <guid>https://tracker.example/download/{i}.private-key</guid>
          <comments>https://tracker.example/torrents/{i}</comments>
          <pubDate>Thu, 05 Nov 2026 {10 + i % 10}:00:00 +0000</pubDate>
          <size>1073741824</size>
          <torznab:attr name="category" value="2000"/>
        </item>"""
        for i in ids
    )
    return (
        '<?xml version="1.0"?><rss version="1.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">'
        f"<channel>{items}</channel></rss>"
    ).encode()


@pytest.fixture
def storage():
    db = Storage(":memory:")
    yield db
    db.close()


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
async def runner(storage, notifier):
    feed = FeedConfig(
        name="feed", url=FEED_URL, apprise_config_id="main", tag=["movies"], interval=60
    )
    async with httpx.AsyncClient() as http:
        yield FeedRunner(
            feed,
            TorznabClient(http, feed.url, feed.headers, feed.timeout),
            storage,
            notifier,
            DEFAULT_CATEGORY_RANGES,
            send_delay=0,
            stop=asyncio.Event(),
        )


@respx.mock
async def test_first_poll_seeds_then_only_new_releases_are_announced(runner, notifier):
    route = respx.get(re.compile(r"https://indexer\.example\.com/.*"))
    route.respond(200, content=feed_xml(1, 2, 3))

    assert await runner.poll() is True
    assert notifier.sent == []

    route.respond(200, content=feed_xml(4, 3, 2, 1))
    assert await runner.poll() is True

    ((config_id, tags, body),) = notifier.sent
    assert (config_id, tags) == ("main", ["movies"])
    assert "Release 4" in body
    assert "https://tracker.example/torrents/4" in body
    assert "private-key" not in body

    assert await runner.poll() is True
    assert len(notifier.sent) == 1


@respx.mock
async def test_new_releases_are_announced_oldest_first(runner, notifier):
    route = respx.get(re.compile(r"https://indexer\.example\.com/.*"))
    route.respond(200, content=feed_xml(1))
    await runner.poll()

    route.respond(200, content=feed_xml(5, 4, 3, 1))
    await runner.poll()

    order = [re.search(r"Release (\d)", body).group(1) for _, _, body in notifier.sent]
    assert order == ["3", "4", "5"]


@respx.mock
async def test_failed_sends_are_retried_on_the_next_poll(runner, notifier):
    route = respx.get(re.compile(r"https://indexer\.example\.com/.*"))
    route.respond(200, content=feed_xml(1))
    await runner.poll()

    route.respond(200, content=feed_xml(2, 1))
    notifier.fail = True
    assert await runner.poll() is False
    assert notifier.sent == []

    notifier.fail = False
    assert await runner.poll() is True
    assert len(notifier.sent) == 1
    assert "Release 2" in notifier.sent[0][2]

    assert await runner.poll() is True
    assert len(notifier.sent) == 1


@respx.mock
async def test_pending_releases_are_retried_even_if_the_fetch_fails(runner, notifier):
    route = respx.get(re.compile(r"https://indexer\.example\.com/.*"))
    route.respond(200, content=feed_xml(1))
    await runner.poll()
    route.respond(200, content=feed_xml(2, 1))
    notifier.fail = True
    await runner.poll()

    notifier.fail = False
    route.respond(500)

    assert await runner.poll() is False
    assert len(notifier.sent) == 1


@respx.mock
async def test_fetch_errors_do_not_leak_the_api_key(runner, caplog):
    respx.get(re.compile(r"https://indexer\.example\.com/.*")).mock(
        side_effect=httpx.ConnectError("boom for " + FEED_URL)
    )

    with caplog.at_level("WARNING"):
        assert await runner.poll() is False

    assert "SECRET" not in caplog.text
    assert "indexer.example.com" in caplog.text


@respx.mock
async def test_unchanged_feed_is_handled(runner, notifier):
    route = respx.get(re.compile(r"https://indexer\.example\.com/.*"))
    route.respond(200, content=feed_xml(1), headers={"ETag": '"v1"'})
    await runner.poll()

    route.respond(304)

    assert await runner.poll() is True
    assert route.calls.last.request.headers["If-None-Match"] == '"v1"'
    assert notifier.sent == []


def test_backoff():
    assert next_delay(60, 0) == 60
    assert next_delay(60, 1) == 120
    assert next_delay(60, 2) == 240
    assert next_delay(60, 20) == 3600
    assert next_delay(7200, 3) == 7200
