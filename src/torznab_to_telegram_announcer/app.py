import argparse
import asyncio
import logging
import os
import signal
from collections.abc import Sequence

import httpx

from .config import Config, ConfigError, load_config
from .log_config import LogConfig
from .notifier import AppriseNotifier, NotifierError
from .runner import run_all
from .storage import Storage
from .torznab import TorznabClient

logger = logging.getLogger(__name__)


async def serve(config: Config) -> None:
    notifier = AppriseNotifier(config.apprise.url)
    for feed in config.feeds:
        notifier.prepare(feed.apprise_config_id, feed.tag)

    storage = Storage(config.database)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    try:
        async with httpx.AsyncClient() as http:
            await run_all(
                config,
                lambda feed: TorznabClient(http, feed.url, feed.headers, feed.timeout),
                storage,
                notifier,
                stop,
            )
    finally:
        storage.close()
    logger.info("stopped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="torznab-to-telegram-announcer",
        description="Announce new releases of Torznab feeds through Apprise.",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=os.environ.get("ANNOUNCER_CONFIG", "config.yml"),
        help="path to the YAML config file (default: $ANNOUNCER_CONFIG or config.yml)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        type=str.upper,
        help="log verbosity (default: $LOG_LEVEL or INFO)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    LogConfig(level=args.log_level).configure()
    # These log full request URLs, which can contain api keys.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        config = load_config(args.config)
        asyncio.run(serve(config))
    except (ConfigError, NotifierError) as error:
        logger.error("%s", error)
        return 2
    except KeyboardInterrupt:
        pass
    return 0
