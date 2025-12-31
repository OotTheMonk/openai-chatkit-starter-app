"""Tool for loading deck contents."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext

from ..config import SWUSTATS_ACCESS_TOKEN, SWUSTATS_API_BASE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def fetch_deck_contents(deck_id: int) -> dict[str, Any]:
    """
    Fetch deck contents from the SWU stats API.
    
    Args:
        deck_id: The ID of the deck to load
    
    Returns:
        Dictionary with deck data including cards, leader, base, sideboard
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SWUSTATS_API_BASE}/LoadDeck.php",
                params={
                    "access_token": SWUSTATS_ACCESS_TOKEN,
                    "deckID": deck_id
                },
                timeout=10.0
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
        if deck_id is None:
            deck_manager = ctx.context.request_context.get("deck_manager")
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
        
        result = await fetch_deck_contents(deck_id)
        
        if result["error"]:
            return f"❌ {result['error']}"
        
        # Store the deck contents in the deck state for later use
        deck_manager = ctx.context.request_context.get("deck_manager")
        if deck_manager:
            thread_id = ctx.context.thread.id
            state = deck_manager.get_state(thread_id)
            state.deck_contents = result
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
        
        if result["leader"]:
            summary_parts.append(f"- Leader ID: {result['leader'].get('id', 'Unknown')}")
        if result["base"]:
            summary_parts.append(f"- Base ID: {result['base'].get('id', 'Unknown')}")
        
        return "\n".join(summary_parts)
        
    except Exception as e:
        logger.error(f"❌ EXCEPTION in load_deck_contents_tool: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"
