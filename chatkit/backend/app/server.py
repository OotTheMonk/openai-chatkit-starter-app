"""ChatKit server that streams responses from a single assistant."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Annotated
from pathlib import Path
import httpx
import re
from datetime import datetime

from agents import Runner, Agent, function_tool, RunContextWrapper
from chatkit.agents import AgentContext, simple_to_agent_input, stream_agent_response
from chatkit.server import ChatKitServer
from chatkit.actions import Action
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
from .deck_state import DeckStateManager
from .tools import (
    get_user_decks_tool,
    set_active_deck_tool,
    get_active_deck_tool,
    load_deck_contents_tool,
)

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
        "You can search for cards and manage the user's deck collections.\n"
        "\n"
        "TOOLS AVAILABLE:\n"
        "- search_cards: Search the card database\n"
        "- get_user_decks: Retrieve user's saved deck lists\n"
        "- set_active_deck: Select which deck to work with\n"
        "- get_active_deck: See which deck is currently active\n"
        "- load_deck_contents: Load and view a deck's cards\n"
        "\n"
        "WHEN TO USE EACH TOOL:\n"
        "\n"
        "CARD SEARCHES: Use search_cards for:\n"
        "- 'Find Luke Skywalker'\n"
        "- 'Search for cards with stealth'\n"
        "- 'What cards cancel opponent events?'\n"
        "- 'Show me Yoda cards'\n"
        "\n"
        "DECK MANAGEMENT: Use deck tools for:\n"
        "- 'Show my decks' or 'List my decks' -> use get_user_decks\n"
        "- 'Load my deck' or 'Show my deck contents' -> use load_deck_contents\n"
        "- 'Select deck X' or 'Use deck X' -> use set_active_deck\n"
        "- 'What deck am I using?' -> use get_active_deck\n"
        "\n"
        "IMPORTANT: When user asks about their decks, ALWAYS authenticate first.\n"
        "If you get an authentication error, provide them with the login URL\n"
        "and let them know they need to log in to SWU Stats.\n"
        "\n"
        "Always use the relevant tool for the user's request - don't guess!"
    ),
    tools=[
        search_cards,
        get_user_decks_tool,
        set_active_deck_tool,
        get_active_deck_tool,
        load_deck_contents_tool,
    ],
)

logger.info(f"✅ Agent created with {len(assistant_agent.tools)} tools")
logger.info(f"✅ Model: {MODEL}")
logger.info(f"✅ Tool names: {[str(t) for t in assistant_agent.tools]}")



class StarterChatServer(ChatKitServer[dict[str, Any]]):
    """Server implementation that keeps conversation state in memory."""

    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore()
        self.deck_manager: DeckStateManager = DeckStateManager()
        super().__init__(self.store)

    async def respond(
        self,
        thread: ThreadMetadata,
        item: UserMessageItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        logger.info(f"📨 User message: {item.content if item else 'None'}")
        
        # Ensure deck_manager is in context
        if "deck_manager" not in context:
            context["deck_manager"] = self.deck_manager
        
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

    async def action(
        self,
        thread: ThreadMetadata,
        action: Action[str, Any],
        sender: Any | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        """
        Handle widget actions (e.g., deck selection).
        
        Args:
            thread: Thread metadata
            action: Action object with type and payload
            sender: Widget item that sent the action
            context: Request context
        
        Yields:
            ThreadStreamEvent responses
        """
        logger.info(f"🎯 ACTION HANDLER called")
        logger.info(f"   Action type: {action.type}")
        logger.info(f"   Action payload: {action.payload}")
        logger.info(f"   Sender: {sender}")
        
        # Handle deck selection actions
        if action.type == "select_deck":
            try:
                deck_id = action.payload.get("deck_id")
                deck_name = action.payload.get("deck_name")
                
                if not deck_id or not deck_name:
                    logger.error(f"❌ Invalid payload for select_deck: {action.payload}")
                    return
                
                logger.info(f"✅ Deck selected: {deck_name} (ID: {deck_id})")
                
                # Set the active deck using the server's deck_manager
                thread_id = thread.id
                result = self.deck_manager.set_active_deck(thread_id, deck_id, deck_name)
                logger.info(f"✅ Deck manager result: {result}")
                
                # Emit client effect to refresh UI
                from chatkit.types import ClientEffectEvent
                yield ClientEffectEvent(
                    name="deck_refresh",
                    data={"deck_id": deck_id, "deck_name": deck_name},
                )
                
            except Exception as e:
                logger.error(f"❌ Error handling select_deck action: {e}", exc_info=True)
        else:
            logger.warning(f"⚠️ Unknown action type: {action.type}")
