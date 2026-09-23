"""Tool for retrieving user deck lists."""

from __future__ import annotations

import logging
from typing import Any

# httpx is re-exported from ..swu so tests can patch httpx.AsyncClient here.
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext
from ..deck_list_widget import build_deck_list_widget
from ..config import get_access_token, SWUSTATS_API_BASE, SERVER_BASE_URL
from ..swu import httpx, SWU_HEADERS, track_request, describe_decks

logger = logging.getLogger(__name__)


async def fetch_user_decks(user_id: str = "default") -> dict[str, Any]:
    """
    Fetch user deck lists from the SWU stats API.
    
    Args:
        user_id: User identifier for OAuth token lookup
    
    Returns:
        Dictionary with deck list data
    """
    try:
        # Get access token (handles OAuth refresh automatically)
        access_token = await get_access_token(user_id)
        
        if not access_token:
            logger.warning("⚠️ No access token available - user not authenticated")
            return {
                "decks": [],
                "count": 0,
                "error": "not_authenticated",
                "login_url": f"{SERVER_BASE_URL}/oauth/login?user_id={user_id}"
            }
        
        async with httpx.AsyncClient(timeout=30.0, headers=SWU_HEADERS) as client:
            resp = await client.get(
                f"{SWUSTATS_API_BASE}/UserAPIs/GetUserDecks.php",
                params={"access_token": access_token},
                timeout=30.0
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
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.warning("⚠️ Access token expired or invalid")
            return {
                "decks": [],
                "count": 0,
                "error": "token_expired",
                "login_url": f"{SERVER_BASE_URL}/oauth/login?user_id={user_id}"
            }
        logger.error(f"❌ Error fetching decks: {e}", exc_info=True)
        return {
            "decks": [],
            "count": 0,
            "error": f"Error fetching deck lists: {str(e)}"
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
        result = await track_request(ctx.context, "Loading saved decks from SWUStats", fetch_user_decks, describe_decks)
        logger.info(f"✅ Decks fetched: {result['count']} total")
        
        # Handle authentication errors with helpful message
        if result.get("error") in ("not_authenticated", "token_expired"):
            request = ctx.context.request_context.get("request")
            base_url = str(request.base_url).rstrip("/") if request else SERVER_BASE_URL
            login_url = f"{base_url}/oauth/login"
            return (
                "🔒 **Authentication Required**\n\n"
                "You need to connect your SWU Stats account to view your decks.\n\n"
                f"Please [click here to log in]({login_url}) and then try again."
            )
        
        # Handle other errors
        if result["error"]:
            logger.warning(f"⚠️ Fetch error: {result['error']}")
            return f"Error: {result['error']}"
        
        if not result["decks"]:
            logger.info("No decks found")
            return "You don't have any deck lists saved yet."
        
        # Get active deck info from deck manager
        deck_manager = ctx.context.request_context.get("deck_manager")
        active_deck_id, active_deck_name = None, None
        if deck_manager:
            thread_id = ctx.context.thread.id
            active_deck_id, active_deck_name = deck_manager.get_active_deck(thread_id)
        
        # Sort decks: favorites first, then by name
        sorted_decks = sorted(
            result["decks"],
            key=lambda d: (not d.get("is_favorite", False), d.get("name") or f"Unnamed {d.get('id', 0)}")
        )
        
        # Build and stream the widget with deck results
        logger.info(f"📊 Building widget for {result['count']} decks (active: {active_deck_id})")
        widget = build_deck_list_widget(
            sorted_decks, 
            result["count"],
            active_deck_id=active_deck_id,
            active_deck_name=active_deck_name
        )
        logger.info(f"📊 Widget built successfully")
        
        # Create copy text with deck names
        deck_names = [deck.get("name") or f"Deck {deck.get('id')}" for deck in sorted_decks]
        copy_text = "\n".join(deck_names)
        logger.info(f"📊 About to stream widget")
        
        await ctx.context.stream_widget(widget, copy_text=copy_text)
        logger.info(f"✅ Widget streamed with {result['count']} decks")
        
        return f"Found {result['count']} deck list(s)."
        
    except Exception as e:
        logger.error(f"❌ EXCEPTION in get_user_decks_tool: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"
