import logging
from typing import Protocol
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import apprise
from apprise import NotifyFormat

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send(self, config_id: str, tags: list[str], body: str) -> bool:
        """Deliver a Markdown message; ``True`` only if the Apprise API accepted it."""
        ...


class NotifierError(Exception):
    """The Apprise API URL could not be used."""


def build_url(base_url: str, config_id: str, tags: list[str]) -> str:
    """``apprises://host`` + id + tags -> ``apprises://host/<id>/?tags=a,b``."""
    parts = urlsplit(base_url)
    path = f"{parts.path.rstrip('/')}/{quote(config_id, safe='')}/"
    query = urlencode([*parse_qsl(parts.query), ("tags", ",".join(tags))])
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


class AppriseNotifier:
    """Notifies through the configurations stored on an Apprise API server.

    A configuration id on the server holds tagged notification URLs; the tags of
    a feed select which of them receive its messages.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._instances: dict[tuple[str, tuple[str, ...]], apprise.Apprise] = {}

    def prepare(self, config_id: str, tags: list[str]) -> apprise.Apprise:
        key = (config_id, tuple(tags))
        if key not in self._instances:
            instance = apprise.Apprise()
            if not instance.add(build_url(self._base_url, config_id, tags)):
                raise NotifierError(
                    f"'{self._base_url.split('@')[-1]}' is not a valid Apprise API URL "
                    f"for config id '{config_id}'"
                )
            self._instances[key] = instance
        return self._instances[key]

    async def send(self, config_id: str, tags: list[str], body: str) -> bool:
        result = await self.prepare(config_id, tags).async_notify(
            body=body, body_format=NotifyFormat.MARKDOWN
        )
        return bool(result)
