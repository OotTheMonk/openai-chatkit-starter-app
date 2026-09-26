import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def _item(payload):
    return SimpleNamespace(model_dump=lambda mode="json": dict(payload))


class ConversationItemsTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_list_content_normalized_to_list(self):
        ok = {"id": "msg_1", "thread_id": "t", "type": "assistant_message",
              "content": [{"type": "output_text", "text": "hi"}]}
        poison = {"id": "shcx_1", "thread_id": "t", "type": "sdk_hidden_context",
                  "content": "The user cancelled the stream."}
        page = SimpleNamespace(data=[ok, poison])
        store = SimpleNamespace(load_thread_items=AsyncMock(return_value=page))
        with patch("app.main.chatkit_server", SimpleNamespace(store=store)):
            with TestClient(app) as client:
                result = client.get("/api/conversations/t").json()
        self.assertEqual(result[0]["content"], [])
        self.assertEqual(result[1]["content"], [{"type": "output_text", "text": "hi"}])


if __name__ == "__main__":
    unittest.main()
