"""Persist committed deck changes to SWUStats.

Reads stay local-first, but every committed mutation of a linked deck
(applies, removals, undos) is written through the atomic bulk endpoint
POST /TCGEngine/APIs/EditDeckCards.php and then re-read, so the server
stays the source of truth. Undo itself is tracked locally as content
snapshots; reverting one means diffing back to the snapshot and pushing
that diff. Local drafts (no linked deck) never touch this module.
"""
from __future__ import annotations

import logging
from typing import Any

# httpx is re-exported from .swu so tests can patch httpx.AsyncClient here.
from .config import get_access_token, SWUSTATS_API_BASE
from .swu import httpx, SWU_HEADERS

logger = logging.getLogger(__name__)

MAX_BATCH = 200


def _save_error(status: int, detail: str) -> str:
    lowered = (detail or "").lower()
    if status == 401:
        return "Reconnect SWUStats to save deck changes; the login expired."
    if status == 403 and "scope" in lowered:
        return "Reconnect SWUStats to grant deck-edit permission, then try again."
    if status == 403:
        return "This deck is not owned by your SWUStats account; saving is disabled."
    if status in (400, 404):
        return f"SWUStats refused the save ({detail or 'change unsatisfiable'}); nothing was written."
    return f"SWUStats refused the save (HTTP {status}); nothing was written."


async def push_deck_changes(
    deck_id: int,
    ops: list[dict[str, Any]],
    user_id: str = "default",
) -> dict[str, Any]:
    """Write one atomic batch of card changes to a deck you own.

    Each op is {action: "add"|"remove", cardID: str, count: int, zone: "main"|"side"}.
    Returns the decoded response. Raises ValueError with a human-readable
    message when the save cannot happen; failed saves write nothing.
    """
    if not ops:
        raise ValueError("Nothing to save.")
    if len(ops) > MAX_BATCH:
        raise ValueError(f"Too many changes for one save (max {MAX_BATCH}); split the proposal.")
    for op in ops:
        if op.get("action") not in ("add", "remove"):
            raise ValueError(f"Invalid save action {op.get('action')!r}; use 'add' or 'remove'.")
        if op.get("zone") not in ("main", "side"):
            raise ValueError(f"Invalid save zone {op.get('zone')!r}; use 'main' or 'side'.")
        if not isinstance(op.get("count"), int) or op["count"] < 1:
            raise ValueError(f"Invalid save count {op.get('count')!r}; use a positive integer.")
        if not op.get("cardID"):
            raise ValueError("Save entries need a cardID.")
    access_token = await get_access_token(user_id)
    if not access_token:
        raise ValueError("Reconnect SWUStats to save deck changes.")
    body = {
        "access_token": access_token,
        "deckID": deck_id,
        "overwrite": False,
        "cards": [
            {"action": op["action"], "cardID": str(op["cardID"]), "count": op["count"], "zone": op["zone"]}
            for op in ops
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=SWU_HEADERS) as client:
            resp = await client.post(f"{SWUSTATS_API_BASE}/EditDeckCards.php", json=body, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            data = e.response.json() or {}
        except Exception:
            data = {}
        detail = str(data.get("error") or "")
        where = " ".join(f"{k}={data[k]}" for k in ("cardID", "zone", "index") if data.get(k) is not None)
        if where:
            detail = f"{detail} ({where})" if detail else where
        logger.warning(f"Deck save refused (HTTP {status}): {detail or e} | deck={deck_id} ops={ops}")
        raise ValueError(_save_error(status, detail)) from e
    except Exception as e:
        logger.error(f"Error saving deck {deck_id}: {e}", exc_info=True)
        raise ValueError(f"Could not save to SWUStats ({e}); nothing was written.") from e
    if not isinstance(data, dict) or data.get("success") is not True:
        raise ValueError(f"SWUStats refused the save ({data}); nothing was written.")
    logger.info(f"Saved deck {deck_id}: {len(ops)} change(s) in one batch.")
    return data
