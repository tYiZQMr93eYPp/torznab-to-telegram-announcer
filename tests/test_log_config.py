import logging

import pytest
from loguru import logger

from torznab_to_telegram_announcer.log_config import LogConfig


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    logger.remove()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_level_comes_from_the_argument_then_the_environment(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")

    assert LogConfig().level == "WARNING"
    assert LogConfig(level="debug").level == "DEBUG"

    monkeypatch.delenv("LOG_LEVEL")
    assert LogConfig().level == "INFO"


def test_log_path_comes_from_the_argument_then_the_environment(monkeypatch):
    monkeypatch.setenv("LOG_PATH", "/env.log")

    assert LogConfig().log_path == "/env.log"
    assert LogConfig(log_path="/arg.log").log_path == "/arg.log"

    monkeypatch.delenv("LOG_PATH")
    assert LogConfig().log_path is None


def test_stdlib_logging_is_routed_to_the_log_file(tmp_path):
    log_file = tmp_path / "logs" / "announcer.log"
    LogConfig(level="INFO", log_path=str(log_file)).configure()

    logging.getLogger("some.module").info("hello from stdlib")
    logging.getLogger("some.module").debug("too verbose")
    logger.complete()

    content = log_file.read_text(encoding="utf-8")
    assert "hello from stdlib" in content
    assert "too verbose" not in content


def test_no_file_is_written_without_a_log_path(tmp_path, monkeypatch):
    monkeypatch.delenv("LOG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    LogConfig().configure()
    logging.getLogger("x").warning("console only")
    logger.complete()

    assert list(tmp_path.iterdir()) == []
