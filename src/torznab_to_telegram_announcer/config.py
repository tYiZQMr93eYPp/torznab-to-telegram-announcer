import os
import re
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .categories import DEFAULT_CATEGORY_RANGES

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_DURATION = re.compile(r"^(\d+)\s*([smh]?)$")
_DURATION_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


def parse_duration(value: Any) -> int:
    """Seconds from an int or a string such as ``90``, ``30s``, ``10m`` or ``1h``."""
    if isinstance(value, bool):
        raise ValueError("invalid duration")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = _DURATION.match(value.strip().lower())
        if match:
            return int(match.group(1)) * _DURATION_UNITS[match.group(2)]
    raise ValueError("expected seconds or a duration such as '10m'")


Duration = Annotated[int, Field(ge=1)]


def _parse_ranges(value: Any) -> list[tuple[int, int]]:
    if isinstance(value, int) and not isinstance(value, bool):
        return [(value, value)]
    if not isinstance(value, list):
        raise ValueError("expected an id, or a list of ids and [low, high] ranges")
    if len(value) == 2 and all(isinstance(part, int) for part in value):
        value = [value]
    ranges: list[tuple[int, int]] = []
    for entry in value:
        if isinstance(entry, int) and not isinstance(entry, bool):
            ranges.append((entry, entry))
        elif isinstance(entry, list) and len(entry) == 2 and all(isinstance(part, int) for part in entry):
            low, high = entry
            if low > high:
                raise ValueError(f"invalid range [{low}, {high}]")
            ranges.append((low, high))
        else:
            raise ValueError(f"invalid range {entry!r}")
    return ranges


def _validate_category_map(value: Any) -> dict[str, list[tuple[int, int]]]:
    if not isinstance(value, dict):
        raise ValueError("expected a mapping of category name to ranges")
    return {str(name): _parse_ranges(ranges) for name, ranges in value.items()}


class FeedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    url: str
    headers: dict[str, str] = {}
    interval: Duration = 600
    timeout: float = Field(default=30.0, gt=0)
    apprise_config_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    tag: list[str] = Field(min_length=1)
    categories: dict[str, list[tuple[int, int]]] = {}

    @field_validator("interval", mode="before")
    @classmethod
    def _interval(cls, value: Any) -> int:
        return parse_duration(value)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        if urlsplit(value).scheme not in {"http", "https"}:
            raise ValueError("must be an http(s) URL")
        return value

    @field_validator("tag", mode="before")
    @classmethod
    def _tag(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

    @field_validator("categories", mode="before")
    @classmethod
    def _categories(cls, value: Any) -> Any:
        return _validate_category_map(value)


class AppriseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Apprise API server, e.g. apprises://user:pass@apprise.example.org[:port][/prefix].
    # Each feed names a configuration id stored on that server.
    url: str

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"apprise", "apprises"} or not parts.hostname:
            raise ValueError("must be an apprise:// or apprises:// URL with a host")
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database: Path = Path("announcer.sqlite3")
    send_delay: float = Field(default=3.0, ge=0)
    apprise: AppriseSettings
    category_map: dict[str, list[tuple[int, int]]] = {
        name: list(ranges) for name, ranges in DEFAULT_CATEGORY_RANGES.items()
    }
    feeds: list[FeedConfig] = Field(min_length=1)

    @field_validator("category_map", mode="before")
    @classmethod
    def _category_map(cls, value: Any) -> Any:
        return _validate_category_map(value)

    @model_validator(mode="after")
    def _check_feed_names(self) -> "Config":
        names = [feed.name for feed in self.feeds]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate feed names: {', '.join(duplicates)}")
        return self


def expand_env(value: Any, environ: dict[str, str]) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if name in environ:
                return environ[name]
            if default is not None:
                return default
            raise ConfigError(f"environment variable {name} is not set")

        return _ENV_REFERENCE.sub(replace, value)
    if isinstance(value, dict):
        return {key: expand_env(item, environ) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item, environ) for item in value]
    return value


def load_config(path: str | Path, environ: dict[str, str] | None = None) -> Config:
    """Load the YAML config; ``${VAR}`` and ``${VAR:-default}`` are expanded."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error.strerror or error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")

    raw = expand_env(raw, dict(os.environ if environ is None else environ))
    try:
        config = Config.model_validate(raw)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, problem['loc']))}: {problem['msg']}" for problem in error.errors()
        )
        raise ConfigError(f"invalid configuration: {problems}") from None

    if not config.database.is_absolute():
        config.database = path.resolve().parent / config.database
    return config
