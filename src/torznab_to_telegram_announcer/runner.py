import asyncio
import logging

from .categories import CategoryRanges, merge_ranges
from .config import Config, FeedConfig
from .formatting import format_release
from .notifier import Notifier
from .storage import Storage
from .torznab import TorznabClient, TorznabError

logger = logging.getLogger(__name__)

MAX_BACKOFF = 3600


def next_delay(interval: int, consecutive_failures: int) -> float:
    """Exponential backoff after failures, never shorter than the interval."""
    if consecutive_failures == 0:
        return interval
    return max(interval, min(interval * 2**consecutive_failures, MAX_BACKOFF))


class FeedRunner:
    """Polls one feed and announces what is new."""

    def __init__(
        self,
        feed: FeedConfig,
        client: TorznabClient,
        storage: Storage,
        notifier: Notifier,
        category_map: CategoryRanges,
        send_delay: float,
        stop: asyncio.Event,
    ) -> None:
        self.feed = feed
        self._client = client
        self._storage = storage
        self._notifier = notifier
        self._ranges = merge_ranges(category_map, feed.categories)
        self._send_delay = send_delay
        self._stop = stop

    async def poll(self) -> bool:
        """One poll cycle. Returns ``False`` if fetching or announcing failed."""
        ok = True
        try:
            releases = await self._client.fetch()
        except TorznabError as error:
            logger.warning("[%s] fetch failed: %s", self.feed.name, error)
            ok = False
        else:
            if releases is not None:
                seeding = not self._storage.is_seeded(self.feed.name)
                new = self._storage.record(self.feed.name, releases)
                if seeding:
                    logger.info(
                        "[%s] first run: marked %d existing release(s) as seen without announcing",
                        self.feed.name,
                        new,
                    )
                else:
                    logger.info("[%s] %d new release(s)", self.feed.name, new)
        return await self._announce_pending() and ok

    async def _announce_pending(self) -> bool:
        pending = self._storage.pending(self.feed.name)
        all_sent = True
        for index, (release_id, release) in enumerate(pending):
            if index and self._send_delay:
                if await self._interrupted(self._send_delay):
                    return all_sent
            body = format_release(release, self._ranges)
            try:
                sent = await self._notifier.send(self.feed.apprise_config_id, self.feed.tag, body)
            except Exception:
                logger.exception("[%s] unexpected error while notifying", self.feed.name)
                sent = False
            if sent:
                self._storage.mark_notified(release_id)
                logger.info("[%s] announced: %s", self.feed.name, release.title)
            else:
                self._storage.mark_failed(release_id)
                all_sent = False
                logger.warning(
                    "[%s] could not announce '%s', will retry on the next poll",
                    self.feed.name,
                    release.title,
                )
        return all_sent

    async def _interrupted(self, seconds: float) -> bool:
        """Sleep, returning ``True`` early if shutdown was requested."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

    async def run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                ok = await self.poll()
            except Exception:
                logger.exception("[%s] unexpected error", self.feed.name)
                ok = False
            failures = 0 if ok else failures + 1
            delay = next_delay(self.feed.interval, failures)
            if failures:
                logger.info("[%s] next attempt in %ds", self.feed.name, delay)
            if await self._interrupted(delay):
                break


async def run_all(
    config: Config,
    client_factory,
    storage: Storage,
    notifier: Notifier,
    stop: asyncio.Event,
) -> None:
    runners = [
        FeedRunner(
            feed,
            client_factory(feed),
            storage,
            notifier,
            config.category_map,
            config.send_delay,
            stop,
        )
        for feed in config.feeds
    ]
    async with asyncio.TaskGroup() as group:
        for runner in runners:
            group.create_task(runner.run(), name=runner.feed.name)
