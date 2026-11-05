from types import SimpleNamespace

import pytest
import requests

from torznab_to_telegram_announcer.notifier import AppriseNotifier, NotifierError, build_url


class FakeApi(list):
    status_code = 200


@pytest.fixture
def api(monkeypatch):
    """Capture what is POSTed to the Apprise API server."""
    calls = FakeApi()

    def fake_post(url, data=None, **kwargs):
        calls.append(SimpleNamespace(url=url, payload=data, headers=kwargs.get("headers", {})))
        response = requests.Response()
        response.status_code = calls.status_code
        response._content = b"{}"
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


def test_build_url():
    assert (
        build_url("apprises://apprise.example.org", "torznab-announcer", ["my-tracker"])
        == "apprises://apprise.example.org/torznab-announcer/?tags=my-tracker"
    )
    assert (
        build_url("apprise://user:pw@host:8000/prefix/", "cfg", ["a", "b"])
        == "apprise://user:pw@host:8000/prefix/cfg/?tags=a%2Cb"
    )


async def test_message_is_posted_to_the_api_with_config_id_and_tags(api):
    notifier = AppriseNotifier("apprises://apprise.example.org")

    sent = await notifier.send("torznab-announcer", ["my-tracker"], "**hello**")

    assert sent is True
    (call,) = api
    assert call.url == "https://apprise.example.org/notify"
    assert call.headers["X-Apprise-Config-ID"] == "torznab-announcer"
    assert call.payload["tag"] == ["my-tracker"]
    assert call.payload["format"] == "markdown"
    assert call.payload["body"] == "**hello**"


async def test_each_feed_can_use_its_own_config_id_and_tags(api):
    notifier = AppriseNotifier("apprises://apprise.example.org")

    await notifier.send("one", ["a"], "x")
    await notifier.send("two", ["b", "c"], "y")

    assert [(c.headers["X-Apprise-Config-ID"], c.payload["tag"]) for c in api] == [
        ("one", ["a"]),
        ("two", ["b", "c"]),
    ]


async def test_rejected_notification_returns_false(api):
    api.status_code = 424
    notifier = AppriseNotifier("apprise://apprise.example.org")

    assert await notifier.send("cfg", ["a"], "x") is False


def test_invalid_url_is_rejected():
    with pytest.raises(NotifierError, match="not a valid Apprise API URL"):
        AppriseNotifier("apprises://").prepare("cfg", ["a"])
