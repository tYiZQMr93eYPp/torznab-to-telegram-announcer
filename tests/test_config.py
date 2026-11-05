import pytest

from torznab_to_telegram_announcer.config import ConfigError, load_config

ENV = {"INDEXER_KEY": "x", "APPRISE_URL": "apprises://apprise.example.org"}

VALID = """
database: data/db.sqlite3
send_delay: 0
apprise:
  url: ${APPRISE_URL}
feeds:
  - name: my-tracker
    url: https://indexer.example.com/1/api?apikey=${INDEXER_KEY}&t=search
    interval: 10m
    apprise_config_id: torznab-announcer
    tag: my-tracker
    headers:
      X-Api-Key: ${HEADER_KEY:-fallback}
    categories:
      Anime: [[5070, 5070]]
      Documentary: 5080
  - name: other
    url: http://other.example/api
    interval: 90
    apprise_config_id: other_config
    tag: [a, b]
"""


def write(tmp_path, text):
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_a_valid_config(tmp_path):
    config = load_config(write(tmp_path, VALID), environ={**ENV, "INDEXER_KEY": "secret"})

    first, second = config.feeds
    assert first.url == "https://indexer.example.com/1/api?apikey=secret&t=search"
    assert first.interval == 600
    assert first.tag == ["my-tracker"]
    assert first.apprise_config_id == "torznab-announcer"
    assert config.apprise.url == "apprises://apprise.example.org"
    assert first.headers == {"X-Api-Key": "fallback"}
    assert first.categories == {"Anime": [(5070, 5070)], "Documentary": [(5080, 5080)]}
    assert second.interval == 90
    assert second.tag == ["a", "b"]
    assert config.category_map["TV"] == [(5000, 5999)]
    assert config.send_delay == 0


def test_relative_database_path_resolves_against_the_config_file(tmp_path):
    config = load_config(write(tmp_path, VALID), environ=ENV)

    assert config.database == tmp_path / "data" / "db.sqlite3"


def test_missing_environment_variable(tmp_path):
    with pytest.raises(ConfigError, match="INDEXER_KEY"):
        load_config(write(tmp_path, VALID), environ={"APPRISE_URL": ENV["APPRISE_URL"]})

    with pytest.raises(ConfigError, match="APPRISE_URL"):
        load_config(write(tmp_path, VALID), environ={"INDEXER_KEY": "x"})


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yml")


def test_invalid_apprise_url_and_config_id(tmp_path):
    text = VALID.replace("${APPRISE_URL}", "https://apprise.example.org")
    text = text.replace("apprise_config_id: other_config", "apprise_config_id: not valid!")

    with pytest.raises(ConfigError) as error:
        load_config(write(tmp_path, text), environ=ENV)

    assert "apprise.url" in str(error.value)
    assert "apprise_config_id" in str(error.value)


def test_duplicate_feed_names(tmp_path):
    text = VALID.replace("name: other", "name: my-tracker")

    with pytest.raises(ConfigError, match="duplicate feed names"):
        load_config(write(tmp_path, text), environ=ENV)


def test_invalid_values(tmp_path):
    text = VALID.replace("interval: 10m", "interval: soon").replace("http://other", "ftp://other")

    with pytest.raises(ConfigError) as error:
        load_config(write(tmp_path, text), environ=ENV)

    assert "interval" in str(error.value)
    assert "http(s)" in str(error.value)


def test_unknown_keys_are_rejected(tmp_path):
    with pytest.raises(ConfigError, match="intervall"):
        load_config(
            write(tmp_path, VALID.replace("interval: 90", "intervall: 90")),
            environ=ENV,
        )
