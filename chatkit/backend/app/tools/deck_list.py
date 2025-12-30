"""Tool for retrieving user deck lists."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext
from ..deck_list_widget import build_deck_list_widget
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded access token for now
ACCESS_TOKEN = "59c82a619479a64495a25d02c8e0ef549e0c66be"


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
        Message confirming widget was displayed
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
        
        # Build and stream the widget with deck results
        logger.info(f"📊 Building widget for {result['count']} decks")
        widget = build_deck_list_widget(result["decks"], result["count"])
        logger.info(f"📊 Widget built successfully")
        
        # Create copy text with deck names
        deck_names = [deck.get("name") or f"Deck {deck.get('id')}" for deck in result["decks"]]
        copy_text = "\n".join(deck_names)
        logger.info(f"📊 About to stream widget")
        
        await ctx.context.stream_widget(widget, copy_text=copy_text)
        logger.info(f"✅ Widget streamed with {result['count']} decks")
        
        return f"Found {result['count']} deck list(s)."
        
    except Exception as e:
        logger.error(f"❌ EXCEPTION in get_user_decks_tool: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"
