"""Tool for retrieving user deck lists."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded access token for now
ACCESS_TOKEN = "daa7dd1ec7a962b89500749b3be7d6def43f1883"


async def fetch_user_decks() -> dict[str, Any]:
    """
    Fetch user deck lists from the SWU stats API.
    
    Returns:
        Dictionary with deck list data
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://swustats.net/TCGEngine/APIs/UserAPIs/GetUserDecks.php?access_token={ACCESS_TOKEN}",
                timeout=10.0
            )
            resp.raise_for_status()
            data = resp.json()
            
            decks = data.get("decks", [])
            logger.info(f"✅ Fetched {len(decks)} decks from API")
            
            return {
                "decks": decks,
                "count": len(decks),
                "error": None
            }
    except Exception as e:
        logger.error(f"❌ Error fetching decks: {e}", exc_info=True)
        return {
            "decks": [],
            "count": 0,
            "error": f"Error fetching deck lists: {str(e)}"
        }


@function_tool
async def get_user_decks_tool(
    ctx: RunContextWrapper[AgentContext],
) -> str:
    """
    Get all user deck lists.
    
    Returns:
        A summary of available decks
    """
    try:
        logger.info("📋 GET_USER_DECKS TOOL CALLED")
        result = await fetch_user_decks()
        logger.info(f"✅ Decks fetched: {result['count']} total")
        
        # Handle errors
        if result["error"]:
            logger.warning(f"⚠️ Fetch error: {result['error']}")
            return f"Error: {result['error']}"
        
        if not result["decks"]:
            logger.info("No decks found")
            return "You don't have any deck lists saved yet."
        
        # Format deck list for display
        deck_list = []
        for deck in result["decks"][:10]:  # Show first 10 for brevity
            name = deck.get("name") or f"Deck {deck.get('id')}"
            is_fav = "⭐" if deck.get("is_favorite") else ""
            deck_list.append(f"• {name} {is_fav}".strip())
        
        summary = f"You have {result['count']} deck(s) saved:\n" + "\n".join(deck_list)
        if result['count'] > 10:
            summary += f"\n... and {result['count'] - 10} more"
        
        logger.info(f"✅ Returning deck list summary")
        return summary
        
    except Exception as e:
        logger.error(f"❌ EXCEPTION in get_user_decks_tool: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"
