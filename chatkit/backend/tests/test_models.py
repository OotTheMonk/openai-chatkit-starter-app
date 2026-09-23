"""Model selector: registry, availability gating, per-thread selection."""
import os
import unittest
from unittest.mock import patch

from app import models
from app.models import (
    agent_for,
    available_models,
    is_available,
    model_for,
    resolve_model,
    set_model,
)

OPENAI_ENV = {"OPENAI_API_KEY": "test-openai-key"}
META_ENV = {"OPENAI_API_KEY": "test-openai-key", "LLAMA_API_KEY": "test-llama-key"}
OPENROUTER_ENV = {"OPENAI_API_KEY": "test-openai-key", "OPENROUTER_API_KEY": "test-or-key"}


class RegistryTests(unittest.TestCase):
    def test_registry_lists_openai_and_meta_without_secrets(self):
        with patch.dict(os.environ, META_ENV, clear=False):
            entries = available_models()
        ids = [e["id"] for e in entries]
        self.assertIn("gpt-4o", ids)
        self.assertIn("gpt-4o-mini", ids)
        self.assertTrue(any(e["provider"] == "meta" for e in entries))
        blob = str(entries)
        self.assertNotIn("test-openai-key", blob)
        self.assertNotIn("test-llama-key", blob)

    def test_meta_unavailable_without_key(self):
        env = {"OPENAI_API_KEY": "test-openai-key"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(any(e["provider"] == "meta" and e["available"] for e in available_models()))
            self.assertTrue(is_available("gpt-4o-mini"))

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            is_available("nope")

    def test_openrouter_lists_free_models_without_secrets(self):
        with patch.dict(os.environ, OPENROUTER_ENV, clear=False):
            entries = available_models()
        free = [e for e in entries if e["provider"] == "openrouter"]
        self.assertTrue(free)
        self.assertTrue(all(e["available"] for e in free))
        self.assertIn("openrouter-free-router", [e["id"] for e in free])
        self.assertTrue(
            all(
                ":free" in models._entry(e["id"])["model"]
                or models._entry(e["id"])["model"] == "openrouter/free"
                for e in free
            )
        )
        self.assertNotIn("test-or-key", str(entries))

    def test_openrouter_unavailable_without_key(self):
        with patch.dict(os.environ, OPENAI_ENV, clear=True):
            self.assertFalse(
                any(e["provider"] == "openrouter" and e["available"] for e in available_models())
            )
            self.assertFalse(is_available("gpt-oss-120b-free"))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self._default = models._global_default_id
        self._threads = dict(models._per_thread_id)

    def tearDown(self):
        models._global_default_id = self._default
        models._per_thread_id.clear()
        models._per_thread_id.update(self._threads)

    def test_select_and_resolve_thread_model(self):
        with patch.dict(os.environ, OPENAI_ENV, clear=True):
            self.assertEqual(set_model("t1", "gpt-4o-mini"), "gpt-4o-mini")
            self.assertEqual(model_for("t1"), "gpt-4o-mini")
            self.assertEqual(model_for("new-thread"), "gpt-4o-mini")

    def test_unavailable_model_rejected_with_key_hint(self):
        with patch.dict(os.environ, OPENAI_ENV, clear=True):
            with self.assertRaises(ValueError) as ctx:
                set_model("t1", "llama-4-maverick")
            self.assertIn("LLAMA_API_KEY", str(ctx.exception))

    def test_meta_selectable_with_key(self):
        with patch.dict(os.environ, META_ENV, clear=False):
            self.assertEqual(set_model("t9", "llama-4-scout"), "llama-4-scout")
            self.assertEqual(model_for("t9"), "llama-4-scout")

    def test_openrouter_selectable_with_key(self):
        with patch.dict(os.environ, OPENROUTER_ENV, clear=True):
            self.assertEqual(set_model("t-or", "qwen3-coder-free"), "qwen3-coder-free")
            self.assertEqual(model_for("t-or"), "qwen3-coder-free")

    def test_openrouter_rejected_without_key_hint(self):
        with patch.dict(os.environ, OPENAI_ENV, clear=True):
            with self.assertRaises(ValueError) as ctx:
                set_model("t-or", "qwen3-coder-free")
            self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))


class ResolveTests(unittest.TestCase):
    def test_openai_resolves_to_model_name(self):
        with patch.dict(os.environ, OPENAI_ENV, clear=True):
            self.assertEqual(resolve_model("gpt-4o-mini"), "gpt-4o-mini")

    def test_meta_resolves_to_compat_client(self):
        with patch.dict(os.environ, META_ENV, clear=False):
            model = resolve_model("llama-4-maverick")
            self.assertEqual(model.model, "Llama-4-Maverick-17B-128E-Instruct-FP8")

    def test_openrouter_resolves_to_compat_client(self):
        with patch.dict(os.environ, OPENROUTER_ENV, clear=True):
            model = resolve_model("gpt-oss-120b-free")
            self.assertEqual(model.model, "openai/gpt-oss-120b:free")

    def test_openrouter_free_router_resolves(self):
        with patch.dict(os.environ, OPENROUTER_ENV, clear=True):
            self.assertEqual(set_model("t-orr", "openrouter-free-router"), "openrouter-free-router")
            self.assertEqual(resolve_model("openrouter-free-router").model, "openrouter/free")


class ModelsEndpointTests(unittest.TestCase):
    def test_models_endpoint_lists_router_without_thread(self):
        import json

        from app.main import list_models

        with patch.dict(os.environ, OPENROUTER_ENV, clear=True):
            payload = json.loads(list_models().body)
        ids = [e["id"] for e in payload["models"]]
        self.assertIn("openrouter-free-router", ids)
        self.assertIn(payload["active"], ids)
        self.assertNotIn("test-or-key", str(payload))

    def test_agent_for_threads_without_shared_mutation(self):
        from app.server import assistant_agent

        with patch.dict(os.environ, OPENAI_ENV, clear=True):
            models._per_thread_id.clear()
            agent = agent_for("t1")
            self.assertEqual(agent.model, "gpt-4o")
            self.assertEqual(agent.tools, assistant_agent.tools)
            self.assertEqual(assistant_agent.model, "gpt-4o")


if __name__ == "__main__":
    unittest.main()
