"""ChatKit server that streams responses from a single assistant."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Annotated
from pathlib import Path
import httpx
import re
from datetime import datetime

from agents import Runner, Agent, function_tool, RunContextWrapper, StopAtTools
from chatkit.agents import AgentContext, simple_to_agent_input, stream_agent_response
from chatkit.server import ChatKitServer
from chatkit.types import (
    ThreadMetadata, 
    ThreadStreamEvent, 
    UserMessageItem,
    AssistantMessageItem,
    AssistantMessageContent,
    ThreadItemDoneEvent,
)
from chatkit.widgets import WidgetTemplate
from pydantic import Field

from .memory_store import MemoryStore
from .card_search_widget import build_card_search_widget

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_RECENT_ITEMS = 30
MODEL = "gpt-4o"  # Use full gpt-4o for better tool calling support


# ============================================================================
# Custom Agent Context
# ============================================================================

class CardSearchAgentContext(AgentContext):
    """Agent context with access to card search functionality."""
    store: Annotated[MemoryStore, Field(exclude=True)]
    widget_data: dict[str, Any] = Field(default_factory=dict, exclude=True)


# ============================================================================
# Card Search Tool
# ============================================================================

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
async def search_cards(
    ctx: RunContextWrapper[CardSearchAgentContext],
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
        logger.error(f"❌ EXCEPTION in search_cards: {type(e).__name__}: {e}", exc_info=True)
        return f"Error: {str(e)}"


# ============================================================================
# Create Agent with Card Search Tool
# ============================================================================

assistant_agent = Agent[CardSearchAgentContext](
    model=MODEL,
    name="Card Search Assistant",
    instructions=(
        "You are an expert Star Wars Unlimited card game assistant. "
        "Your ONLY job is to search for Star Wars Unlimited cards and report the results. "
        "\n"
        "CRITICAL RULE: You MUST use the search_cards tool for EVERY user message about cards. "
        "Do not provide general knowledge or generic answers. Always search the database first.\n"
        "\n"
        "USE THE TOOL FOR QUERIES LIKE:\n"
        "- 'Find Luke Skywalker'\n"
        "- 'Search for cards that cancel opponent events'\n"
        "- 'What cards have stealth?'\n"
        "- 'Show me cards named Yoda'\n"
        "- 'Find cards with high cost'\n"
        "- 'Search for [any card mechanic, effect, or name]'\n"
        "- 'What cards do [something]?'\n"
        "\n"
        "MANDATORY: For ANY question that mentions:\n"
        "- Card names\n"
        "- Card abilities or effects\n"
        "- Card mechanics\n"
        "- Card types or costs\n"
        "- Strategy or deck building\n"
        "\n"
        "You MUST call search_cards with the relevant search term. Do NOT answer from memory or general knowledge.\n"
        "\n"
        "After searching, present results clearly with card names and any relevant details. "
        "If no results found, say 'No cards found matching that search.'"
    ),
    tools=[search_cards],
    tool_use_behavior=StopAtTools(stop_at_tool_names=["search_cards"]),
)

logger.info(f"✅ Agent created with {len(assistant_agent.tools)} tools")
logger.info(f"✅ Model: {MODEL}")
logger.info(f"✅ Tool names: {[str(t) for t in assistant_agent.tools]}")



class StarterChatServer(ChatKitServer[dict[str, Any]]):
    """Server implementation that keeps conversation state in memory."""

    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore()
        super().__init__(self.store)

    async def respond(
        self,
        thread: ThreadMetadata,
        item: UserMessageItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        logger.info(f"📨 User message: {item.content if item else 'None'}")
        
        # Create agent context with card search capabilities
        agent_context = CardSearchAgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )
        
        items_page = await self.store.load_thread_items(
            thread.id,
            after=None,
            limit=MAX_RECENT_ITEMS,
            order="desc",
            context=context,
        )
        items = list(reversed(items_page.data))
        agent_input = await simple_to_agent_input(items)

        logger.info(f"🤖 Running agent with {len(items)} conversation items")
        logger.info(f"🛠️ Agent has tools: {[t.name if hasattr(t, 'name') else str(t) for t in assistant_agent.tools]}")
        
        result = Runner.run_streamed(
            assistant_agent,
            agent_input,
            context=agent_context,
        )
        
        logger.info(f"💭 Runner returned: {type(result)}")
        
        event_count = 0
        async for event in stream_agent_response(agent_context, result):
            event_count += 1
            event_type = type(event).__name__
            logger.info(f"📤 Event {event_count}: {event_type}")
            if hasattr(event, 'content'):
                content_preview = str(event.content)[:100]
                logger.info(f"   Content: {content_preview}")
            yield event
        
        logger.info(f"✅ Finished streaming {event_count} events")
