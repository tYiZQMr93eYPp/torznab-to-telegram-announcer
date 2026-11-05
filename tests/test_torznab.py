from datetime import UTC, datetime
from decimal import Decimal

import pytest

from torznab_to_telegram_announcer.torznab import TorznabError, parse_feed, redact_url


def by_title(releases, prefix):
    return next(release for release in releases if release.title.startswith(prefix))


def test_parses_all_items_of_the_example_feed(example_xml):
    releases = parse_feed(example_xml)

    assert len(releases) == 100
    assert len({release.key for release in releases}) == 100


def test_extracts_the_required_fields(example_xml):
    release = by_title(parse_feed(example_xml), "Naruto S01 ")

    assert release.url == "https://tracker.example.com/torrents/18313"
    assert release.key == release.url
    assert release.size == 5038126562
    assert release.category_ids == (5000, 100002)
    assert release.tags == ("internal", "freeleech", "doubleupload")
    assert release.imdb_id == "0409591"
    assert release.tvdb_id == "78857"
    assert release.tmdb_id == "46260"
    assert release.download_factor == Decimal(0)
    assert release.upload_factor == Decimal(2)
    assert release.published.tzinfo is not None


def test_published_is_normalised_to_utc(example_xml):
    release = by_title(parse_feed(example_xml), "Naruto S05 ")

    assert release.published == datetime(2026, 11, 5, 10, 35, 44, tzinfo=UTC)


def test_missing_ids_and_tags_are_empty(example_xml):
    releases = parse_feed(example_xml)

    assert any(release.tvdb_id is None for release in releases)
    assert any(release.imdb_id is None for release in releases)
    assert any(release.tags == () for release in releases)


def test_guid_is_never_exposed(example_xml):
    for release in parse_feed(example_xml):
        assert "this-is-the-users-rss-key" not in repr(release)


def item(body: str) -> bytes:
    return (
        '<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">'
        f"<channel><item><title>T</title>{body}</item></channel></rss>"
    ).encode()


def test_id_attribute_aliases_and_normalisation():
    (release,) = parse_feed(
        item(
            "<comments>https://x/1</comments>"
            '<torznab:attr name="imdbid" value="tt0409591"/>'
            '<torznab:attr name="tvdb" value="78857"/>'
            '<torznab:attr name="tmdb" value="0"/>'
        )
    )

    assert release.imdb_id == "0409591"
    assert release.tvdb_id == "78857"
    assert release.tmdb_id is None


def test_defaults_when_attributes_are_missing():
    (release,) = parse_feed(item("<comments>https://x/1</comments>"))

    assert release.download_factor == Decimal(1)
    assert release.upload_factor == Decimal(1)
    assert release.size is None
    assert release.category_ids == ()


def test_falls_back_to_hashed_guid_without_comments():
    (release,) = parse_feed(item("<guid>https://x/download/1.secretkey</guid>"))

    assert release.url is None
    assert release.key.startswith("guid-sha256:")
    assert "secretkey" not in release.key


def test_items_without_any_identifier_are_skipped():
    assert parse_feed(item("")) == []


def test_comma_separated_tags_and_size_from_enclosure():
    (release,) = parse_feed(
        item(
            "<comments>https://x/1</comments>"
            '<enclosure url="https://x/d" length="1234" type="application/x-bittorrent"/>'
            '<torznab:attr name="tag" value="Internal, freeleech"/>'
        )
    )

    assert release.tags == ("internal", "freeleech")
    assert release.size == 1234


def test_torznab_error_document():
    with pytest.raises(TorznabError, match="100.*Incorrect user credentials"):
        parse_feed(b'<error code="100" description="Incorrect user credentials"/>')


def test_rejects_non_rss_and_invalid_xml():
    with pytest.raises(TorznabError):
        parse_feed(b"<html></html>")
    with pytest.raises(TorznabError):
        parse_feed(b"not xml")


def test_rejects_entity_expansion():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss>&a;</rss>'

    with pytest.raises(TorznabError):
        parse_feed(bomb)


def test_redact_url_hides_query_values():
    url = "https://host.example/api?apikey=SECRET&t=search"

    assert redact_url(url) == "https://host.example/api?apikey=***&t=***"


def test_redact_url_keeps_the_port_and_drops_credentials():
    assert (
        redact_url("http://user:pw@127.0.0.1:9696/1/api?apikey=SECRET")
        == "http://127.0.0.1:9696/1/api?apikey=***"
    )
    assert redact_url("http://[::1]:8080/api") == "http://[::1]:8080/api"
