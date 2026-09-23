"""Bulk deck saves to SWUStats plus the contents-diff used for undo."""
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import httpx

from app.swustats_write import push_deck_changes
from app.drafts import diff_contents


def _response(status, payload=None):
    return httpx.Response(status, json=payload or {}, request=httpx.Request("POST", "https://x"))


def _client(response=None, exc=None):
    client = AsyncMock()
    client.__aenter__.return_value = client
    if exc is not None:
        client.post.side_effect = exc
    else:
        client.post.return_value = response
    return client


class FakeSWU:
    """In-memory SWUStats deck server: applies pushed ops, serves refreshes."""

    def __init__(self, contents):
        self.contents = deepcopy(contents)
        self.pushed = []

    async def push(self, deck_id, ops, user_id="default"):
        self.pushed.append((deck_id, list(ops)))
        rows = {
            "main": self.contents.get("deck", []),
            "side": self.contents.get("sideboard", []),
        }
        for op in ops:
            table = rows[op["zone"]]
            row = next((c for c in table if str(c["id"]) == str(op["cardID"])), None)
            if op["action"] == "add":
                if row:
                    row["count"] += op["count"]
                else:
                    table.append({"id": op["cardID"], "name": op["cardID"], "count": op["count"]})
            else:
                if not row or row["count"] < op["count"]:
                    raise ValueError("Card not found in specified zone")
                row["count"] -= op["count"]
                if row["count"] <= 0:
                    table.remove(row)
        return {"success": True}

    async def fetch(self, deck_id, user_id="default"):
        return deepcopy(self.contents)


class PushTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.token = patch("app.swustats_write.get_access_token", AsyncMock(return_value="tok"))
        self.token.start()

    def tearDown(self):
        self.token.stop()

    async def _push(self, ops, response=None, exc=None):
        client = _client(response, exc)
        with patch("app.swustats_write.httpx.AsyncClient", return_value=client):
            return await push_deck_changes(7, ops), client

    async def test_success_posts_one_atomic_batch(self):
        ops = [{"action": "add", "cardID": "a", "count": 2, "zone": "main"}]
        data, client = await self._push(ops, _response(200, {"success": True, "deckID": 7}))
        self.assertTrue(data["success"])
        args, kwargs = client.post.call_args
        self.assertTrue(args[0].endswith("/EditDeckCards.php"))
        body = kwargs["json"]
        self.assertEqual(body["deckID"], 7)
        self.assertFalse(body["overwrite"])
        self.assertEqual(body["cards"], ops)

    async def test_empty_and_invalid_batches_rejected_locally(self):
        for bad in ([], [{"action": "add", "cardID": "a", "count": 1, "zone": "main"}] * 201,
                    [{"action": "oops", "cardID": "a", "count": 1, "zone": "main"}],
                    [{"action": "add", "cardID": "a", "count": 1, "zone": "nowhere"}],
                    [{"action": "add", "cardID": "a", "count": 0, "zone": "main"}],
                    [{"action": "add", "cardID": "", "count": 1, "zone": "main"}]):
            with self.assertRaises(ValueError):
                await push_deck_changes(7, bad)

    async def test_missing_token_asks_to_reconnect(self):
        with patch("app.swustats_write.get_access_token", AsyncMock(return_value=None)):
            with self.assertRaises(ValueError) as ctx:
                await push_deck_changes(7, [{"action": "add", "cardID": "a", "count": 1, "zone": "main"}])
        self.assertIn("Reconnect", str(ctx.exception))

    async def test_auth_failures_map_to_reconnect_or_owner(self):
        ops = [{"action": "add", "cardID": "a", "count": 1, "zone": "main"}]
        err = httpx.HTTPStatusError("m", request=httpx.Request("POST", "https://x"),
                                    response=_response(401))
        with self.assertRaises(ValueError) as ctx:
            await self._push(ops, exc=err)
        self.assertIn("Reconnect", str(ctx.exception))
        err = httpx.HTTPStatusError("m", request=httpx.Request("POST", "https://x"),
                                    response=_response(403, {"error": "insufficient_scope"}))
        with self.assertRaises(ValueError) as ctx:
            await self._push(ops, exc=err)
        self.assertIn("deck-edit permission", str(ctx.exception))
        err = httpx.HTTPStatusError("m", request=httpx.Request("POST", "https://x"),
                                    response=_response(403, {"error": "Not deck owner"}))
        with self.assertRaises(ValueError) as ctx:
            await self._push(ops, exc=err)
        self.assertIn("not owned", str(ctx.exception))

    async def test_refused_batch_reports_nothing_written(self):
        ops = [{"action": "remove", "cardID": "a", "count": 9, "zone": "main"}]
        err = httpx.HTTPStatusError("m", request=httpx.Request("POST", "https://x"),
                                    response=_response(404, {"error": "Card not found in specified zone"}))
        with self.assertRaises(ValueError) as ctx:
            await self._push(ops, exc=err)
        self.assertIn("nothing was written", str(ctx.exception))

    async def test_success_flag_required(self):
        with self.assertRaises(ValueError):
            await self._push([{"action": "add", "cardID": "a", "count": 1, "zone": "main"}],
                             _response(200, {"success": False}))


class DiffTests(unittest.TestCase):
    def test_diff_maps_sections_and_directions(self):
        old = {"deck": [{"id": "a", "count": 3}], "sideboard": [{"id": "b", "count": 2}]}
        new = {"deck": [{"id": "a", "count": 1}, {"id": "c", "count": 2}], "sideboard": []}
        self.assertEqual(diff_contents(old, new), [
            {"action": "remove", "cardID": "a", "count": 2, "zone": "main"},
            {"action": "add", "cardID": "c", "count": 2, "zone": "main"},
            {"action": "remove", "cardID": "b", "count": 2, "zone": "side"},
        ])

    def test_identical_contents_need_no_ops(self):
        contents = {"deck": [{"id": "a", "count": 1}], "sideboard": []}
        self.assertEqual(diff_contents(contents, deepcopy(contents)), [])


if __name__ == "__main__":
    unittest.main()
