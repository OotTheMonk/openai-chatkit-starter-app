import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.oauth import OAuthConfig, OAuthService, OAuthToken, OAuthTokenStore
from app.tools.deck_list import fetch_user_decks, get_user_decks_tool


class AccountConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = OAuthTokenStore(Path(self.temp.name) / "tokens.json")
        self.service = OAuthService(OAuthConfig(
            client_id="test", client_secret="test",
            authorize_url="https://provider.example/authorize",
            token_url="https://provider.example/token",
            userinfo_url="https://provider.example/userinfo",
            redirect_uri="https://callback.example/oauth/callback",
        ), self.store)

    def tearDown(self):
        self.temp.cleanup()

    async def test_expired_refresh_failure_offers_connection(self):
        self.store.set(OAuthToken("expired", "refresh", expires_at=time.time() - 10))
        with patch("app.main.is_oauth_configured", return_value=True), \
             patch("app.oauth.get_oauth_service", return_value=self.service), \
             patch.object(self.service, "refresh_token", AsyncMock(return_value=None)):
            with TestClient(app) as client:
                result = client.get("/oauth/status").json()
        self.assertFalse(result["authenticated"])
        self.assertEqual(result["login_url"], "/oauth/login")

    async def test_login_returns_to_local_app_with_tunneled_callback(self):
        with patch("app.main.is_oauth_configured", return_value=True), \
             patch("app.oauth.get_oauth_service", return_value=self.service):
            with TestClient(app, base_url="http://localhost:8000") as client:
                response = client.get("/oauth/login", follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertIn("callback.example", response.headers["location"])
                self.assertEqual(self.service._redirect_urls["default"], "http://localhost:8000/")
                with patch.object(self.service, "exchange_code", AsyncMock(return_value=OAuthToken("test"))):
                    callback = client.get("/oauth/callback?code=test")
                self.assertIn("http://localhost:8000/", callback.text)
                self.assertEqual(client.get("/oauth/login?redirect_to=//evil.example").status_code, 400)

    async def test_missing_account_tool_links_to_request_origin(self):
        context = SimpleNamespace(context=SimpleNamespace(request_context={
            "request": SimpleNamespace(base_url="http://localhost:8000/")
        }))
        with patch("app.tools.deck_list.get_access_token", AsyncMock(return_value=None)):
            result = await get_user_decks_tool.on_invoke_tool(context, "{}")
        self.assertIn("http://localhost:8000/oauth/login", result)
        self.assertNotIn("ngrok", result)

    async def test_connected_decks_are_loaded_and_streamed(self):
        decks = [{"id": 7, "name": "Test deck", "is_favorite": True}]
        response = httpx.Response(200, json={"decks": decks}, request=httpx.Request("GET", "https://provider.example/decks"))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        context = SimpleNamespace(context=SimpleNamespace(request_context={}, stream_widget=AsyncMock()))
        with patch("app.tools.deck_list.get_access_token", AsyncMock(return_value="test")), \
             patch("app.tools.deck_list.httpx.AsyncClient", return_value=client):
            result = await get_user_decks_tool.on_invoke_tool(context, "{}")
        self.assertEqual(result, "Found 1 deck list(s).")
        context.context.stream_widget.assert_awaited_once()

    async def test_provider_401_requires_reconnection(self):
        response = httpx.Response(401, request=httpx.Request("GET", "https://provider.example/decks"))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        with patch("app.tools.deck_list.get_access_token", AsyncMock(return_value="test")), \
             patch("app.tools.deck_list.httpx.AsyncClient", return_value=client):
            result = await fetch_user_decks()
        self.assertEqual(result["error"], "token_expired")

    async def test_library_endpoint_requires_connected_account(self):
        with patch("app.tools.deck_list.fetch_user_decks", AsyncMock(return_value={
            "decks": [], "count": 0, "error": "not_authenticated"
        })):
            with TestClient(app) as client:
                response = client.get("/api/decks")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "not_authenticated")

    async def test_library_endpoint_returns_saved_decks(self):
        decks = [{"id": 7, "name": "Test deck", "is_favorite": True}]
        with patch("app.tools.deck_list.fetch_user_decks", AsyncMock(return_value={
            "decks": decks, "count": 1, "error": None
        })):
            with TestClient(app) as client:
                response = client.get("/api/decks")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decks"], decks)


if __name__ == "__main__":
    unittest.main()
