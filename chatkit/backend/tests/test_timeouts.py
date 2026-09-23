"""Slow external card/deck APIs must get at least 30s before timing out.

Regression test: the 10s timeouts on the card-search endpoint and the
SWUStats deck/statistics calls cut slow responses off, leaving the agent
without verified card data so it falls back to prose suggestions.
"""
import unittest
from contextlib import contextmanager
from unittest.mock import patch, AsyncMock


class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs
        self.calls = []
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(text="<ul><li>Test Card</li></ul>")

    async def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(payload={})


@contextmanager
def fake_http():
    FakeClient.instances.clear()
    with patch("httpx.AsyncClient", FakeClient):
        yield


def recorded_timeouts():
    timeouts = []
    for client in FakeClient.instances:
        for call in client.calls:
            timeout = call.get("timeout", client.init_kwargs.get("timeout"))
            timeouts.append(timeout)
    return timeouts


class ExternalTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def assert_min_timeout(self, invoke, minimum=30):
        with fake_http():
            await invoke()
        timeouts = recorded_timeouts()
        self.assertTrue(timeouts, "expected at least one HTTP call")
        for timeout in timeouts:
            self.assertIsNotNone(timeout, "external call must set an explicit timeout")
            self.assertGreaterEqual(timeout, minimum)

    async def test_card_search_waits_for_slow_responses(self):
        from app.server import search_cards_direct as server_search
        from app.tools.card_search import search_cards_direct as tool_search
        from app.widgets import CardSearchWidget
        await self.assert_min_timeout(lambda: server_search("Luke"))
        await self.assert_min_timeout(lambda: tool_search("Luke"))
        await self.assert_min_timeout(lambda: CardSearchWidget().fetch_results("Luke"))

    async def test_deck_fetches_wait_for_slow_responses(self):
        from app.tools.deck_list import fetch_user_decks
        from app.tools.load_deck import fetch_deck_contents
        with patch("app.tools.deck_list.get_access_token", AsyncMock(return_value="tok")):
            await self.assert_min_timeout(lambda: fetch_user_decks())
        with patch("app.tools.load_deck.get_access_token", AsyncMock(return_value="tok")):
            await self.assert_min_timeout(lambda: fetch_deck_contents(1))

    async def test_statistics_wait_for_slow_responses(self):
        from app.swustats_stats import request
        await self.assert_min_timeout(lambda: request("Stats/CardMetaStatsAPI.php", {"format": "premier"}))


if __name__ == "__main__":
    unittest.main()
