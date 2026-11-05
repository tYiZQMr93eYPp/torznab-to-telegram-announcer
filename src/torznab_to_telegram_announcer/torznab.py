import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from .models import Release

ATTR_NAMESPACES = frozenset(
    {
        "http://torznab.com/schemas/2015/feed",
        "http://www.newznab.com/DTD/2010/feeds/attributes/",
    }
)

USER_AGENT = "torznab-to-telegram-announcer"


class TorznabError(Exception):
    """The feed could not be fetched or is not a valid Torznab response."""


def redact_url(url: str) -> str:
    """Hide credentials and query string values (api keys) so the URL is safe to log."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host = f"{host}:{parts.port}"
    query = "&".join(f"{name}=***" for name, _ in parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _split_tag(element_tag: str) -> tuple[str, str]:
    if element_tag.startswith("{"):
        namespace, _, local = element_tag[1:].partition("}")
        return namespace, local
    return "", element_tag


def _parse_decimal(value: str | None, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return default
    return parsed if parsed.is_finite() else default


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _normalize_numeric_id(value: str | None) -> str | None:
    """Digits only; empty and all-zero ids mean "unknown"."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits or int(digits) == 0:
        return None
    return digits


def _normalize_imdb_id(value: str | None) -> str | None:
    digits = _normalize_numeric_id(value)
    return digits.zfill(7) if digits else None


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _first(attrs: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        for value in attrs.get(name, []):
            if value.strip():
                return value
    return None


def _parse_item(item) -> Release | None:
    texts: dict[str, str] = {}
    plain_categories: list[str] = []
    attrs: dict[str, list[str]] = {}
    enclosure_length: str | None = None

    for child in item:
        namespace, local = _split_tag(child.tag)
        if local == "attr" and namespace in ATTR_NAMESPACES:
            name, value = child.get("name"), child.get("value")
            if name and value is not None:
                attrs.setdefault(name.lower(), []).append(value)
        elif namespace == "" and local == "category":
            plain_categories.append((child.text or "").strip())
        elif namespace == "" and local == "enclosure":
            enclosure_length = child.get("length")
        elif namespace == "":
            texts.setdefault(local, (child.text or "").strip())

    title = texts.get("title")
    url = texts.get("comments") or None
    guid = texts.get("guid")

    # The guid usually embeds the user's download key, so only its hash is kept.
    if url:
        key = url
    elif guid:
        key = "guid-sha256:" + hashlib.sha256(guid.encode()).hexdigest()
    else:
        return None
    if not title:
        return None

    category_ids: list[int] = []
    for raw in [*attrs.get("category", []), *plain_categories]:
        category_id = _parse_int(raw)
        if category_id is not None and category_id not in category_ids:
            category_ids.append(category_id)

    tags: list[str] = []
    for raw in attrs.get("tag", []):
        for tag in raw.split(","):
            tag = tag.strip().lower()
            if tag and tag not in tags:
                tags.append(tag)

    size = _parse_int(texts.get("size")) or _parse_int(_first(attrs, "size")) or _parse_int(enclosure_length)

    return Release(
        key=key,
        title=title,
        url=url,
        size=size,
        category_ids=tuple(category_ids),
        tags=tuple(tags),
        imdb_id=_normalize_imdb_id(_first(attrs, "imdbid", "imdb")),
        tvdb_id=_normalize_numeric_id(_first(attrs, "tvdbid", "tvdb")),
        tmdb_id=_normalize_numeric_id(_first(attrs, "tmdbid", "tmdb")),
        download_factor=_parse_decimal(_first(attrs, "downloadvolumefactor"), Decimal(1)),
        upload_factor=_parse_decimal(_first(attrs, "uploadvolumefactor"), Decimal(1)),
        published=_parse_published(texts.get("pubDate")),
    )


def parse_feed(content: bytes) -> list[Release]:
    """Parse a Torznab RSS document. Items without a usable key are skipped."""
    try:
        root = SafeET.fromstring(content)
    except (SafeET.ParseError, DefusedXmlException) as error:
        raise TorznabError(f"invalid XML: {error}") from error

    if _split_tag(root.tag)[1] == "error":
        raise TorznabError(f"Torznab error {root.get('code')}: {root.get('description')}")
    if _split_tag(root.tag)[1] != "rss":
        raise TorznabError(f"unexpected root element <{root.tag}>")

    releases: list[Release] = []
    seen: set[str] = set()
    for item in root.iter("item"):
        release = _parse_item(item)
        if release is not None and release.key not in seen:
            seen.add(release.key)
            releases.append(release)
    return releases


class TorznabClient:
    """Fetches one feed, using conditional requests when the server supports them."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = client
        self._url = url
        self._headers = {"User-Agent": USER_AGENT, **(headers or {})}
        self._timeout = timeout
        self._validators: dict[str, str] = {}

    async def fetch(self) -> list[Release] | None:
        """Return the releases, or ``None`` when the feed is unchanged (HTTP 304)."""
        try:
            response = await self._client.get(
                self._url,
                headers={**self._headers, **self._validators},
                timeout=self._timeout,
                follow_redirects=True,
            )
        except httpx.HTTPError as error:
            # httpx error messages can contain the full URL, including the api key.
            raise TorznabError(
                f"request to {redact_url(self._url)} failed: {type(error).__name__}"
            ) from None

        if response.status_code == httpx.codes.NOT_MODIFIED:
            return None
        if response.is_error:
            raise TorznabError(
                f"{redact_url(self._url)} returned HTTP {response.status_code}"
            )

        releases = parse_feed(response.content)
        self._validators = {
            header: response.headers[source]
            for header, source in (("If-None-Match", "ETag"), ("If-Modified-Since", "Last-Modified"))
            if source in response.headers
        }
        return releases
