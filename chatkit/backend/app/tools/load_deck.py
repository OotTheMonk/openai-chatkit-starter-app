"""Tool for loading deck contents."""

from __future__ import annotations

import logging
from typing import Any

# httpx is re-exported from ..swu so tests can patch httpx.AsyncClient here.
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext

from ..config import get_access_token, SWUSTATS_API_BASE, SERVER_BASE_URL
from ..swu import httpx, SWU_HEADERS, track_request, describe_deck_contents

logger = logging.getLogger(__name__)


async def fetch_deck_contents(deck_id: int, user_id: str = "default") -> dict[str, Any]:
    """
    Fetch deck contents from the SWU stats API.
    
    Args:
        deck_id: The ID of the deck to load
        user_id: User identifier for OAuth token lookup
    
    Returns:
        Dictionary with deck data including cards, leader, base, sideboard
    """
    try:
        # Get access token (handles OAuth refresh automatically)
        access_token = await get_access_token(user_id)
        
        if not access_token:
            logger.warning("⚠️ No access token available - user not authenticated")
            return {
                "deck_id": deck_id,
                "metadata": {},
                "leader": None,
                "base": None,
                "deck": [],
                "sideboard": [],
                "error": "not_authenticated",
                "login_url": f"{SERVER_BASE_URL}/oauth/login?user_id={user_id}"
            }
        
        async with httpx.AsyncClient(timeout=30.0, headers=SWU_HEADERS) as client:
            resp = await client.get(
                f"{SWUSTATS_API_BASE}/LoadDeck.php",
                params={
                    "access_token": access_token,
                    "deckID": deck_id
                },
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            
            logger.info(f"✅ Loaded deck {deck_id}: {data.get('metadata', {}).get('name', 'Unknown')}")
            
            return {
                "deck_id": deck_id,
                "metadata": data.get("metadata", {}),
                "leader": data.get("leader"),
                "base": data.get("base"),
                "deck": data.get("deck", []),
                "sideboard": data.get("sideboard", []),
                "error": None
            }
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.warning("⚠️ Access token expired or invalid")
            return {
                "deck_id": deck_id,
                "metadata": {},
                "leader": None,
                "base": None,
                "deck": [],
                "sideboard": [],
                "error": "token_expired",
                "login_url": f"{SERVER_BASE_URL}/oauth/login?user_id={user_id}"
            }
        logger.error(f"❌ Error loading deck {deck_id}: {e}", exc_info=True)
        return {
            "deck_id": deck_id,
            "metadata": {},
            "leader": None,
            "base": None,
            "deck": [],
            "sideboard": [],
            "error": f"Error loading deck: {str(e)}"
        }
    except Exception as e:
        logger.error(f"❌ Error loading deck {deck_id}: {e}", exc_info=True)
        return {
            "deck_id": deck_id,
            "metadata": {},
            "leader": None,
            "base": None,
            "deck": [],
            "sideboard": [],
            "error": f"Error loading deck: {str(e)}"
        }


@function_tool
async def load_deck_contents_tool(
    ctx: RunContextWrapper[AgentContext],
    deck_id: int | None = None,
) -> str:
    """
    Load the contents of a deck. If no deck_id is provided, loads the active deck.
    
    Args:
        deck_id: Optional deck ID to load. If not provided, uses the active deck.
    
    Returns:
        Summary of the deck contents
    """
    try:
        logger.info(f"📦 LOAD_DECK_CONTENTS TOOL CALLED with deck_id={deck_id}")
        
        # If no deck_id provided, try to use the active deck
        deck_manager = ctx.context.request_context.get("deck_manager")
        if deck_id is None:
            if deck_manager:
                thread_id = ctx.context.thread.id
                active_id, active_name = deck_manager.get_active_deck(thread_id)
                if active_id:
                    deck_id = active_id
                    logger.info(f"📦 Using active deck: {active_name} (ID: {deck_id})")
                else:
                    return "❌ No active deck set. Please select a deck first using 'show my decks'."
            else:
                return "❌ No deck_id provided and no active deck available."
        
        state = deck_manager.get_state(ctx.context.thread.id) if deck_manager else None
        if state and state.active_deck_id == deck_id and state.deck_contents and not state.deck_contents.get("error"):
            result = state.deck_contents
        else:
            result = await track_request(ctx.context, f"Loading deck {deck_id} from SWUStats", lambda: fetch_deck_contents(deck_id), describe_deck_contents)

        if result.get("error") in ("not_authenticated", "token_expired"):
            request = ctx.context.request_context.get("request")
            base_url = str(request.base_url).rstrip("/") if request else SERVER_BASE_URL
            return (
                "Connect your SWUStats account to load this deck: "
                f"[Connect SWUStats]({base_url}/oauth/login). Then try again."
            )
        
        if result["error"]:
            return f"❌ {result['error']}"
        
        # Store the deck contents in the deck state for later use
        deck_manager = ctx.context.request_context.get("deck_manager")
        if deck_manager:
            thread_id = ctx.context.thread.id
            state = deck_manager.get_state(thread_id)
            if state.active_deck_id == deck_id:
                state.deck_contents = result
                deck_manager.save()
            logger.info(f"📦 Stored deck contents in state for thread {thread_id}")
        
        # Build a summary
        deck_name = result["metadata"].get("name", f"Deck #{deck_id}")
        main_deck_count = sum(card.get("count", 0) for card in result["deck"])
        sideboard_count = sum(card.get("count", 0) for card in result["sideboard"])
        
        summary_parts = [
            f"**{deck_name}**",
            f"- Main deck: {main_deck_count} cards ({len(result['deck'])} unique)",
            f"- Sideboard: {sideboard_count} cards ({len(result['sideboard'])} unique)",
        ]
        
        if result["leader"] or result["base"]:
            summary_parts.append("- Leader, base, and cards are visible in the deck inspector.")
        
        return "\n".join(summary_parts)
        
    except Exception as e:
        logger.error(f"❌ EXCEPTION in load_deck_contents_tool: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"
