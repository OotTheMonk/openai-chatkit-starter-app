"""Selectable chat models.

OpenAI models run on the existing OPENAI_API_KEY. Meta Llama models run
through Meta's OpenAI-compatible API and need a separate LLAMA_API_KEY
(Meta billing is separate from any OpenAI plan). OpenRouter models run
through OpenRouter's OpenAI-compatible API and need OPENROUTER_API_KEY
(get one at https://openrouter.ai/keys); the wired entries use free
(:free) models so they cost nothing, though OpenRouter rotates free
availability. Entries without their key are reported unavailable so the
UI can hide or disable them; only key presence is ever exposed, never
values.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Any

from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

DEFAULT_MODEL_ID = "gpt-4o"
META_API_BASE = "https://api.llama.com/compat/v1/"
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

REGISTRY: list[dict[str, str]] = [
    {
        "id": "gpt-4o",
        "label": "GPT-4o",
        "provider": "openai",
        "model": "gpt-4o",
        "needs_key": "OPENAI_API_KEY",
        "hint": "Best tool calling",
    },
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o Mini",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "needs_key": "OPENAI_API_KEY",
        "hint": "Cheaper and faster; lighter on rate limits",
    },
    {
        "id": "llama-4-maverick",
        "label": "Llama 4 Maverick (Meta)",
        "provider": "meta",
        "model": "Llama-4-Maverick-17B-128E-Instruct-FP8",
        "needs_key": "LLAMA_API_KEY",
        "hint": "Needs LLAMA_API_KEY in backend/.env",
    },
    {
        "id": "llama-4-scout",
        "label": "Llama 4 Scout (Meta)",
        "provider": "meta",
        "model": "Llama-4-Scout-17B-16E-Instruct-FP8",
        "needs_key": "LLAMA_API_KEY",
        "hint": "Needs LLAMA_API_KEY in backend/.env",
    },
    {
        "id": "gpt-oss-120b-free",
        "label": "GPT-OSS 120B (OpenRouter free)",
        "provider": "openrouter",
        "model": "openai/gpt-oss-120b:free",
        "needs_key": "OPENROUTER_API_KEY",
        "hint": "Free via OpenRouter; needs OPENROUTER_API_KEY in backend/.env",
    },
    {
        "id": "qwen3-coder-free",
        "label": "Qwen3 Coder (OpenRouter free)",
        "provider": "openrouter",
        "model": "qwen/qwen3-coder:free",
        "needs_key": "OPENROUTER_API_KEY",
        "hint": "Free via OpenRouter; needs OPENROUTER_API_KEY in backend/.env",
    },
    {
        "id": "openrouter-free-router",
        "label": "OpenRouter Free Router",
        "provider": "openrouter",
        "model": "openrouter/free",
        "needs_key": "OPENROUTER_API_KEY",
        "hint": "Auto-routes to a free model; underlying model may vary per request",
    },
]

_global_default_id = DEFAULT_MODEL_ID
_per_thread_id: dict[str, str] = {}


def _entry(model_id: str) -> dict[str, str]:
    for entry in REGISTRY:
        if entry["id"] == model_id:
            return entry
    raise ValueError(f"Unknown model '{model_id}'.")


def is_available(model_id: str) -> bool:
    """A model is selectable only when its provider key is configured."""
    return bool(os.getenv(_entry(model_id)["needs_key"]))


def available_models() -> list[dict[str, Any]]:
    """Registry for the UI: ids, labels and availability. Never key values."""
    return [
        {
            "id": e["id"],
            "label": e["label"],
            "provider": e["provider"],
            "hint": e["hint"],
            "available": is_available(e["id"]),
        }
        for e in REGISTRY
    ]


def set_model(thread_id: str | None, model_id: str) -> str:
    """Select a model; also becomes the default for new conversations."""
    global _global_default_id
    entry = _entry(model_id)
    if not is_available(model_id):
        raise ValueError(
            f"{entry['label']} needs {entry['needs_key']} set in backend/.env before it can be used."
        )
    if thread_id:
        _per_thread_id[thread_id] = model_id
    _global_default_id = model_id
    return model_id


def model_for(thread_id: str | None) -> str:
    """Active model id for a thread, falling back to the global default."""
    for candidate in (_per_thread_id.get(thread_id or ""), _global_default_id, DEFAULT_MODEL_ID):
        if candidate:
            try:
                if is_available(candidate):
                    return candidate
            except ValueError:
                continue
    raise ValueError("No chat model is configured: set OPENAI_API_KEY in backend/.env.")


def resolve_model(model_id: str) -> Any:
    """Build the Agents SDK model for a registry id."""
    entry = _entry(model_id)
    if entry["provider"] == "openai":
        return entry["model"]
    api_key = os.getenv(entry["needs_key"])
    if not api_key:
        raise ValueError(
            f"{entry['label']} needs {entry['needs_key']} set in backend/.env before it can be used."
        )
    if entry["provider"] == "openrouter":
        base_url = os.getenv("OPENROUTER_API_BASE", OPENROUTER_API_BASE)
        return OpenAIChatCompletionsModel(
            model=entry["model"],
            openai_client=AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                default_headers={
                    "HTTP-Referer": os.getenv("SERVER_BASE_URL", "http://localhost:8000"),
                    "X-Title": "ChatKit Deck Builder",
                },
            ),
        )
    base_url = os.getenv("META_API_BASE", META_API_BASE)
    return OpenAIChatCompletionsModel(
        model=entry["model"],
        openai_client=AsyncOpenAI(base_url=base_url, api_key=api_key),
    )


def agent_for(thread_id: str | None) -> Any:
    """The shared assistant with this thread's model applied (no shared mutation)."""
    from .server import assistant_agent

    return dataclasses.replace(assistant_agent, model=resolve_model(model_for(thread_id)))
