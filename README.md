# torznab-to-telegram-announcer

Watches one or more [Torznab](specs/torznab/) RSS feeds and announces new releases to Telegram through [Apprise](https://appriseit.com/).

## Contents

- [Features](#features)
- [Message format](#message-format)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Environment variables](#environment-variables)
- [Notifications](#notifications)
- [Development](#development)

## Features

- Several feeds, each with its own polling interval, credentials and categories.
- Built to run as a long-lived Docker service. It shuts down cleanly on `SIGTERM`.
- The first poll of a feed only *seeds* the database, so an empty database never floods the channel. Only releases that show up afterwards are announced.
- Failed announcements are retried on the next poll, oldest first.
- Releases are kept in SQLite, keyed by the item's `comments` URL. The feed's `guid` is never stored or logged, because it usually contains your download key.
- API keys are redacted from logs.

## Message format

```text
📺 **Example Show S01 2024 1080p WEB-DL H.264 DUAL AAC 2.0-GROUP**

📂 **Category:** TV
💾 **Size:** 4.69 GiB
💸 **Free:** 100%
🏷️ **Tags:** `internal,freeleech,doubleupload`
🔗 https://tracker.example.com/torrents/12345
🎞️ **IMDb:** `tt0409591`
📺 **TVDB:** `78857`
🎥 **TMDB:** `46260`
```

| Field | Source | Notes |
| --- | --- | --- |
| Title | `title` | Markdown characters are escaped. |
| Category | `category` / `torznab:attr category` | See [categories](#categories). |
| Size | `size` | Shown in the largest fitting unit: KiB, MiB, GiB or TiB. |
| Free | `downloadvolumefactor` | `(1 - factor) × 100`: `0` is 100%, `0.5` is 50%, `0.75` is 25%, `1` is 0%. |
| Tags | `torznab:attr tag` | Comma-separated, without spaces. Omitted when there are none. |
| Link | `comments` | |
| IMDb, TVDB, TMDB | `imdbid`/`imdb`, `tvdbid`/`tvdb`, `tmdbid`/`tmdb` | Only the ids the feed provides, one per line. |

### Categories

Category ids are mapped with the standard Newznab/Torznab ranges:

| Range | Name |
| --- | --- |
| 1000–1999 | Console |
| 2000–2999 | Movies |
| 3000–3999 | Audio |
| 4000–4999 | PC |
| 5000–5999 | TV |
| 6000–6999 | XXX |
| 7000–7999 | Books |
| 8000–8999 | Other |

Ids outside every range, such as the site-specific `100000+` ones, are ignored. If nothing maps, the category is `Undefined`. The ranges can be changed globally (`category_map`) and per feed (`categories`).

## Quick start

The image is published on Docker Hub as [`tyizqmr93eypp/torznab-to-telegram-announcer`](https://hub.docker.com/r/tyizqmr93eypp/torznab-to-telegram-announcer).

1. Store a configuration on your [Apprise API](https://github.com/caronc/apprise-api) server, with a tagged URL for each feed. See [`examples/apprise.example.yml`](examples/apprise.example.yml).
2. Create your `config.yml` from [`examples/config.example.yml`](examples/config.example.yml).
3. Run the image, mounting the configuration at `/config/config.yml` and a volume at `/data` so the database survives restarts. Pass the environment variables the configuration uses (see [Environment variables](#environment-variables)). The example configuration needs `MY_TRACKER_API_KEY` and `APPRISE_URL`; startup fails if one is missing.

   With Docker Compose:

   ```yaml
   services:
     announcer:
       image: tyizqmr93eypp/torznab-to-telegram-announcer:latest
       restart: unless-stopped
       environment:
         MY_TRACKER_API_KEY: replace-with-your-api-key
         APPRISE_URL: apprises://apprise.example.org
       volumes:
         - ./config.yml:/config/config.yml:ro
         - announcer-data:/data

   volumes:
     announcer-data:
   ```

   ```sh
   docker compose up -d
   ```

   Or with `docker run`:

   ```sh
   docker run -d --name torznab-to-telegram-announcer --restart unless-stopped \
     -e MY_TRACKER_API_KEY=replace-with-your-api-key \
     -e APPRISE_URL=apprises://apprise.example.org \
     -v "$PWD/config.yml:/config/config.yml:ro" \
     -v announcer-data:/data \
     tyizqmr93eypp/torznab-to-telegram-announcer:latest
   ```

The [`compose.yaml`](compose.yaml) in this repository does the same with the example configuration.

### User and permissions

The container starts as root, fixes the ownership of `/data`, then runs the announcer as `PUID:PGID`, which default to `1000:1000`. Set them as environment variables, for example to match the owner of a bind-mounted `/data`:

```yaml
environment:
  PUID: 1001
  PGID: 1001
```

The variables are named `PUID`/`PGID` rather than `UID`/`GID` because shells keep `UID` to themselves, which makes `${UID}` unreliable in Compose files.

If you start the container as another user instead (`user:` in Compose or `docker run --user`), `PUID`/`PGID` are ignored and `/data` must already be writable by that user.

## Configuration

The configuration is a YAML file, read from `--config` (or `$ANNOUNCER_CONFIG`, default `config.yml`). The Docker image uses `/config/config.yml`.

| Key | Description |
| --- | --- |
| `database` | SQLite file. Default: `announcer.sqlite3`. |
| `send_delay` | Seconds between two messages. Default: `3`. |
| `apprise.url` | Apprise API server, `apprise://` or `apprises://`. Credentials, a port and a path prefix are supported. |
| `category_map` | Optional. Replaces the default [category ranges](#categories). |
| `feeds` | One or more feeds, below. |

Each entry of `feeds`:

| Key | Description |
| --- | --- |
| `name` | Unique name. |
| `url` | Torznab URL. An in-line API key works. Query parameters such as `cat=2000,5000` are the tracker's own filters, sent as is; they are unrelated to `category_map` / `categories`, which only name the categories shown in messages. |
| `headers` | Optional HTTP headers, for example `X-Api-Key`. |
| `interval` | Polling interval: seconds, or `30s` / `10m` / `1h`. Default: `10m`. After failures the next attempt is delayed exponentially (up to one hour, never less than `interval`). |
| `timeout` | Request timeout in seconds. Default: `30`. |
| `apprise_config_id` | Configuration id stored on the Apprise API server. |
| `tag` | A tag, or a list of tags (any matches), selecting URLs in that configuration. |
| `categories` | Optional. Per-feed ranges that take precedence over `category_map` and extend it. Values are ids or `[low, high]` ranges. |

Command line: `torznab-to-telegram-announcer [--config PATH] [--log-level DEBUG|INFO|WARNING|ERROR]`.

### Logging

Logs are written to stderr (so `docker logs` shows them) with [loguru](https://github.com/Delgan/loguru); the standard `logging` output of libraries such as Apprise is routed through it. Two environment variables, which are not part of the YAML file, control it:

| Variable | Description |
| --- | --- |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Default: `INFO`. `--log-level` takes precedence. |
| `LOG_PATH` | Optional. Also write the log to this file, rotated at 100 MB and kept for 5 days. In Docker, point it into a mounted volume, for example `/data/announcer.log`. |

API keys and credentials are removed from every logged URL, at any level.

## Environment variables

To keep a secret out of the configuration file, write `${NAME}` where the value goes, and define the environment variable `NAME` for the announcer. `NAME` is whatever you choose: there is no automatic mapping from a setting's path (such as `feeds[0].headers.X-Api-Key`) to a variable name.

References work in any value, at any depth: `url`, `headers`, `apprise.url`, `database` and so on. Keys cannot use them.

| Syntax | Result |
| --- | --- |
| `${NAME}` | The value of `NAME`. Startup fails if it is not set. |
| `${NAME:-fallback}` | The value of `NAME`, or `fallback` if it is not set. |

For example, to send an API key as a header:

```yaml
feeds:
  - name: my-tracker
    url: https://tracker.example.com/api?t=search
    headers:
      X-Api-Key: ${MY_TRACKER_API_KEY}
```

How to define `MY_TRACKER_API_KEY` depends on how you run the announcer:

- **Docker Compose**: under `environment:` of the service. Every `${NAME}` used in the configuration must be listed there.

  ```yaml
  environment:
    MY_TRACKER_API_KEY: ${MY_TRACKER_API_KEY:?set MY_TRACKER_API_KEY}   # taken from your shell, or Compose's own .env file
    APPRISE_URL: apprises://apprise.example.org                # or a literal value
  ```

- **`docker run`**: `docker run -e MY_TRACKER_API_KEY=... -e APPRISE_URL=... ...`.
- **Local run**: export them in your shell first, for example `export MY_TRACKER_API_KEY=...` (`$env:MY_TRACKER_API_KEY = "..."` in PowerShell).

## Notifications

Messages go through an Apprise API server. A feed's `apprise_config_id` is a configuration id stored on that server, and its `tag` selects the tagged URLs in it. With

```yaml
apprise:
  url: apprises://apprise.example.org
feeds:
  - name: my-tracker
    apprise_config_id: torznab-announcer
    tag: my-tracker
```

the announcer notifies `apprises://apprise.example.org/torznab-announcer/?tags=my-tracker`.

Messages are sent as Markdown, and the Apprise API server converts them for each target. They are far below Telegram's 4096 character limit; if you ever need splitting, add `?overflow=split` to the URL in the stored configuration.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14.

```sh
uv sync
uv run pytest
uv run torznab-to-telegram-announcer --config examples/config.example.yml
```

[`examples/torznab.example.xml`](examples/torznab.example.xml) is a sample Torznab feed, used by the tests.
