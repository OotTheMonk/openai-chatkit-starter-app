"""Tool for searching Star Wars Unlimited cards."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import re
from agents import RunContextWrapper, function_tool
from chatkit.agents import AgentContext

from ..card_search_widget import build_card_search_widget

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def search_cards_direct(query: str) -> dict[str, Any]:
    """
    Directly search for Star Wars Unlimited cards (not a tool, used internally).
    
    Args:
        query: Card name, keywords, or any search term
    
    Returns:
        Dictionary with card results and metadata for widget display
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://142.11.210.6/es/swucardsearch.php",
                data={"searchInput": query},
                timeout=10.0
            )
            # Extract the <ul>...</ul> block
            ul_match = re.search(r"<ul>(.*?)</ul>", resp.text, re.DOTALL)
            if not ul_match:
                return {
                    "query": query,
                    "cards": [],
                    "count": 0,
                    "error": None
                }
            ul_content = ul_match.group(1)
            # Extract all <li>...</li> items
            items = re.findall(r"<li>(.*?)</li>", ul_content, re.DOTALL)
            # Clean up and parse as structured data
            cards = []
            for item in items:
                cleaned = re.sub(r"<.*?>", "", item).strip()
                if cleaned:
                    cards.append({"name": cleaned, "raw": cleaned})
            
            return {
                "query": query,
                "cards": cards,
                "count": len(cards),
                "error": None
            }
    except Exception as e:
        return {
            "query": query,
            "cards": [],
            "count": 0,
            "error": f"Error searching cards: {e}"
        }


@function_tool
async def search_cards_tool(
    ctx: RunContextWrapper[AgentContext],
    query: str,
) -> str:
    """
    Search for Star Wars Unlimited cards.
    
    Args:
        query: Card name, keywords, or any search term
    
    Returns:
        Message confirming widget was displayed
    """
    try:
        logger.info(f"🔍 SEARCH TOOL CALLED with query: {query}")
        result = await search_cards_direct(query)
        logger.info(f"✅ Search returned {result['count']} cards")
        
        # Handle errors
        if result["error"]:
            logger.warning(f"⚠️ Search error: {result['error']}")
            return f"Error: {result['error']}"
        
        if not result["cards"]:
            logger.info(f"No cards found for '{query}'")
            return f"No cards found matching '{query}'."
        
        # Build and stream the widget with card results
        logger.info(f"📊 Building widget for {result['count']} cards")
        widget = build_card_search_widget(query, result["cards"], result["count"])
        logger.info(f"📊 Widget built successfully")
        
        copy_text = "\n".join([card['name'] for card in result["cards"]])
        logger.info(f"📊 About to stream widget with copy_text length: {len(copy_text)}")
        
        await ctx.context.stream_widget(widget, copy_text=copy_text)
        logger.info(f"✅ Widget streamed with {result['count']} cards for '{query}'")
        
        return f"Found {result['count']} results for '{query}'."
    except Exception as e:
        logger.error(f"❌ EXCEPTION in search_cards_tool: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"
