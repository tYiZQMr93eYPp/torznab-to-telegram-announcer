from decimal import Decimal

import pytest

from torznab_to_telegram_announcer.categories import DEFAULT_CATEGORY_RANGES
from torznab_to_telegram_announcer.formatting import (
    escape_markdown,
    format_percentage,
    format_release,
    format_size,
    free_percentage,
)
from torznab_to_telegram_announcer.models import Release
from torznab_to_telegram_announcer.torznab import parse_feed


def render(release):
    return format_release(release, DEFAULT_CATEGORY_RANGES)


def test_freeleech_double_upload_tv_release(example_xml):
    release = next(r for r in parse_feed(example_xml) if r.title.startswith("Naruto S01 "))

    assert render(release) == (
        "📺 **Naruto S01 2002 NF WEB\\-DL H\\.264 MULTI AAC LC 2\\.0\\-GROUP Spanish**\n"
        "\n"
        "📂 **Category:** TV\n"
        "💾 **Size:** 4.69 GiB\n"
        "💸 **Free:** 100%\n"
        "🏷️ **Tags:** `internal,freeleech,doubleupload`\n"
        "🔗 <https://tracker.example.com/torrents/18313>\n"
        "🎞️ **IMDb:** `tt0409591`\n"
        "📺 **TVDB:** `78857`\n"
        "🎥 **TMDB:** `46260`"
    )


def test_halfleech_movie_without_tvdb(example_xml):
    release = next(r for r in parse_feed(example_xml) if r.title.startswith("Ninja Turtles"))
    message = render(release)

    assert message.startswith("🎬 **Ninja Turtles: Fuera de las sombras 2016")
    assert "📂 **Category:** Movies" in message
    assert "💾 **Size:** 12.32 GiB" in message
    assert "💸 **Free:** 50%" in message
    assert "`internal,halfleech`" in message
    assert "IMDb:** `tt3949660`" in message
    assert "TMDB:** `308531`" in message
    assert "TVDB" not in message


def test_minimal_release_omits_optional_lines():
    release = Release(
        key="k",
        title="Plain",
        url=None,
        size=None,
        category_ids=(100001,),
        tags=(),
        imdb_id=None,
        tvdb_id=None,
        tmdb_id=None,
        download_factor=Decimal(1),
        upload_factor=Decimal(1),
        published=None,
    )

    assert render(release) == "📦 **Plain**\n\n📂 **Category:** Undefined\n💸 **Free:** 0%"


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.00 KiB"),
        (1024**2, "1.00 MiB"),
        (5 * 1024**2 + 512 * 1024, "5.50 MiB"),
        (1024**3, "1.00 GiB"),
        (70425821171, "65.59 GiB"),
        (3 * 1024**4, "3.00 TiB"),
    ],
)
def test_format_size(size, expected):
    assert format_size(size) == expected


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        ("0", "100%"),
        ("0.5", "50%"),
        ("0.75", "25%"),
        ("0.25", "75%"),
        ("1", "0%"),
        ("1.0", "0%"),
        ("2", "0%"),
        ("0.333", "66.7%"),
    ],
)
def test_free_percentage(factor, expected):
    assert format_percentage(free_percentage(Decimal(factor))) == expected


def test_markdown_in_titles_is_escaped():
    title = "A_B*C [D] (E) `F` <G> & H~I"

    assert escape_markdown(title) == "A\\_B\\*C \\[D\\] \\(E\\) \\`F\\` \\<G\\> \\& H\\~I"
