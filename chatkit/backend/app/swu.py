"""Shared helpers for SWUStats requests.

Two concerns live here. SWUStats answers requests with non-browser user
agents using HTTP 403, so every request to its hosts must carry a browser
User-Agent. And every SWUStats request made by the assistant streams a
progress card into the chat (a workflow task): loading while the request
runs, complete with a human-readable summary afterwards, or complete with a
"Failed: " summary when the request fails. The chat renders the three
states with different indicators and shows the summary on hover.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

import httpx
from chatkit.types import CustomTask

if TYPE_CHECKING:
    from chatkit.agents import AgentContext

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
FAILED_PREFIX = "Failed: "
SWU_HEADERS = {"User-Agent": BROWSER_USER_AGENT}


def swu_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Async HTTP client for SWUStats hosts."""
    return httpx.AsyncClient(timeout=timeout, headers=SWU_HEADERS)


async def track_request(
    agent_ctx: AgentContext,
    title: str,
    call: Callable[[], Awaitable[Any]],
    describe: Callable[[Any], str],
) -> Any:
    """Run an external request while streaming a progress card for it.

    Adds a loading workflow task, awaits ``call``, then marks the task
    complete with ``describe(result)`` (or a "Failed: " summary). The
    workflow ends only once no task is still loading, so parallel
    requests cannot strand each other's cards. Exceptions from ``call``
    are reported on the card and re-raised unchanged. A failing
    ``describe`` or a vanished workflow never fails the call: the card
    falls back to a plain completion and the result is still returned.
    Contexts without workflow streaming (tests, non-agent callers) run
    the call directly with no card.
    """
    if not all(
        callable(getattr(agent_ctx, name, None))
        for name in ("add_workflow_task", "update_workflow_task", "end_workflow")
    ):
        return await call()
    task = CustomTask(title=title, status_indicator="loading")
    await agent_ctx.add_workflow_task(task)
    try:
        result = await call()
    except Exception as exc:
        await _finish_task(agent_ctx, task, title, f"{FAILED_PREFIX}{exc}")
        raise
    try:
        summary = describe(result)
    except Exception:
        summary = f"{title} finished."
    await _finish_task(agent_ctx, task, title, summary)
    return result


async def _finish_task(agent_ctx: AgentContext, task: CustomTask, title: str, content: str) -> None:
    """Mark one tracked task complete without stranding sibling requests.

    The task is located by identity so parallel requests cannot mislabel
    each other. If the workflow was already ended (for example by a
    finished sibling), the completion is streamed as its own entry
    instead of raising. The workflow ends only when nothing is still
    loading. Bookkeeping failures never propagate to the caller.
    """
    done = CustomTask(title=title, content=content, status_indicator="complete")
    try:
        tasks = agent_ctx.workflow_item.workflow.tasks
        index = next((i for i, existing in enumerate(tasks) if existing is task), len(tasks) - 1)
        await agent_ctx.update_workflow_task(done, index)
    except Exception:
        try:
            await agent_ctx.add_workflow_task(done)
        except Exception:
            return
    try:
        tasks = agent_ctx.workflow_item.workflow.tasks
        if not any(getattr(existing, "status_indicator", None) == "loading" for existing in tasks):
            await agent_ctx.end_workflow()
    except Exception:
        pass


def _summarize_names(values: list[str]) -> str:
    shown = values[:8]
    text = ", ".join(shown)
    if len(values) > 8:
        text += f" (+{len(values) - 8} more)"
    return text


def describe_cards(query: str, result: dict[str, Any]) -> str:
    """Hover payload for a card search progress card.

    Success renders as JSON with the query, count and per-card names plus
    art URLs; the UI shows it as a rich hover popup. Failures stay plain
    text so the card keeps its Failed styling.
    """
    import json
    if result.get("error"):
        return f"{FAILED_PREFIX}{result['error']}"
    cards = result.get("cards", [])
    if not cards:
        return f"No cards found for '{query}'."
    payload = {
        "query": query,
        "count": result.get("count", len(cards)),
        "cards": [
            {
                "name": (c.get("name") or "?") if isinstance(c, dict) else "?",
                "image": c.get("image") if isinstance(c, dict) else None,
                "id": c.get("id") if isinstance(c, dict) else None,
            }
            for c in cards
        ],
    }
    return json.dumps(payload)


def describe_decks(result: dict[str, Any]) -> str:
    """Human-readable summary of a saved-deck listing."""
    error = result.get("error")
    if error in ("not_authenticated", "token_expired"):
        return "SWUStats login needed to list saved decks."
    if error:
        return f"{FAILED_PREFIX}{error}"
    decks = result.get("decks", [])
    if not decks:
        return "No saved decks on SWUStats."
    names = [(d.get("name") or f"Deck {d.get('id')}") for d in decks]
    return f"Found {result.get('count', len(decks))} saved decks: {_summarize_names(names)}"


def describe_deck_contents(result: dict[str, Any]) -> str:
    """Human-readable summary of a loaded deck."""
    error = result.get("error")
    if error in ("not_authenticated", "token_expired"):
        return "SWUStats login needed to load this deck."
    if error:
        return f"{FAILED_PREFIX}{error}"
    main = result.get("deck", [])
    side = result.get("sideboard", [])
    name = result.get("metadata", {}).get("name", "deck")
    main_count = sum(c.get("count", 0) for c in main)
    side_count = sum(c.get("count", 0) for c in side)
    return (
        f"Loaded '{name}': {main_count} main-deck cards "
        f"({len(main)} unique), {side_count} sideboard."
    )


def describe_evidence(result: dict[str, Any]) -> str:
    """Human-readable summary of aggregate statistics evidence."""
    if not isinstance(result, dict) or result.get("error"):
        detail = result.get("error") if isinstance(result, dict) else "unavailable"
        return f"{FAILED_PREFIX}{detail}"
    cards = result.get("card_statistics", [])
    matchups = result.get("matchups", [])
    if not cards and not matchups and result.get("retrieved_at") is None:
        notice = (result.get("notices") or ["SWUStats statistics are temporarily unavailable."])[0]
        return f"{FAILED_PREFIX}{notice}"
    text = (
        f"Statistics ready: {len(cards)} card observations, "
        f"{len(matchups)} matchups ({result.get('window', 'all-time')})."
    )
    notices = [n for n in result.get("notices", [])][:2]
    if notices:
        text += " Notes: " + " ".join(notices)
    return text
