import asyncio
import logging
import time
from collections.abc import Callable

from .categories import CategoryRanges, merge_ranges
from .config import AlertSettings, Config, FeedConfig
from .formatting import escape_markdown, format_release
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
        alerts: AlertSettings | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.feed = feed
        self._alerts = alerts
        self._clock = clock
        self._last_alert: float | None = None
        self._last_error = ""
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
            self._last_error = f"fetch failed: {error}"
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
                self._last_error = "could not announce new releases"
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

    async def _alert_if_needed(self, failures: int) -> None:
        if self._alerts is None or failures < self._alerts.after_failures:
            return
        now = self._clock()
        if self._last_alert is not None and now - self._last_alert < self._alerts.cooldown:
            return
        body = (
            f"⚠️ **{escape_markdown(self.feed.name)}** has failed {failures} times in a row\n\n"
            f"Last error: {escape_markdown(self._last_error)}"
        )
        try:
            sent = await self._notifier.send(self._alerts.apprise_config_id, self._alerts.tag, body)
        except Exception:
            logger.exception("[%s] unexpected error while sending the alert", self.feed.name)
            return
        if sent:
            self._last_alert = now
            logger.info("[%s] alert sent after %d consecutive failures", self.feed.name, failures)
        else:
            logger.warning("[%s] could not send the alert, will retry on the next failure", self.feed.name)

    async def run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                ok = await self.poll()
            except Exception as error:
                logger.exception("[%s] unexpected error", self.feed.name)
                self._last_error = f"unexpected error: {type(error).__name__}"
                ok = False
            failures = 0 if ok else failures + 1
            if not ok:
                await self._alert_if_needed(failures)
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
            config.alerts,
        )
        for feed in config.feeds
    ]
    async with asyncio.TaskGroup() as group:
        for runner in runners:
            group.create_task(runner.run(), name=runner.feed.name)
